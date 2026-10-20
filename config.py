"""Configuration and Environment Variables for My Bet Bot."""

import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env file
BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

# Telegram Bot
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_ALLOWED_USER_ID = os.getenv("TELEGRAM_ALLOWED_USER_ID", "")

# AI Inference (AgentRouter / OpenRouter)
AGENTROUTER_API_KEY = os.getenv("AGENTROUTER_API_KEY", "")
AGENTROUTER_BASE_URL = os.getenv("AGENTROUTER_BASE_URL", "https://openrouter.ai/api/v1")
AI_MODEL = os.getenv("AI_MODEL", "anthropic/claude-3.5-sonnet")

# Sports Data API
ODDS_API_KEY = os.getenv("ODDS_API_KEY", "")
ODDS_API_REGIONS = os.getenv("ODDS_API_REGIONS", "eu,uk")
SPORTYBET_BASE_URL = os.getenv("SPORTYBET_BASE_URL", "https://www.sportybet.com/ng").rstrip("/")
STAKE_BASE_URL = os.getenv("STAKE_BASE_URL", "https://stake.com").rstrip("/")

# Financial & Strategy Defaults
DEFAULT_INITIAL_STAKE = float(os.getenv("DEFAULT_INITIAL_STAKE", "500.0"))
DEFAULT_CURRENCY = os.getenv("DEFAULT_CURRENCY", "NGN")
TARGET_DAILY_ODDS = float(os.getenv("TARGET_DAILY_ODDS", "1.55"))
MIN_LEG_ODDS = float(os.getenv("MIN_LEG_ODDS", "1.200"))
MAX_LEG_ODDS = float(os.getenv("MAX_LEG_ODDS", "1.590"))
MIN_COMBINED_ODDS = float(os.getenv("MIN_COMBINED_ODDS", "1.500"))
MAX_COMBINED_ODDS = float(os.getenv("MAX_COMBINED_ODDS", "1.800"))
WITHDRAWAL_CYCLE_DAYS = int(os.getenv("WITHDRAWAL_CYCLE_DAYS", "5"))
WITHDRAWAL_PERCENTAGE = float(os.getenv("WITHDRAWAL_PERCENTAGE", "0.50"))
TOTAL_CHALLENGE_DAYS = 30

# Database & Server Port
DB_PATH = Path(os.getenv("DB_PATH", str(BASE_DIR / "ledger.db")))
PORT = int(os.getenv("PORT", "8080"))

# Schedule
DAILY_BRIEFING_TIME = os.getenv("DAILY_BRIEFING_TIME", "10:30")
TIMEZONE = os.getenv("TIMEZONE", "Africa/Lagos")
