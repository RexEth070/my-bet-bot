"""Formatted Telegram Messages and Notification Templates."""

from typing import List
from core.models import AIPrediction, LedgerState, BetRecord
from core.compound_math import calculate_compound_schedule
import config


def format_welcome_message(user_id: int, state: LedgerState) -> str:
    return f"""🏀 *Welcome to My Bet Bot (NBA Totals Edition)!* 🏆
_Your 30-Day Compound Growth & Profit-Locking Agent_

🎯 *NBA Strategy Blueprint:*
• Primary Focus: *NBA Basketball Exclusive* (games played every day through April — uninterrupted 30-day compounding!)
• Strictly Allowed Options:
   1. *Over/Under Total Points (incl. Overtime)* — Cushioned full-game totals with free overtime points protection!
   2. *First Half Over/Under* — Early-settling 1st half totals, completely insulated from 4th-quarter garbage time!
• Flexible High-Conviction Format:
   • *1-Leg Solo Pick:* When a single top-tier line has odds between *1.50 and 1.60* with a 99% win conviction rating (eliminating second-leg exposure!).
   • *2-Leg Combo Ticket:* When combining two cushioned lines (*1.20 - 1.35*) to safely reach *1.500 - 1.800* combined odds.
• Odds Ceiling Rule: *Max 1.60 per leg* (non of each odds per match should exceed 1.60)
• Strategy Duration: *30 Days*
• 🛑 *5-Day Profit Rule:* Every 5 days, withdraw *50%* of accumulated balance to your bank account!

📊 *Your Current Profile:*
• Day: *Day {state.current_day} of 30*
• Current Bankroll: *{state.current_balance:,.2f} {config.DEFAULT_CURRENCY}*
• Total Withdrawn So Far: *{state.total_withdrawn:,.2f} {config.DEFAULT_CURRENCY}*
• Active Win Streak: *{state.current_streak} 🔥*

Tap *🎯 Today's Pick* or type `/today` to scan today's optimal NBA Over/Under setup!
"""


def format_daily_pick_message(prediction: AIPrediction, state: LedgerState) -> str:
    if prediction.recommended_action == "SKIP":
        factors_text = "\n".join([f"• {f}" for f in prediction.key_factors])
        return f"""🛡️ *CAPITAL PRESERVATION BRIEFING — DAY {state.current_day} OF 30*
🛑 *ACTION: NO BET TODAY (PRESERVE CAPITAL)*

📌 *Reason:*
_{prediction.title}_

🧠 *AI Multi-Source Risk Audit:*
{factors_text}

💰 *Protected Bankroll:* *{state.current_balance:,.2f} {config.DEFAULT_CURRENCY}*
🎯 *Golden Rule:* In compounding, skipping high-variance days is what protects your 98%-99% success rate. The bot will automatically re-scan tomorrow morning at {config.DAILY_BRIEFING_TIME}!
"""

    is_withdrawal_day = (state.current_day % config.WITHDRAWAL_CYCLE_DAYS == 0)
    withdrawal_badge = "🚨 *WITHDRAWAL DAY TODAY! (50% Cashout after win)*" if is_withdrawal_day else "📈 *Compound Day*"
    ticket_type_badge = "🏀 *1-LEG SOLO PICK (MAXIMUM CONVICTION)*" if len(prediction.selections) == 1 else "🏀 *2-LEG HIGH-PROBABILITY COMBO*"

    selections_text = ""
    for idx, s in enumerate(prediction.selections, 1):
        selections_text += f"\n*{idx}. 🏀 {s.fixture}*\n"
        selections_text += f"   • Market: `{s.market}`\n"
        selections_text += f"   • Selection: *{s.selection}*\n"
        selections_text += f"   • Odds: `{s.odds:.2f}` | Starts: _{s.commence_time or 'Today'}_\n"

        # Calculate live analytics edge (H2H, L10, Players & Cushion)
        try:
            from data_sources.nba_intel import NBAIntelService
            nba_intel = NBAIntelService()
            edge = nba_intel.evaluate_line_edge(s.fixture, s.market, s.selection, s.odds)
            if edge.get("cushion_pts", 0) > 0:
                selections_text += f"   • 🛡️ *Safety Cushion:* `+{edge['cushion_pts']:.1f} Pts Buffer` (Win Conviction: *{edge['win_probability_pct']:.1f}%*)\n"
            if edge.get("pace_tier"):
                selections_text += f"   • ⚡ *Tempo & Pace:* `{edge['pace_tier']}` ({edge.get('projected_pace', 100.0)} poss/48m)\n"
            if edge.get("h2h_summary"):
                selections_text += f"   • 📊 *H2H Trend:* _{edge['h2h_summary']}_\n"
            if edge.get("home_l10_summary"):
                selections_text += f"   • 📈 *Home L10 Form:* _{edge['home_l10_summary']}_\n"
            if edge.get("away_l10_summary"):
                selections_text += f"   • 📈 *Away L10 Form:* _{edge['away_l10_summary']}_\n"
            if edge.get("player_spotlight"):
                selections_text += f"   • ⭐ *Key Players:* `{edge['player_spotlight']}`\n"
            if edge.get("star_notes"):
                selections_text += f"   • 🏥 *Injury Impact:* _{'; '.join(edge['star_notes'][:2])}_\n"
        except Exception:
            pass

        if s.why_picked_club:
            selections_text += f"   • 🏟️ *Why this team:* {s.why_picked_club}\n"
        if s.why_best_option:
            selections_text += f"   • 🎯 *Why best bet option:* {s.why_best_option}\n"
        if s.early_payout_rule == "15-Up":
            selections_text += "   • ⚡ *SportyBet 15-Up Early Payout: ELIGIBLE* (Paid as WIN if 15 points ahead)\n"

    factors_text = "\n".join([f"• {f}" for f in prediction.key_factors])

    potential_return = round(prediction.suggested_stake * prediction.combined_odds, 2)
    profit = round(potential_return - prediction.suggested_stake, 2)

    booking_code_text = ""
    if getattr(prediction, "booking_code", None):
        booking_code_text = f"""🎟 *SPORTYBET BOOKING CODE:*
`{prediction.booking_code}`  _(Tap to copy)_
🔗 [1-Click Load Bet Slip]({prediction.booking_url})

"""

    return f"""🏆 *DAILY BETTING BRIEFING — DAY {state.current_day} OF 30*
{withdrawal_badge}
{ticket_type_badge}

📌 *{prediction.title}*
{selections_text}
{booking_code_text}📊 *Bet Parameters:*
• Combined Odds: *{prediction.combined_odds:.2f}*
• Stake Allocated: *{prediction.suggested_stake:,.2f} {config.DEFAULT_CURRENCY}*
• Potential Payout: *{potential_return:,.2f} {config.DEFAULT_CURRENCY}* (+{profit:,.2f})
• Confidence Score: *{prediction.confidence_score}/10* ⭐ (Risk: `{prediction.risk_level}`)

🧠 *AI Basketball Analytics (Rest / Net Rating / Sharp Line / Injury Scan):*
{factors_text}

⚡ _Click below to load your SportyBet slip, enter {prediction.suggested_stake:,.0f} {config.DEFAULT_CURRENCY}, and place bet!_
"""


def format_balance_message(state: LedgerState) -> str:
    next_withdrawal_day = ((state.current_day - 1) // config.WITHDRAWAL_CYCLE_DAYS + 1) * config.WITHDRAWAL_CYCLE_DAYS
    days_left_to_cashout = next_withdrawal_day - state.current_day

    return f"""💰 *TREASURY & LEDGER STATUS*

📅 *Progress:*
• Current Cycle: *Day {state.current_day} of 30*
• Next 50% Cashout: *Day {next_withdrawal_day}* ({days_left_to_cashout} days away)

💵 *Financial Summary:*
• Available Bankroll: *{state.current_balance:,.2f} {config.DEFAULT_CURRENCY}*
• Initial Stake: *{state.initial_stake:,.2f} {config.DEFAULT_CURRENCY}*
• 🔒 *Total Locked Profits Withdrawn:* *{state.total_withdrawn:,.2f} {config.DEFAULT_CURRENCY}*
• Net Total Value (Bankroll + Withdrawn): *{(state.current_balance + state.total_withdrawn):,.2f} {config.DEFAULT_CURRENCY}*

🏆 *Performance Record:*
• Wins: *{state.total_won_bets}* | Losses: *{state.total_lost_bets}*
• Current Win Streak: *{state.current_streak} 🔥*
• Best Win Streak: *{state.highest_streak} ⭐️*
• Account Status: `{state.status}`
"""


def format_bet_placed_confirmation(bet: BetRecord, currency: str = "NGN") -> str:
    code_text = f"• Booking Code: `{bet.booking_code}`\n" if bet.booking_code else ""
    return f"""✅ *BET PLACED & TRACKED!* 🎯
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
The bot has locked this bet into active memory:

🏆 *Match:* `{bet.event_name}`
🎯 *Selection:* `{bet.selection}`
📊 *Odds:* `{bet.odds:.2f}`
💵 *Stake:* `{bet.stake:,.2f} {currency}`
💰 *Potential Return:* `{bet.potential_return:,.2f} {currency}`
{code_text}
📡 *Live Automated Monitoring Active:*
The bot is now monitoring the scoreboards. Once the match finishes, it will automatically update you with a **congratulations on win** or **loss report**, and automatically compound your bankroll! 🚀
"""


def format_bet_cleared_confirmation() -> str:
    return """🗑️ *PREDICTION CLEARED!*
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
This prediction has been cleared from bot memory and will not be tracked.

💡 Tap *🎯 Today's Pick* or type `/today` anytime to analyze another game setup!
"""


def format_outcome_win_message(outcome: dict, currency: str = "NGN") -> str:
    bonus_text = ""
    if outcome.get("bonus_included", 0) > 0:
        bonus_text = f"🎁 *Bonus / Acca Boost Added:* +{outcome['bonus_included']:,.2f} {currency}\n"

    base = f"""🎉 *CONGRATULATIONS! BET WON!* 🏆
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Your placed bet has landed successfully!

💰 *Profit Secured:* +{outcome['profit_loss']:,.2f} {currency}
🏦 *Gross Balance:* {outcome['gross_balance']:,.2f} {currency}
{bonus_text}🔥 *Winning Streak:* {outcome['streak']} in a row!
"""

    if outcome.get("is_withdrawal_day") and outcome.get("withdrawal_amount", 0) > 0:
        base += f"""
🚨 *MILESTONE REACHED — 5-DAY WITHDRAWAL ALERT!* 🚨
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🛑 *ACTION REQUIRED:*
Withdraw *50% of your gross balance* right now to lock in profits!

• Cashout Amount to Withdraw: *{outcome['withdrawal_amount']:,.2f} {currency}*
• Leftover Active Bankroll: *{outcome['new_balance']:,.2f} {currency}*
• Total Withdrawn to Date: *{outcome['total_withdrawn_overall']:,.2f} {currency}*

_Your new active stake for Day {outcome['next_day']} will be {outcome['new_balance']:,.2f} {currency}._
"""
    else:
        base += f"""
👉 *Next Up:* Day {outcome['next_day']} of 30
📈 *New Compounding Bankroll:* {outcome['new_balance']:,.2f} {currency}
"""
    return base


def format_outcome_loss_message(outcome: dict, currency: str = "NGN") -> str:
    return f"""💔 *BET LOST — Match Concluded*
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
The placed pick did not land.
• Day PnL: *{outcome['profit_loss']:,.2f} {currency}*
• Active Bankroll: *{outcome['new_balance']:,.2f} {currency}*

💡 *Capital Preservation Rule:*
1. Don't panic or chase losses. Your accumulated profits from previous cycles remain protected.
2. You can restart Day 1 anytime with your initial stake using `/reset` or tap *🎯 Today's Pick* when you're ready for the next setup.
"""


def format_cycle_plan_message(initial_stake: float = 500.0, currency: str = "NGN") -> str:
    schedule = calculate_compound_schedule(initial_stake=initial_stake, odds=config.TARGET_DAILY_ODDS)
    
    rows = []
    rows.append("🗓 *30-DAY COMPOUND & 5-DAY WITHDRAWAL TARGETS*\n")
    rows.append(f"_Starting Stake: {initial_stake:,.0f} {currency} @ ~{config.TARGET_DAILY_ODDS} Odds_\n")

    for p in schedule:
        if p.is_withdrawal_day or p.day in [1, 2, 3, 4]:
            if p.is_withdrawal_day:
                rows.append(f"📍 *Day {p.day:02d}:* Reach *{p.gross_win_balance:,.0f}* ➔ 🛑 *Withdraw {p.withdrawal_amount:,.0f}* | Leftover: *{p.end_balance:,.0f}*")
            else:
                rows.append(f"• Day {p.day:02d}: {p.start_balance:,.0f} ➔ *{p.gross_win_balance:,.0f}*")

    rows.append("\n💡 _By Day 5, you recover nearly 3.8x your starting capital! All future compounding is playing with pure profit._")
    return "\n".join(rows)


def format_recent_bets_message(bets: List[BetRecord], currency: str = "NGN") -> str:
    if not bets:
        return "📜 *No bets recorded yet.* Tap `/today` to get your first pick!"

    lines = ["📜 *RECENT BETS LEDGER:*\n"]
    for b in bets:
        icon = "⏳" if b.outcome == "PENDING" else ("✅" if b.outcome == "WON" else "❌")
        lines.append(f"{icon} *Day {b.day_number}: {b.event_name}*")
        lines.append(f"   • Pick: `{b.selection}` @ `{b.odds}`")
        lines.append(f"   • Stake: `{b.stake:,.2f} {currency}` | PnL: `{b.profit_loss:+,.2f} {currency}`\n")

    return "\n".join(lines)


def format_sportybet_helper_message(target_bet, currency: str = "NGN") -> str:
    potential_return = round(target_bet.stake * target_bet.odds, 2)
    default_url = "https://www.sportybet.com/ng/sport/basketball"
    sporty_url = getattr(target_bet, "booking_url", None) or default_url
    first_team = target_bet.event_name.split(" vs ")[0] if " vs " in target_bet.event_name else target_bet.event_name

    code_block = ""
    if getattr(target_bet, "booking_code", None):
        code_block = f"""🎟 *SPORTYBET BOOKING CODE:*
`{target_bet.booking_code}`  _(Tap code to copy)_
🔗 [1-Click Auto-Load Slip]({sporty_url})

"""

    instruction = (
        f"1. Tap [1-Click Auto-Load Slip]({sporty_url}) or open SportyBet app and enter code `{target_bet.booking_code}` into **Load Bet Slip**."
        if getattr(target_bet, "booking_code", None)
        else f"1. Tap [Open SportyBet]({sporty_url}) and search `{first_team}` in the search bar."
    )

    return f"""⚡ *SPORTYBET FAST BETSLIP GUIDE*

{code_block}🏆 *Match / Fixture:* `{target_bet.event_name}`
🎯 *Market:* `{target_bet.market}`
📊 *Selection:* `{target_bet.selection}`
📈 *Odds:* `{target_bet.odds:.2f}` (Leg: 1.200 - 1.590 | Ticket: 1.500 - 1.800)
💵 *Stake to Input:* `{target_bet.stake:,.2f} {currency}`
💰 *Potential Return:* `{potential_return:,.2f} {currency}`

📱 *How to place on SportyBet Nigeria:*
{instruction}
2. Enter `{target_bet.stake:,.2f} {currency}` in the stake box.
3. Tap **Place Bet**!
"""


def format_stats_dashboard_message(stats: dict, currency: str = "NGN") -> str:
    """Formats performance and win-rate statistics dashboard."""
    if not stats:
        return "📊 *No performance history yet.* Place and settle your first bet to populate stats!"

    win_rate = stats.get("win_rate", 0.0)
    rate_badge = "🔥 ELITE" if win_rate >= 90 else ("✅ SOLID" if win_rate >= 75 else "📈 BUILDING")

    return f"""📊 *PERFORMANCE & WIN-RATE DASHBOARD*
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🎯 *Overall Win Rate:* *{win_rate:.1f}%* `[{rate_badge}]`
🏆 *Bets Settled:* *{stats.get('total_settled', 0)}* (Won: *{stats.get('total_won', 0)}* | Lost: *{stats.get('total_lost', 0)}*)
🔥 *Active Win Streak:* *{stats.get('current_streak', 0)} in a row* (Best: *{stats.get('highest_streak', 0)}*)

💰 *Financial Growth:*
• Initial Stake: `{stats.get('initial_stake', 500.0):,.2f} {currency}`
• Current Bankroll: *{stats.get('current_balance', 500.0):,.2f} {currency}*
• Net Profit Earned: *{stats.get('net_profit', 0.0):+,.2f} {currency}*
• Return on Investment (ROI): *{stats.get('roi', 0.0):+.1f}%*
• Total 5-Day Withdrawn: *{stats.get('total_withdrawn', 0.0):,.2f} {currency}*

⚙️ *Active Engine Configuration:*
• Sport Focus: *🏀 NBA Basketball Exclusive*
• Ticket Format: *1-Leg Solo (1.50 - 1.60) or 2-Leg Combo*
• Odds Ceiling: *Max 1.60 per match* (strictly 1.200 - 1.600)
• Target Daily Odds: *~{stats.get('avg_odds', 1.55):.2f}* (1.500 - 1.800)
• Early Settlement: *Halftime Settlement (1st Half) & Over Points Clearance*

💡 _Tap **🏀 NBA Strategy** or type `/nba` to review active engine rules._
"""


def format_nba_strategy_message() -> str:
    """Formats the active NBA Strategy briefing."""
    return f"""🏀 *ACTIVE NBA TOTALS STRATEGY BRIEFING*
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
The bot is strictly locked to **NBA Basketball** — running daily through April!

🎯 *Allowed Options / Markets (Only 2):*
1. *Over/Under Total Points (incl. Overtime)* — Alternate game totals with full overtime points security.
2. *First Half Over/Under* — Early-settling 1st half totals, completely bypassing 4th-quarter garbage time.

⚡ *High-Conviction Ticket Structure:*
• *1-Leg Solo Pick:* When a single alternate line has odds between *1.50 and 1.60* and a 99% win-rate rating (eliminates second-leg exposure completely!).
• *2-Leg Combo Ticket:* When combining two heavily cushioned lines (*1.20 - 1.35*) to achieve *1.500 - 1.800* combined odds.
• *Odds Cap:* Non of each odds per match should exceed **1.60** (strictly 1.200 - 1.600 per leg).

🔬 *Advanced NBA Intelligence Engines (Active in Production):*
• 🏥 *Star Absence Impact Tracker:* Scans live ESPN injury wire. If a 20+ PPG star (Giannis, Luka, Jokić, Tatum) is Out, automatically shades projected output down (-7 to -10 pts) and targets Alternate Under / 1st Half Under! If a rim anchor is Out, targets Alternate Over cushions.
• ⚡ *Pace & Defensive Efficiency Engine:* Cross-analyzes possessions per 48m and offensive/defensive ratings across all 30 NBA teams to verify a minimum *+10 to +16 point safety cushion* before approving any line.
• 🎟️ *1-Click SportyBet Fast-Booking:* Instant direct booking codes loaded onto your slip with one tap!

🏎️ *Rapid Early Auto-Settlement:*
• *1st Half Over/Under* automatically grades at halftime as soon as Q2 finishes.
• *Over Total Points* automatically settles as WON mid-game as soon as cumulative points exceed the line threshold!

Tap *🎯 Today's Pick* or type `/today` to scan!
"""


format_sport_selector_message = lambda current_sport="basketball": format_nba_strategy_message()


def format_memory_cleared_message() -> str:
    """Confirmation message after clearing old memories and history."""
    return f"""🧹 *BOT MEMORY & HISTORY CLEARED SUCCESSFULLY!*
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
✅ **What was wiped:**
• All previous bets and slip history purged from local ledger.
• Upcoming fixtures memory cache cleared.
• Account progress reset back to **Day 1 of 30** with initial bankroll ({config.DEFAULT_INITIAL_STAKE:,.2f} {config.DEFAULT_CURRENCY}).

🏀 **Active Engine Status:**
• Sport: *Strictly NBA Basketball* (no football / soccer).
• Markets: *Over/Under (incl. OT)* & *First Half Over/Under*.
• Format: *1-Leg Solo (1.50 - 1.60 odds)* or *2-Leg Combo*.
• Max Leg Odds: *1.60 per match*.

Tap *🎯 Today's Pick* or type `/today` to generate your fresh Day 1 pick!
"""

