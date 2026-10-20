"""Formatted Telegram Messages and Notification Templates."""

from typing import List
from core.models import AIPrediction, LedgerState, BetRecord
from core.compound_math import calculate_compound_schedule
import config


def format_welcome_message(user_id: int, state: LedgerState) -> str:
    return f"""🔥 *Welcome to My Bet Bot!*
_Your 30-Day Compound Growth & Profit-Locking Agent_

🎯 *Strategy Blueprint:*
• Daily Target Odds: *~{config.TARGET_DAILY_ODDS}* (High probability selections)
• Strategy Duration: *30 Days*
• 🛑 *5-Day Profit Rule:* Every 5 days, withdraw *50%* of accumulated balance to your bank account!

📊 *Your Current Profile:*
• Day: *Day {state.current_day} of 30*
• Current Bankroll: *{state.current_balance:,.2f} {config.DEFAULT_CURRENCY}*
• Total Withdrawn So Far: *{state.total_withdrawn:,.2f} {config.DEFAULT_CURRENCY}*
• Active Win Streak: *{state.current_streak} 🔥*

Tap *🎯 Today's Pick* or type `/today` to scan and analyze today's optimal bet!
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

    selections_text = ""
    for idx, s in enumerate(prediction.selections, 1):
        sport_emoji = "🏀" if "basket" in s.sport.lower() else "⚽"
        selections_text += f"\n*{idx}. {sport_emoji} {s.fixture}*\n"
        selections_text += f"   • Market: `{s.market}`\n"
        selections_text += f"   • Selection: *{s.selection}*\n"
        selections_text += f"   • Odds: `{s.odds}` | Starts: _{s.commence_time or 'Today'}_\n"
        if s.early_payout_rule == "2-Up" or s.is_2up_eligible:
            selections_text += "   • ⚡ *SportyBet 2-Up Early Payout: ELIGIBLE* (Paid as WIN if 2 goals ahead)\n"
        elif s.early_payout_rule == "1-Up":
            selections_text += "   • ⚡ *1-Up Early Payout: ELIGIBLE* (Paid as WIN if 1 goal ahead)\n"
        elif s.early_payout_rule:
            selections_text += f"   • ⚡ *Early Lead Payout ({s.early_payout_rule}): ELIGIBLE*\n"

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

📌 *{prediction.title}*
{selections_text}
{booking_code_text}📊 *Bet Parameters:*
• Combined Odds: *{prediction.combined_odds:.2f}*
• Stake Allocated: *{prediction.suggested_stake:,.2f} {config.DEFAULT_CURRENCY}*
• Potential Payout: *{potential_return:,.2f} {config.DEFAULT_CURRENCY}* (+{profit:,.2f})
• Confidence Score: *{prediction.confidence_score}/10* ⭐ (Risk: `{prediction.risk_level}`)

🧠 *AI Multi-Source Analysis (Bet365 / Flashscore / WhoScored / Injury Scan):*
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


def format_outcome_win_message(outcome: dict, currency: str = "NGN") -> str:
    bonus_text = ""
    if outcome.get("bonus_included", 0) > 0:
        bonus_text = f"🎁 *Bonus / Acca Boost Added:* +{outcome['bonus_included']:,.2f} {currency}\n"

    base = f"""🎉 *BOOOM! BET WON!*

💰 *Profit Secured:* +{outcome['profit_loss']:,.2f} {currency}
🏦 *Gross Balance:* {outcome['gross_balance']:,.2f} {currency}
{bonus_text}🔥 *Streak:* {outcome['streak']} in a row!
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
    return f"""💔 *MATCH DID NOT HIT*

The pick did not land.
• Day PnL: *{outcome['profit_loss']:,.2f} {currency}*

💡 *What to do now:*
1. Don't panic or chase losses.
2. Check your locked profits from previous cycles.
3. You can reset to Day 1 with your starting stake using `/reset` whenever you are ready.
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
    sport_lower = str(getattr(target_bet, "sport", "") or "").lower()
    default_url = (
        "https://www.sportybet.com/ng/sport/basketball"
        if "basket" in sport_lower
        else "https://www.sportybet.com/ng/sport/football"
    )
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
