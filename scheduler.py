"""Automated Scheduler for Daily Briefings and Outcome Checks."""

import logging
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from telegram.ext import Application
from core.ledger import LedgerDB
from core.models import BetRecord
from intelligence.agent_router import AgentRouterClient
from data_sources.odds_api import OddsApiClient
from telegram_bot.keyboards import get_pick_action_keyboard
from telegram_bot import messages
import config

logger = logging.getLogger(__name__)


def setup_scheduler(
    app: Application,
    ledger: LedgerDB,
    agent: AgentRouterClient,
    odds_api: OddsApiClient
) -> AsyncIOScheduler:
    """Configures the daily cron scheduler for automated morning briefings."""
    try:
        from zoneinfo import ZoneInfo
        tz = ZoneInfo(config.TIMEZONE)
    except Exception:
        tz = None

    scheduler = AsyncIOScheduler(timezone=tz)

    time_parts = config.DAILY_BRIEFING_TIME.split(":")
    hour = int(time_parts[0]) if len(time_parts) > 0 else 10
    minute = int(time_parts[1]) if len(time_parts) > 1 else 30

    async def morning_briefing_job():
        target_chat_id = config.TELEGRAM_ALLOWED_USER_ID
        if not target_chat_id:
            logger.info("Scheduler: No TELEGRAM_ALLOWED_USER_ID configured. Skipping automated push.")
            return

        try:
            user_id = int(target_chat_id)
            state = ledger.get_or_create_user(user_id)
            fixtures_data = await odds_api.get_upcoming_fixtures_summary()

            prediction = await agent.analyze_and_predict(
                fixtures_summary=fixtures_data,
                current_day=state.current_day,
                current_balance=state.current_balance,
                currency=config.DEFAULT_CURRENCY,
            )

            # Automatically book on SportyBet to generate live booking code & 1-click URL
            try:
                from intelligence.sportybet_service import SportyBetService
                sporty_service = SportyBetService()
                prediction = sporty_service.book_prediction(prediction)
            except Exception as be:
                logger.warning(f"Could not generate live SportyBet booking code: {be}")

            event_names = " + ".join([s.fixture for s in prediction.selections])
            market_names = " + ".join([s.market for s in prediction.selections])
            selection_names = " + ".join([s.selection for s in prediction.selections])

            bet = BetRecord(
                day_number=state.current_day,
                event_name=event_names,
                market=market_names,
                selection=selection_names,
                odds=prediction.combined_odds,
                stake=prediction.suggested_stake,
                potential_return=round(prediction.suggested_stake * prediction.combined_odds, 2),
                booking_code=prediction.booking_code,
                booking_url=prediction.booking_url,
                outcome="PENDING",
            )
            bet_id = ledger.record_bet(user_id=user_id, bet=bet)

            pick_msg = messages.format_daily_pick_message(prediction, state)
            primary_sport = prediction.selections[0].sport if prediction.selections else "football"
            await app.bot.send_message(
                chat_id=user_id,
                text=pick_msg,
                parse_mode="Markdown",
                reply_markup=get_pick_action_keyboard(
                    bet_id,
                    sport=primary_sport,
                    booking_url=prediction.booking_url,
                    booking_code=prediction.booking_code,
                ),
            )
            logger.info(f"Morning pick successfully dispatched to user {user_id}")
        except Exception as e:
            logger.error(f"Error executing morning briefing job: {e}")

    # 1. Schedule daily morning briefing
    scheduler.add_job(
        morning_briefing_job,
        trigger="cron",
        hour=hour,
        minute=minute,
        timezone=tz,
        id="morning_briefing_job",
        replace_existing=True,
    )

    # 2. Automated Settlement Job: checks match scores every 10 minutes and grades pending bets
    from core.auto_settler import AutoSettler
    auto_settler = AutoSettler(ledger=ledger)

    async def auto_settlement_job():
        try:
            settled = auto_settler.check_and_settle_all(bot_app=app)
            if settled:
                logger.info(f"Auto-settler automatically graded {len(settled)} bets.")
        except Exception as ex:
            logger.warning(f"Auto-settler job encounter: {ex}")

    scheduler.add_job(
        auto_settlement_job,
        trigger="interval",
        minutes=10,
        id="auto_settlement_job",
        replace_existing=True,
    )

    tz_label = str(tz) if tz else "local"
    logger.info(f"Scheduler configured: Morning briefing at {hour:02d}:{minute:02d} {tz_label}, Auto-settler every 10m")
    return scheduler

