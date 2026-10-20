"""Compounding and Profit-Locking Withdrawal Mathematical Engine.

Implements the 30-Day Compound Growth Model:
- Daily target odds: ~1.50
- 5-Day cycle profit withdrawal: 50% of the accumulated balance is withdrawn on Days 5, 10, 15, 20, 25, 30.
- Remaining 50% forms the new starting stake for the next cycle.
"""

from typing import List, Dict, Any, Optional
from dataclasses import dataclass


@dataclass
class DayProjection:
    day: int
    start_balance: float
    target_odds: float
    gross_win_balance: float
    is_withdrawal_day: bool
    withdrawal_amount: float
    end_balance: float
    cumulative_withdrawn: float


def calculate_compound_schedule(
    initial_stake: float = 1000.0,
    odds: float = 1.50,
    total_days: int = 30,
    cycle_days: int = 5,
    withdrawal_pct: float = 0.50,
) -> List[DayProjection]:
    """Generates the full projection schedule for the 30-day challenge."""
    schedule: List[DayProjection] = []
    current_balance = float(initial_stake)
    cumulative_withdrawn = 0.0

    for day in range(1, total_days + 1):
        start_bal = current_balance
        gross_win = round(start_bal * odds, 2)
        is_withdrawal = (day % cycle_days == 0)

        if is_withdrawal:
            withdrawal = round(gross_win * withdrawal_pct, 2)
            end_bal = round(gross_win - withdrawal, 2)
            cumulative_withdrawn = round(cumulative_withdrawn + withdrawal, 2)
        else:
            withdrawal = 0.0
            end_bal = gross_win

        projection = DayProjection(
            day=day,
            start_balance=start_bal,
            target_odds=odds,
            gross_win_balance=gross_win,
            is_withdrawal_day=is_withdrawal,
            withdrawal_amount=withdrawal,
            end_balance=end_bal,
            cumulative_withdrawn=cumulative_withdrawn,
        )
        schedule.append(projection)
        current_balance = end_bal

    return schedule


def calculate_next_day_state(
    current_day: int,
    current_balance: float,
    won: bool,
    actual_odds: float = 1.50,
    cycle_days: int = 5,
    withdrawal_pct: float = 0.50,
    actual_payout: Optional[float] = None,
) -> Dict[str, Any]:
    """Computes the transition state after a bet result is logged.

    Args:
        current_day: The day index before the bet.
        current_balance: Active stake on the bet.
        won: Whether the bet won.
        actual_odds: The odds multiplier if actual_payout is not specified.
        cycle_days: How many days per withdrawal cycle (default 5).
        withdrawal_pct: Percentage to withdraw on milestone days (default 50%).
        actual_payout: Optional exact payout returned from the bookmaker (including bonuses/boosts).

    Returns:
        dict containing transition details.
    """
    if not won:
        return {
            "next_day": current_day,  # remains on current day or resets according to user rules
            "won": False,
            "gross_balance": 0.0,
            "is_withdrawal_day": False,
            "withdrawal_amount": 0.0,
            "new_balance": 0.0,
            "profit_loss": -round(current_balance, 2),
            "bonus_included": 0.0,
        }

    if actual_payout is not None and actual_payout > 0:
        gross = round(float(actual_payout), 2)
        expected_standard = round(current_balance * actual_odds, 2)
        bonus_included = max(0.0, round(gross - expected_standard, 2))
    else:
        gross = round(current_balance * actual_odds, 2)
        bonus_included = 0.0

    profit = round(gross - current_balance, 2)
    is_withdrawal = (current_day % cycle_days == 0)

    if is_withdrawal:
        withdrawal = round(gross * withdrawal_pct, 2)
        new_balance = round(gross - withdrawal, 2)
    else:
        withdrawal = 0.0
        new_balance = gross

    return {
        "next_day": current_day + 1,
        "won": True,
        "gross_balance": gross,
        "is_withdrawal_day": is_withdrawal,
        "withdrawal_amount": withdrawal,
        "new_balance": new_balance,
        "profit_loss": profit,
        "bonus_included": bonus_included,
    }

