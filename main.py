"""Main Entry Point for My Bet Bot.

Supports two operational modes:
1. Live Telegram Bot Mode (when TELEGRAM_BOT_TOKEN is set in .env)
2. Interactive CLI Dry-Run / Test Mode (when testing without Telegram credentials)
"""

import sys
import asyncio
import logging
from telegram.ext import Application

# Ensure UTF-8 output on Windows consoles
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

from core.ledger import LedgerDB
from core.compound_math import calculate_compound_schedule
from intelligence.agent_router import AgentRouterClient
from data_sources.odds_api import OddsApiClient
from telegram_bot.bot import create_bot_application
from scheduler import setup_scheduler
import config

# Setup logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


async def run_cli_demo(ledger: LedgerDB, agent: AgentRouterClient, odds_api: OddsApiClient):
    """Interactive CLI test mode to demonstrate the complete workflow locally."""
    print("=" * 60)
    print("  [+] MY BET BOT — 30-DAY COMPOUND & 5-DAY WITHDRAWAL DEMO")
    print("=" * 60)

    demo_user_id = 12345
    state = ledger.get_or_create_user(demo_user_id, initial_stake=config.DEFAULT_INITIAL_STAKE)
    print(f"\n[1] User Profile Initialized:")
    print(f"    • Day: {state.current_day} of 30")
    print(f"    • Bankroll: {state.current_balance:,.2f} {config.DEFAULT_CURRENCY}")
    print(f"    • Total Withdrawn: {state.total_withdrawn:,.2f} {config.DEFAULT_CURRENCY}")

    print("\n[2] Ingesting upcoming fixtures & odds...")
    fixtures_summary = await odds_api.get_upcoming_fixtures_summary()
    print("    • Fixtures sample loaded.")

    print("\n[3] Running AI Multi-Factor Analysis via AgentRouter...")
    prediction = await agent.analyze_and_predict(
        fixtures_summary=fixtures_summary,
        current_day=state.current_day,
        current_balance=state.current_balance,
        currency=config.DEFAULT_CURRENCY,
    )

    print("\n" + "-" * 50)
    print(f"  AI PICK: {prediction.title}")
    for idx, s in enumerate(prediction.selections, 1):
        print(f"  Leg {idx}: {s.fixture} -> {s.market}: {s.selection} @ {s.odds}")
    print(f"  Combined Odds: {prediction.combined_odds:.2f}")
    print(f"  Confidence: {prediction.confidence_score}/10 (Risk: {prediction.risk_level})")
    print(f"  Allocated Stake: {prediction.suggested_stake:,.2f} {config.DEFAULT_CURRENCY}")
    potential_payout = round(prediction.suggested_stake * prediction.combined_odds, 2)
    print(f"  Potential Return: {potential_payout:,.2f} {config.DEFAULT_CURRENCY}")
    print("  Key Factors:")
    for f in prediction.key_factors:
        print(f"    * {f}")
    print("-" * 50)

    print("\n[4] Simulating Outcome: WON")
    outcome = ledger.log_bet_outcome(user_id=demo_user_id, won=True, actual_odds=prediction.combined_odds)
    print(f"    • Profit Secured: +{outcome['profit_loss']:,.2f} {config.DEFAULT_CURRENCY}")
    print(f"    • New Bankroll for Day {outcome['next_day']}: {outcome['new_balance']:,.2f} {config.DEFAULT_CURRENCY}")
    if outcome['is_withdrawal_day']:
        print(f"    • [!] 5-DAY WITHDRAWAL ALERT: Cash out {outcome['withdrawal_amount']:,.2f} {config.DEFAULT_CURRENCY}!")

    print("\n[5] Next 5 Days Projection Table:")
    schedule = calculate_compound_schedule(initial_stake=config.DEFAULT_INITIAL_STAKE, odds=config.TARGET_DAILY_ODDS)
    for p in schedule[:5]:
        status = "STOP: WITHDRAW 50%" if p.is_withdrawal_day else "Compound"
        print(f"    Day {p.day:02d}: Start: {p.start_balance:,.0f} | Win: {p.gross_win_balance:,.0f} | Action: {status}")

    print("\n" + "=" * 60)
    print("  Demo completed successfully! To run live on Telegram:")
    print("  1. Add your token to .env: TELEGRAM_BOT_TOKEN=your_token")
    print("  2. Re-run: python main.py")
    print("=" * 60)


import json
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler


class CloudHealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path in ["/", "/health", "/status", "/ping"]:
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            payload = {
                "status": "online",
                "service": "telegram-bet-bot",
                "timezone": config.TIMEZONE,
                "briefing_time": config.DAILY_BRIEFING_TIME,
                "port": config.PORT,
            }
            self.wfile.write(json.dumps(payload).encode("utf-8"))
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        pass


def start_health_server(port: int = config.PORT):
    """Runs a background HTTP server so cloud hosts (Render, Koyeb, etc.) verify service health."""
    try:
        server = HTTPServer(("0.0.0.0", port), CloudHealthCheckHandler)
        t = threading.Thread(target=server.serve_forever, daemon=True)
        t.start()
        logger.info(f"Cloud health-check server started on http://0.0.0.0:{port}/health")
    except Exception as e:
        logger.warning(f"Could not bind cloud health-check server to port {port}: {e}")


def main():
    ledger = LedgerDB()
    agent = AgentRouterClient()
    odds_api = OddsApiClient()

    token = config.TELEGRAM_BOT_TOKEN

    if "--test-cli" in sys.argv:
        logger.info("Running in CLI test mode (--test-cli)...")
        asyncio.run(run_cli_demo(ledger, agent, odds_api))
        return

    if not token or "your_" in token:
        logger.info("No TELEGRAM_BOT_TOKEN set in .env. Running in interactive CLI simulation mode...")
        asyncio.run(run_cli_demo(ledger, agent, odds_api))
        return

    # Start cloud web health-check server for Render/Koyeb
    start_health_server(port=config.PORT)

    logger.info("Starting Telegram Bot in long-polling mode...")

    async def post_init(application: Application):
        scheduler = setup_scheduler(app=application, ledger=ledger, agent=agent, odds_api=odds_api)
        scheduler.start()
        logger.info("Scheduler started successfully in event loop.")
        try:
            from telegram import BotCommand
            await application.bot.set_my_commands([
                BotCommand("today", "Today's top NBA pick (1-Leg Solo or 2-Leg Combo)"),
                BotCommand("reroll", "Generate alternative high-conviction NBA pick"),
                BotCommand("nba", "Review active NBA totals strategy & parameters"),
                BotCommand("placed", "Confirm bet placed & start auto-settlement"),
                BotCommand("stats", "Win rate %, streaks, and performance stats"),
                BotCommand("clearall", "Completely wipe old memories & reset to Day 1"),
                BotCommand("clear", "Discard current prediction from memory"),
                BotCommand("helper", "SportyBet fast betslip guide & booking code"),
                BotCommand("balance", "Check current bankroll & win streak"),
                BotCommand("cycle", "30-Day compound projection chart"),
                BotCommand("bets", "Recent bets ledger"),
                BotCommand("reset", "Reset challenge to Day 1"),
                BotCommand("help", "Available commands & guide"),
            ])
            logger.info("Telegram Bot menu commands updated successfully.")
        except Exception as ce:
            logger.warning(f"Could not register Telegram bot commands: {ce}")

    app = create_bot_application(
        token=token,
        ledger=ledger,
        agent=agent,
        odds_api=odds_api,
        post_init=post_init,
    )

    logger.info("Bot is active and listening for messages. Press Ctrl+C to terminate.")
    app.run_polling()


if __name__ == "__main__":
    main()
