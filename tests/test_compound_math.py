"""Unit tests for compound mathematics and SQLite ledger engine using standard unittest."""

import unittest
import tempfile
from pathlib import Path
from core.compound_math import calculate_compound_schedule, calculate_next_day_state
from core.ledger import LedgerDB
from core.models import BetRecord


class TestCompoundMathAndLedger(unittest.TestCase):
    def test_30_day_compound_schedule(self):
        schedule = calculate_compound_schedule(
            initial_stake=1000.0,
            odds=1.50,
            total_days=30,
            cycle_days=5,
            withdrawal_pct=0.50,
        )

        self.assertEqual(len(schedule), 30)

        # Day 1
        self.assertEqual(schedule[0].day, 1)
        self.assertEqual(schedule[0].start_balance, 1000.0)
        self.assertEqual(schedule[0].gross_win_balance, 1500.0)
        self.assertFalse(schedule[0].is_withdrawal_day)
        self.assertEqual(schedule[0].withdrawal_amount, 0.0)
        self.assertEqual(schedule[0].end_balance, 1500.0)

        # Day 5 (Withdrawal Day)
        day5 = schedule[4]
        self.assertEqual(day5.day, 5)
        self.assertTrue(day5.is_withdrawal_day)
        self.assertEqual(day5.gross_win_balance, 7593.75)
        self.assertEqual(day5.withdrawal_amount, 3796.88)
        self.assertIn(day5.end_balance, [3796.87, 3796.88])
        self.assertEqual(day5.cumulative_withdrawn, 3796.88)

        # Day 6 starts with Day 5's end_balance
        day6 = schedule[5]
        self.assertEqual(day6.day, 6)
        self.assertEqual(day6.start_balance, day5.end_balance)

        # By Day 10
        day10 = schedule[9]
        self.assertEqual(day10.day, 10)
        self.assertTrue(day10.is_withdrawal_day)
        self.assertGreater(day10.cumulative_withdrawn, 18000.0)

    def test_next_day_state_won_and_lost(self):
        # Regular win
        win_state = calculate_next_day_state(current_day=2, current_balance=1500.0, won=True, actual_odds=1.50)
        self.assertEqual(win_state["next_day"], 3)
        self.assertTrue(win_state["won"])
        self.assertEqual(win_state["gross_balance"], 2250.0)
        self.assertFalse(win_state["is_withdrawal_day"])
        self.assertEqual(win_state["withdrawal_amount"], 0.0)
        self.assertEqual(win_state["new_balance"], 2250.0)

        # Day 5 withdrawal win
        d5_win = calculate_next_day_state(current_day=5, current_balance=5062.50, won=True, actual_odds=1.50)
        self.assertEqual(d5_win["next_day"], 6)
        self.assertTrue(d5_win["is_withdrawal_day"])
        self.assertEqual(d5_win["withdrawal_amount"], 3796.88)

        # Win with bonus / exact payout
        bonus_win = calculate_next_day_state(
            current_day=1,
            current_balance=1000.0,
            won=True,
            actual_odds=1.50,
            actual_payout=1620.0,  # 1500 standard + 120 bonus
        )
        self.assertEqual(bonus_win["next_day"], 2)
        self.assertEqual(bonus_win["gross_balance"], 1620.0)
        self.assertEqual(bonus_win["new_balance"], 1620.0)
        self.assertEqual(bonus_win["profit_loss"], 620.0)
        self.assertEqual(bonus_win["bonus_included"], 120.0)

        # Loss
        loss_state = calculate_next_day_state(current_day=3, current_balance=2250.0, won=False)
        self.assertFalse(loss_state["won"])
        self.assertEqual(loss_state["new_balance"], 0.0)

    def test_sqlite_ledger(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            test_db = Path(tmp_dir) / "test_ledger.db"
            ledger = LedgerDB(db_path=test_db)

            user_id = 99999
            user = ledger.get_or_create_user(user_id=user_id, initial_stake=1000.0)
            self.assertEqual(user.current_day, 1)
            self.assertEqual(user.current_balance, 1000.0)
            self.assertEqual(user.total_withdrawn, 0.0)

            # Record a pending bet
            bet = BetRecord(
                day_number=1,
                event_name="Arsenal vs Chelsea",
                market="Double Chance",
                selection="Arsenal or Draw",
                odds=1.50,
                stake=1000.0,
                potential_return=1500.0,
            )
            bet_id = ledger.record_bet(user_id=user_id, bet=bet)
            self.assertIsNotNone(bet_id)

            # Log win
            outcome = ledger.log_bet_outcome(user_id=user_id, won=True, bet_id=bet_id, actual_odds=1.50)
            self.assertTrue(outcome["won"])
            self.assertEqual(outcome["next_day"], 2)
            self.assertEqual(outcome["new_balance"], 1500.0)

            # Check updated user
            updated_user = ledger.get_or_create_user(user_id=user_id)
            self.assertEqual(updated_user.current_day, 2)
            self.assertEqual(updated_user.current_balance, 1500.0)
            self.assertEqual(updated_user.current_streak, 1)
            self.assertEqual(updated_user.total_won_bets, 1)

            recent = ledger.get_recent_bets(user_id=user_id)
            self.assertEqual(len(recent), 1)
            self.assertEqual(recent[0].outcome, "WON")

    def test_odds_boundaries_enforcement(self):
        from core.models import AIPrediction

        # Test 1: Valid pick (leg: 1.25, 1.28 -> combined: 1.60)
        valid_data = {
            "title": "Arsenal Double Chance + Real Madrid DNB",
            "selections": [
                {"fixture": "Arsenal vs Chelsea", "market": "Double Chance", "selection": "1X", "odds": 1.25},
                {"fixture": "Real Madrid vs Sevilla", "market": "Draw No Bet", "selection": "Real Madrid DNB", "odds": 1.28},
            ],
            "combined_odds": 1.60,
            "confidence_score": 9,
            "recommended_action": "BET"
        }
        pred = AIPrediction.from_dict_flexible(valid_data, current_balance=500.0)
        self.assertEqual(pred.recommended_action, "BET")
        self.assertEqual(pred.combined_odds, 1.60)
        self.assertEqual(pred.suggested_stake, 500.0)

        # Test 2: Leg below 1.200 (e.g. 1.15) -> Must SKIP
        low_leg_data = {
            "title": "Manchester City Win",
            "selections": [
                {"fixture": "Man City vs Luton", "market": "Match Winner", "selection": "Man City", "odds": 1.15},
                {"fixture": "Bayern vs Bochum", "market": "Match Winner", "selection": "Bayern", "odds": 1.35},
            ],
            "combined_odds": 1.55,
            "recommended_action": "BET"
        }
        pred_low = AIPrediction.from_dict_flexible(low_leg_data, current_balance=500.0)
        self.assertEqual(pred_low.recommended_action, "SKIP")
        self.assertIn("below 1.200", pred_low.title)

        # Test 3: Leg above 1.600 (e.g. 1.65) -> Must SKIP
        high_leg_data = {
            "title": "Inter Milan Win",
            "selections": [
                {"fixture": "Inter vs Juventus", "market": "Match Winner", "selection": "Inter", "odds": 1.65},
            ],
            "combined_odds": 1.65,
            "recommended_action": "BET"
        }
        pred_high = AIPrediction.from_dict_flexible(high_leg_data, current_balance=500.0)
        self.assertEqual(pred_high.recommended_action, "SKIP")
        self.assertIn("exceeds 1.600", pred_high.title)

        # Test 4: Combined odds below 1.500 (e.g. 1.45) -> Must SKIP
        low_combined_data = {
            "title": "Safe Double Chance",
            "selections": [
                {"fixture": "PSG vs Rennes", "market": "Double Chance", "selection": "1X", "odds": 1.20},
                {"fixture": "Barca vs Getafe", "market": "Double Chance", "selection": "1X", "odds": 1.21},
            ],
            "combined_odds": 1.45,
            "recommended_action": "BET"
        }
        pred_low_comb = AIPrediction.from_dict_flexible(low_combined_data, current_balance=500.0)
        self.assertEqual(pred_low_comb.recommended_action, "SKIP")
        self.assertIn("below 1.500", pred_low_comb.title)

        # Test 5: Combined odds above 1.99 (e.g. 2.05) -> Must SKIP
        high_combined_data = {
            "title": "Risky Double",
            "selections": [
                {"fixture": "Liverpool vs Everton", "market": "Draw No Bet", "selection": "Liverpool", "odds": 1.45},
                {"fixture": "Milan vs Roma", "market": "Over 1.5 Goals", "selection": "Over 1.5", "odds": 1.42},
            ],
            "combined_odds": 2.06,
            "recommended_action": "BET"
        }
        pred_high_comb = AIPrediction.from_dict_flexible(high_combined_data, current_balance=500.0)
        self.assertEqual(pred_high_comb.recommended_action, "SKIP")
        self.assertIn("exceeds 2.00 ceiling", pred_high_comb.title)

        # Combined odds at 1.89 (under 1.99 ceiling) -> Valid BET
        valid_combo_data = {
            "title": "Sweet Spot Double",
            "selections": [
                {"fixture": "Liverpool vs Everton", "market": "Draw No Bet", "selection": "Liverpool", "odds": 1.38},
                {"fixture": "Milan vs Roma", "market": "Over 1.5 Goals", "selection": "Over 1.5", "odds": 1.37},
            ],
            "combined_odds": 1.89,
            "recommended_action": "BET"
        }
        pred_valid_comb = AIPrediction.from_dict_flexible(valid_combo_data, current_balance=500.0)
        self.assertEqual(pred_valid_comb.recommended_action, "BET")

    def test_sportybet_helper_message(self):
        from telegram_bot.messages import format_sportybet_helper_message
        from core.models import BetRecord

        rec = BetRecord(
            id=1,
            day_number=1,
            event_name="Arsenal vs Chelsea",
            market="Double Chance",
            selection="1X",
            odds=1.28,
            stake=500.0,
            potential_return=640.0,
        )
        msg = format_sportybet_helper_message(rec, currency="NGN")
        self.assertIn("SPORTYBET FAST BETSLIP GUIDE", msg)
        self.assertIn("sportybet.com/ng", msg)
        self.assertIn("500.00 NGN", msg)
        self.assertIn("1.28", msg)

    def test_sportybet_service_matching(self):
        from intelligence.sportybet_service import SportyBetService

        service = SportyBetService()
        mock_events = [
            {
                "eventId": "sr:match:123456",
                "homeTeamName": "Real Madrid",
                "awayTeamName": "Barcelona",
                "markets": [
                    {
                        "id": "1",
                        "desc": "1X2",
                        "outcomes": [{"id": "1", "desc": "Home"}, {"id": "2", "desc": "Draw"}, {"id": "3", "desc": "Away"}]
                    },
                    {
                        "id": "10",
                        "desc": "Double Chance",
                        "outcomes": [{"id": "9", "desc": "Home or Draw"}, {"id": "10", "desc": "Home or Away"}, {"id": "11", "desc": "Draw or Away"}]
                    },
                    {
                        "id": "18",
                        "desc": "Over/Under",
                        "specifier": "total=1.5",
                        "outcomes": [{"id": "12", "desc": "Over 1.5"}, {"id": "13", "desc": "Under 1.5"}]
                    }
                ]
            }
        ]

        # Test matching Double Chance 1X
        matched_dc = service.match_selection("Real Madrid vs Barcelona", "Double Chance", "1X", mock_events)
        self.assertIsNotNone(matched_dc)
        self.assertEqual(matched_dc["eventId"], "sr:match:123456")
        self.assertEqual(matched_dc["marketId"], "10")
        self.assertEqual(matched_dc["outcomeId"], "9")

        # Test matching Over 1.5
        matched_ou = service.match_selection("Real Madrid vs Barcelona", "Over 1.5 Goals", "Over 1.5", mock_events)
        self.assertIsNotNone(matched_ou)
        self.assertEqual(matched_ou["eventId"], "sr:match:123456")
        self.assertEqual(matched_ou["marketId"], "18")
        self.assertEqual(matched_ou["outcomeId"], "12")
        self.assertEqual(matched_ou["specifier"], "total=1.5")


if __name__ == "__main__":
    unittest.main()


