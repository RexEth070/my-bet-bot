# 🏆 My Bet Bot

An intelligent, quantitative sports betting advisor and automated bankroll manager running on **Telegram**.

## 📌 Strategy Core: 30-Day Compound Growth Model
- **Daily Target Odds:** `~1.50` (Low-variance selections like Double Chance, Over 1.5 Goals).
- **The 5-Day Safety Rule:** On Days 5, 10, 15, 20, 25, and 30, **withdraw 50% of the accumulated balance** to secure capital and lock in profits.
- **AI Multi-Factor Reasoning:** Analyzes team form, home/away splits, tactical match-ups, xG, rest fatigue, and injury reports via **AgentRouter / OpenRouter**.
- **Analyst Mode (Phase 1):** The bot pushes daily picks with rationales to Telegram, allowing 1-click execution on Stake to avoid Cloudflare/2FA account flags.

---

## 🚀 Quick Start

### 1. Configure Secrets
Copy [.env.example](file:///c:/Users/samre/OneDrive/Documents/my%20bet%20bot/.env.example) to `.env`:
```bash
cp .env.example .env
```

Edit `.env` with your credentials:
```env
# Telegram Bot Token from @BotFather
TELEGRAM_BOT_TOKEN=your_token_here

# Your Telegram user ID (optional, restricts bot to you)
TELEGRAM_ALLOWED_USER_ID=your_id

# AgentRouter / OpenRouter key for AI analysis
AGENTROUTER_API_KEY=your_key
AGENTROUTER_BASE_URL=https://openrouter.ai/api/v1
AI_MODEL=anthropic/claude-3.5-sonnet

# The Odds API key (optional for live odds, has sample fallback)
ODDS_API_KEY=your_odds_api_key
```

### 2. Run the Bot
```bash
python main.py
```
*If no Telegram token is set, it automatically runs in an interactive CLI simulation demo.*

### 3. Run Unit Tests
```bash
python -m pytest tests/
```

---

## 📱 Telegram Commands

| Command | Action |
|---|---|
| `/start` | Welcome screen & profile setup |
| `/today` | Fetch & analyze today's ~1.50 pick |
| `/balance` | View bankroll, day in cycle, and locked profits |
| `/cycle` | View the 30-Day projection and 5-Day withdrawal targets |
| `/bets` | View recent betting history |
| `/win` | Mark the current bet as WON and advance compounding |
| `/loss` | Log match loss |
| `/reset` | Reset challenge to Day 1 |
