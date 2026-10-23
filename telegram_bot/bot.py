"""Telegram Bot Handlers and Application Factory."""

import logging
from typing import Optional, Callable
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

from core.ledger import LedgerDB
from core.models import BetRecord
from intelligence.agent_router import AgentRouterClient
from data_sources.odds_api import OddsApiClient
from telegram_bot.keyboards import get_pick_action_keyboard, get_main_reply_keyboard, get_sport_selector_keyboard
from telegram_bot import messages
from intelligence.postmortem import analyze_loss
from core.auto_settler import AutoSettler
import config

logger = logging.getLogger(__name__)


class TelegramBetBot:
    def __init__(self, ledger: LedgerDB, agent: AgentRouterClient, odds_api: OddsApiClient):
        self.ledger = ledger
        self.agent = agent
        self.odds_api = odds_api
        self.auto_settler = AutoSettler(ledger=self.ledger)

    def is_user_allowed(self, user_id: int) -> bool:
        """Restricts bot to designated user if TELEGRAM_ALLOWED_USER_ID is set."""
        if config.TELEGRAM_ALLOWED_USER_ID:
            allowed_id = config.TELEGRAM_ALLOWED_USER_ID.strip()
            return allowed_id == "" or str(user_id) == allowed_id
        return True

    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        if not self.is_user_allowed(user_id):
            await update.message.reply_text("⛔ Unauthorized access.")
            return

        state = self.ledger.get_or_create_user(user_id, initial_stake=config.DEFAULT_INITIAL_STAKE)
        msg = messages.format_welcome_message(user_id, state)
        await update.message.reply_text(
            msg,
            parse_mode="Markdown",
            reply_markup=get_main_reply_keyboard(),
        )

    async def today_pick_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        if not self.is_user_allowed(user_id):
            return

        # Trigger background auto-settlement asynchronously without blocking user response
        import asyncio
        try:
            asyncio.create_task(asyncio.to_thread(self.auto_settler.check_and_settle_all, context.application))
        except Exception as e:
            logger.debug(f"Auto-settler background task error: {e}")

        status_msg = await update.message.reply_text("⚡ *Selecting today's top winning pick...*", parse_mode="Markdown")

        state = self.ledger.get_or_create_user(user_id)
        fixtures_data = await self.odds_api.get_upcoming_fixtures_summary(basketball_limit=60)

        # Run AI reasoning
        prediction = await self.agent.analyze_and_predict(
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

        existing_proposed = self.ledger.get_proposed_bet(user_id)
        if existing_proposed:
            self.ledger.clear_bet(user_id, existing_proposed.id)

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
            outcome="PROPOSED",
        )
        bet_id = self.ledger.record_bet(user_id=user_id, bet=bet)

        pick_msg = messages.format_daily_pick_message(prediction, state)
        primary_sport = prediction.selections[0].sport if prediction.selections else "basketball"
        try:
            await status_msg.delete()
        except Exception:
            pass
        await update.message.reply_text(
            pick_msg,
            parse_mode="Markdown",
            reply_markup=get_pick_action_keyboard(
                bet_id,
                sport=primary_sport,
                booking_url=prediction.booking_url,
                booking_code=prediction.booking_code,
            ),
        )

    async def balance_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        if not self.is_user_allowed(user_id):
            return

        # Trigger background auto-settlement asynchronously without blocking user response
        import asyncio
        try:
            asyncio.create_task(asyncio.to_thread(self.auto_settler.check_and_settle_all, context.application))
        except Exception as e:
            logger.debug(f"Auto-settler check in balance error: {e}")

        state = self.ledger.get_or_create_user(user_id)
        msg = messages.format_balance_message(state)
        await update.message.reply_text(msg, parse_mode="Markdown")

    async def cycle_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        if not self.is_user_allowed(user_id):
            return

        state = self.ledger.get_or_create_user(user_id)
        msg = messages.format_cycle_plan_message(initial_stake=state.initial_stake, currency=config.DEFAULT_CURRENCY)
        await update.message.reply_text(msg, parse_mode="Markdown")

    async def recent_bets_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        if not self.is_user_allowed(user_id):
            return

        # Proactively check and grade any concluded bets before displaying history
        try:
            self.auto_settler.check_and_settle_all(bot_app=context.application)
        except Exception as e:
            logger.debug(f"Auto-settler check in bets: {e}")

        bets = self.ledger.get_recent_bets(user_id=user_id, limit=5)
        msg = messages.format_recent_bets_message(bets, currency=config.DEFAULT_CURRENCY)
        await update.message.reply_text(msg, parse_mode="Markdown")


    async def win_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        if not self.is_user_allowed(user_id):
            return

        actual_payout = None
        if context.args and len(context.args) > 0:
            try:
                raw_arg = context.args[0].replace(",", "").replace("$", "").replace("₦", "")
                actual_payout = float(raw_arg)
            except ValueError:
                pass

        outcome = self.ledger.log_bet_outcome(user_id=user_id, won=True, actual_payout=actual_payout)
        msg = messages.format_outcome_win_message(outcome, currency=config.DEFAULT_CURRENCY)
        await update.message.reply_text(msg, parse_mode="Markdown")

    async def loss_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        if not self.is_user_allowed(user_id):
            return

        recent_before = self.ledger.get_recent_bets(user_id=user_id, limit=1)
        outcome = self.ledger.log_bet_outcome(user_id=user_id, won=False)
        msg = messages.format_outcome_loss_message(outcome, currency=config.DEFAULT_CURRENCY)
        await update.message.reply_text(msg, parse_mode="Markdown")

        # Run AI Postmortem forensic analysis
        if recent_before:
            last_bet = recent_before[0]
            try:
                status_msg = await update.message.reply_text("🔬 *Conducting AI postmortem on the loss to extract learning rules...*", parse_mode="Markdown")
                analysis = await analyze_loss(self.agent, last_bet.event_name, last_bet.selection, last_bet.odds)
                await status_msg.edit_text(
                    f"🧠 *AI Postmortem Forensic Analysis:*\n\n{analysis}\n\n_Heuristic rule saved. Future pre-match filters will strictly avoid this trap._",
                    parse_mode="Markdown",
                )
            except Exception as e:
                logger.error(f"Postmortem error: {e}")

    async def reset_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        if not self.is_user_allowed(user_id):
            return

        self.ledger.reset_challenge(user_id=user_id, initial_stake=config.DEFAULT_INITIAL_STAKE)
        await update.message.reply_text(
            f"🔄 *Challenge Reset!* Ready to begin Day 1 with {config.DEFAULT_INITIAL_STAKE:,.2f} {config.DEFAULT_CURRENCY}.",
            parse_mode="Markdown",
        )

    async def placed_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        if not self.is_user_allowed(user_id):
            return

        recent = self.ledger.get_recent_bets(user_id=user_id, limit=5)
        proposed = next((b for b in recent if b.outcome == "PROPOSED"), None)
        if not proposed:
            active = next((b for b in recent if b.outcome in ("PLACED", "PENDING")), None)
            if active:
                await update.message.reply_text(
                    f"🔒 *Bet Already Active & Monitored:*\n\n"
                    f"• Fixture: `{active.event_name}`\n"
                    f"• Pick: `{active.selection}` @ `{active.odds:.2f}`\n"
                    f"• Code: `{active.booking_code or 'Direct'}`\n\n"
                    "The bot is already monitoring this game live. You'll be notified automatically once the match concludes!",
                    parse_mode="Markdown",
                )
            else:
                await update.message.reply_text(
                    "ℹ️ No active prediction waiting to be placed. Tap `/today` first to generate today's pick!",
                    parse_mode="Markdown",
                )
            return

        placed_bet = self.ledger.confirm_bet_placed(user_id=user_id, bet_id=proposed.id)
        if placed_bet:
            conf_msg = messages.format_bet_placed_confirmation(placed_bet, currency=config.DEFAULT_CURRENCY)
            await update.message.reply_text(conf_msg, parse_mode="Markdown")
        else:
            await update.message.reply_text("⚠️ Could not mark bet as placed.", parse_mode="Markdown")

    async def clear_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        if not self.is_user_allowed(user_id):
            return

        recent = self.ledger.get_recent_bets(user_id=user_id, limit=5)
        target = next((b for b in recent if b.outcome in ("PROPOSED", "PLACED", "PENDING")), None)
        if not target:
            await update.message.reply_text("ℹ️ No active bet or prediction to clear.", parse_mode="Markdown")
            return

        self.ledger.clear_bet(user_id=user_id, bet_id=target.id)
        conf_msg = messages.format_bet_cleared_confirmation()
        await update.message.reply_text(conf_msg, parse_mode="Markdown")

    async def helper_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        if not self.is_user_allowed(user_id):
            return

        recent = self.ledger.get_recent_bets(user_id=user_id, limit=5)
        target_bet = next((b for b in recent if b.outcome in ("PROPOSED", "PLACED", "PENDING")), None)
        if not target_bet:
            await update.message.reply_text(
                "ℹ️ No active bet or pick found. Tap `/today` first to generate today's pick!",
                parse_mode="Markdown",
            )
            return

        help_text = messages.format_sportybet_helper_message(target_bet, currency=config.DEFAULT_CURRENCY)
        await update.message.reply_text(help_text, parse_mode="Markdown")

    async def reroll_pick_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE, message_target=None):
        user_id = update.effective_user.id
        if not self.is_user_allowed(user_id):
            return

        state = self.ledger.get_or_create_user(user_id)
        proposed = self.ledger.get_proposed_bet(user_id)
        exclude_fixtures = []
        if proposed:
            exclude_fixtures = [f.strip() for f in proposed.event_name.split("+") if f.strip()]

        reply_to = message_target or (update.message or (update.callback_query.message if update.callback_query else None))
        status_msg = await reply_to.reply_text("🔄 *Rerolling an alternative high-conviction NBA pick...*", parse_mode="Markdown")

        fixtures_data = await self.odds_api.get_upcoming_fixtures_summary(
            basketball_limit=60,
            exclude_fixtures=exclude_fixtures,
            force_refresh=True,
        )

        prediction = await self.agent.analyze_and_predict(
            fixtures_summary=fixtures_data,
            current_day=state.current_day,
            current_balance=state.current_balance,
            currency=config.DEFAULT_CURRENCY,
            exclude_fixtures=exclude_fixtures,
        )

        try:
            from intelligence.sportybet_service import SportyBetService
            sporty_service = SportyBetService()
            prediction = sporty_service.book_prediction(prediction)
        except Exception as be:
            logger.warning(f"Could not generate live SportyBet booking code on reroll: {be}")

        event_names = " + ".join([s.fixture for s in prediction.selections])
        market_names = " + ".join([s.market for s in prediction.selections])
        selection_names = " + ".join([s.selection for s in prediction.selections])

        if proposed:
            self.ledger.clear_bet(user_id, proposed.id)

        new_bet = BetRecord(
            day_number=state.current_day,
            event_name=event_names,
            market=market_names,
            selection=selection_names,
            odds=prediction.combined_odds,
            stake=prediction.suggested_stake,
            potential_return=round(prediction.suggested_stake * prediction.combined_odds, 2),
            booking_code=prediction.booking_code,
            booking_url=prediction.booking_url,
            outcome="PROPOSED",
        )
        bet_id = self.ledger.record_bet(user_id=user_id, bet=new_bet)

        pick_msg = messages.format_daily_pick_message(prediction, state)
        primary_sport = prediction.selections[0].sport if prediction.selections else "basketball"
        try:
            await status_msg.delete()
        except Exception:
            pass

        await reply_to.reply_text(
            f"🔄 *ALTERNATIVE NBA PICK GENERATED!*\n\n{pick_msg}",
            parse_mode="Markdown",
            reply_markup=get_pick_action_keyboard(
                bet_id,
                sport=primary_sport,
                booking_url=prediction.booking_url,
                booking_code=prediction.booking_code,
            ),
        )

    async def stats_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        if not self.is_user_allowed(user_id):
            return

        stats = self.ledger.get_user_performance_stats(user_id)
        msg = messages.format_stats_dashboard_message(stats, currency=config.DEFAULT_CURRENCY)
        await update.message.reply_text(msg, parse_mode="Markdown")

    async def nba_strategy_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        if not self.is_user_allowed(user_id):
            return

        msg = messages.format_nba_strategy_message()
        from telegram_bot.keyboards import get_nba_strategy_keyboard
        await update.message.reply_text(
            msg,
            parse_mode="Markdown",
            reply_markup=get_nba_strategy_keyboard(),
        )

    async def clear_all_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        if not self.is_user_allowed(user_id):
            return

        self.odds_api.clear_cache()
        self.ledger.clear_all_user_memories(user_id=user_id, initial_stake=config.DEFAULT_INITIAL_STAKE)
        msg = messages.format_memory_cleared_message()
        await update.message.reply_text(msg, parse_mode="Markdown")

    async def sport_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await self.nba_strategy_command(update, context)

    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        help_text = f"""ℹ️ *Available Commands & NBA Guide:*

• `/today` — Analyze today's top NBA pick (1-Leg Solo or 2-Leg Combo).
• `/reroll` — Reroll and generate a fresh alternative NBA pick.
• `/stats` — View performance dashboard, win rate %, net profit, and streaks.
• `/nba` — Review the active NBA Totals Strategy rules & parameters.
• `/placed` — Confirm you have placed the bet. Activates automated live monitoring!
• `/clear` — Discard the current active proposed prediction.
• `/clearall` — Completely wipe old memories, slip history, and reset to Day 1 fresh!
• `/helper` — Get SportyBet fast betslip guide and booking code details.
• `/balance` — View current bankroll, win streak, and next 50% cashout milestone.
• `/cycle` — Review the 30-Day compound projection chart.
• `/bets` — Inspect your recent bets ledger.
• `/reset` — Reset the challenge back to Day 1.

🤖 *Automated Settlement:* Once you tap **Bet Placed** (or `/placed`), the bot monitors the match live with **1st-half halftime grading** and **over-points early clearance alerts**!

💡 *Strict Rules:*
• Sport: Strictly NBA Basketball.
• Markets: Strictly Over/Under (incl. OT) & 1st Half Over/Under.
• Format: 1-Leg Solo (1.50 - 1.60 odds) or 2-Leg Combo (1.20 - 1.35 each, combined 1.50 - 1.80).
• Max Leg Odds: 1.60 per match.
"""
        await update.message.reply_text(help_text, parse_mode="Markdown")

    async def handle_text_buttons(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        text = update.message.text
        if text == "🎯 Today's Pick":
            await self.today_pick_command(update, context)
        elif text == "💰 My Balance":
            await self.balance_command(update, context)
        elif text == "📊 Win-Rate Stats":
            await self.stats_command(update, context)
        elif text in ("🏀 NBA Strategy", "⚙️ Sport Mode"):
            await self.nba_strategy_command(update, context)
        elif text == "📈 30-Day Cycle Plan":
            await self.cycle_command(update, context)
        elif text == "📜 Recent Bets":
            await self.recent_bets_command(update, context)
        elif text == "🔄 Reroll Alternative":
            await self.reroll_pick_command(update, context)
        elif text in ("🧹 Clear Memory", "🗑️ Clear Memory"):
            await self.clear_all_command(update, context)
        elif text == "❓ Help & Commands":
            await self.help_command(update, context)

    async def handle_callback_query(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()

        data = query.data
        user_id = update.effective_user.id

        if data.startswith("bet_placed_"):
            bet_id = int(data.replace("bet_placed_", ""))
            placed_bet = self.ledger.confirm_bet_placed(user_id=user_id, bet_id=bet_id)
            if placed_bet:
                primary_sport = "basketball"
                try:
                    await query.edit_message_reply_markup(
                        reply_markup=get_pick_action_keyboard(
                            bet_id,
                            sport=primary_sport,
                            booking_url=placed_bet.booking_url,
                            booking_code=placed_bet.booking_code,
                            is_placed=True,
                        )
                    )
                except Exception:
                    pass
                conf_msg = messages.format_bet_placed_confirmation(placed_bet, currency=config.DEFAULT_CURRENCY)
                await query.message.reply_text(conf_msg, parse_mode="Markdown")
            else:
                await query.answer("Bet not found or already processed.", show_alert=True)

        elif data.startswith("bet_clear_"):
            bet_id = int(data.replace("bet_clear_", ""))
            self.ledger.clear_bet(user_id=user_id, bet_id=bet_id)
            try:
                await query.edit_message_reply_markup(reply_markup=None)
            except Exception:
                pass
            conf_msg = messages.format_bet_cleared_confirmation()
            await query.message.reply_text(conf_msg, parse_mode="Markdown")

        elif data.startswith("reroll_pick_"):
            await self.reroll_pick_command(update, context, message_target=query.message)

        elif data.startswith("set_sport_"):
            sport = "basketball"
            self.ledger.set_user_sport_preference(user_id, sport)
            try:
                await query.edit_message_reply_markup(reply_markup=get_sport_selector_keyboard(sport))
            except Exception:
                pass
            await query.answer("NBA Basketball Engine Active!", show_alert=False)
            await query.message.reply_text(
                "✅ *Active Sport Engine: NBA Basketball*\n"
                "All daily tickets strictly use Over/Under points lines (incl. OT & 1st Half).\n"
                "Tap **🎯 Today's Pick** or type `/today` to scan!",
                parse_mode="Markdown",
            )

        elif data == "nba_locked_info":
            await query.answer("🏀 Engine is locked to NBA Basketball Over/Under totals (incl. OT & 1st Half)!", show_alert=True)

        elif data == "btn_today_pick":
            await self.today_pick_command(update, context)

        elif data == "view_stats":
            await self.stats_command(update, context)

        elif data in ("btn_clear_memory", "clear_all_memory"):
            await self.clear_all_command(update, context)

        elif data == "btn_cycle_plan":
            await self.cycle_command(update, context)

        elif data.startswith("bet_info_"):
            await query.answer("🔒 This bet is locked into active memory and being monitored live by the bot!", show_alert=True)

        elif data.startswith("outcome_won_"):
            bet_id = int(data.replace("outcome_won_", ""))
            outcome = self.ledger.log_bet_outcome(user_id=user_id, won=True, bet_id=bet_id)
            msg = messages.format_outcome_win_message(outcome, currency=config.DEFAULT_CURRENCY)
            await query.edit_message_reply_markup(reply_markup=None)
            await query.message.reply_text(msg, parse_mode="Markdown")

        elif data.startswith("outcome_lost_"):
            bet_id = int(data.replace("outcome_lost_", ""))
            recent_before = self.ledger.get_recent_bets(user_id=user_id, limit=5)
            target_bet = next((b for b in recent_before if b.id == bet_id), (recent_before[0] if recent_before else None))
            outcome = self.ledger.log_bet_outcome(user_id=user_id, won=False, bet_id=bet_id)
            msg = messages.format_outcome_loss_message(outcome, currency=config.DEFAULT_CURRENCY)
            await query.edit_message_reply_markup(reply_markup=None)
            await query.message.reply_text(msg, parse_mode="Markdown")

            if target_bet:
                try:
                    status_msg = await query.message.reply_text("🔬 *Conducting AI postmortem on the loss to extract learning rules...*", parse_mode="Markdown")
                    analysis = await analyze_loss(self.agent, target_bet.event_name, target_bet.selection, target_bet.odds)
                    await status_msg.edit_text(
                        f"🧠 *AI Postmortem Forensic Analysis:*\n\n{analysis}\n\n_Heuristic rule saved. Future pre-match filters will strictly avoid this trap._",
                        parse_mode="Markdown",
                    )
                except Exception as e:
                    logger.error(f"Postmortem callback error: {e}")

        elif data.startswith("get_helper_"):
            bet_id = int(data.replace("get_helper_", ""))
            recent = self.ledger.get_recent_bets(user_id=user_id, limit=5)
            target_bet = next((b for b in recent if b.id == bet_id), (recent[0] if recent else None))
            if target_bet:
                help_text = messages.format_sportybet_helper_message(target_bet, currency=config.DEFAULT_CURRENCY)
                await query.message.reply_text(help_text, parse_mode="Markdown")

        elif data == "view_balance":
            state = self.ledger.get_or_create_user(user_id)
            msg = messages.format_balance_message(state)
            await query.message.reply_text(msg, parse_mode="Markdown")


def create_bot_application(
    token: str,
    ledger: LedgerDB,
    agent: AgentRouterClient,
    odds_api: OddsApiClient,
    post_init: Optional[Callable] = None,
) -> Application:
    """Builds and wires up the Telegram Application."""
    bot = TelegramBetBot(ledger=ledger, agent=agent, odds_api=odds_api)
    builder = Application.builder().token(token)
    if post_init:
        builder.post_init(post_init)

    app = builder.build()

    # Commands
    app.add_handler(CommandHandler("start", bot.start_command))
    app.add_handler(CommandHandler("today", bot.today_pick_command))
    app.add_handler(CommandHandler("reroll", bot.reroll_pick_command))
    app.add_handler(CommandHandler("alternative", bot.reroll_pick_command))
    app.add_handler(CommandHandler("stats", bot.stats_command))
    app.add_handler(CommandHandler("winrate", bot.stats_command))
    app.add_handler(CommandHandler("nba", bot.nba_strategy_command))
    app.add_handler(CommandHandler("sport", bot.sport_command))
    app.add_handler(CommandHandler("placed", bot.placed_command))
    app.add_handler(CommandHandler("betplaced", bot.placed_command))
    app.add_handler(CommandHandler("clear", bot.clear_command))
    app.add_handler(CommandHandler("clearbet", bot.clear_command))
    app.add_handler(CommandHandler("clearall", bot.clear_all_command))
    app.add_handler(CommandHandler("clearmemory", bot.clear_all_command))
    app.add_handler(CommandHandler("balance", bot.balance_command))
    app.add_handler(CommandHandler("cycle", bot.cycle_command))
    app.add_handler(CommandHandler("bets", bot.recent_bets_command))
    app.add_handler(CommandHandler("win", bot.win_command))
    app.add_handler(CommandHandler("loss", bot.loss_command))
    app.add_handler(CommandHandler("reset", bot.reset_command))
    app.add_handler(CommandHandler("help", bot.help_command))
    app.add_handler(CommandHandler("helper", bot.helper_command))


    # Text Keyboard Buttons
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, bot.handle_text_buttons))

    # Inline Keyboards
    app.add_handler(CallbackQueryHandler(bot.handle_callback_query))

    async def global_error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
        logger.error(f"Telegram exception occurred: {context.error}", exc_info=context.error)
        if isinstance(update, Update) and update.effective_message:
            try:
                await update.effective_message.reply_text(
                    "⚡ *Network reconnecting.* Please tap again in a moment!",
                    parse_mode="Markdown"
                )
            except Exception:
                pass

    app.add_error_handler(global_error_handler)

    return app
