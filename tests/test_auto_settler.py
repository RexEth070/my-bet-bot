"""Unit tests for the Automated Win/Loss Settlement Engine."""

import unittest
from unittest.mock import MagicMock, patch
from pathlib import Path
import tempfile

from core.auto_settler import AutoSettler
from core.models import BetRecord
from core.ledger import LedgerDB


class TestAutoSettlerRules(unittest.TestCase):
    def setUp(self):
        self.settler = AutoSettler(ledger=MagicMock(), sporty=MagicMock())

    def test_evaluate_double_chance_1x(self):
        # 1X: Home Win (2-1) -> True
        self.assertTrue(self.settler.evaluate_leg("Double Chance", "1X", 2, 1))
        # 1X: Draw (1-1) -> True
        self.assertTrue(self.settler.evaluate_leg("Double Chance", "1X", 1, 1))
        # 1X: Away Win (0-1) -> False
        self.assertFalse(self.settler.evaluate_leg("Double Chance", "1X", 0, 1))

    def test_evaluate_double_chance_x2(self):
        # X2: Away Win (0-2) -> True
        self.assertTrue(self.settler.evaluate_leg("Double Chance", "X2", 0, 2))
        # X2: Draw (0-0) -> True
        self.assertTrue(self.settler.evaluate_leg("Double Chance", "X2", 0, 0))
        # X2: Home Win (3-1) -> False
        self.assertFalse(self.settler.evaluate_leg("Double Chance", "X2", 3, 1))

    def test_evaluate_double_chance_12(self):
        # 12: Home Win (1-0) -> True
        self.assertTrue(self.settler.evaluate_leg("Double Chance", "12", 1, 0))
        # 12: Away Win (0-1) -> True
        self.assertTrue(self.settler.evaluate_leg("Double Chance", "12", 0, 1))
        # 12: Draw (2-2) -> False
        self.assertFalse(self.settler.evaluate_leg("Double Chance", "12", 2, 2))

    def test_evaluate_draw_no_bet(self):
        # Home DNB: Home Win -> True
        self.assertTrue(self.settler.evaluate_leg("Draw No Bet", "Home DNB", 2, 0))
        # Home DNB: Away Win -> False
        self.assertFalse(self.settler.evaluate_leg("Draw No Bet", "Home DNB", 0, 1))
        # Home DNB: Draw -> True (Push returned)
        self.assertTrue(self.settler.evaluate_leg("Draw No Bet", "Home DNB", 1, 1))

    def test_evaluate_total_goals(self):
        # Over 1.5 Goals
        self.assertTrue(self.settler.evaluate_leg("Total Goals", "Over 1.5", 2, 0))
        self.assertTrue(self.settler.evaluate_leg("Total Goals", "Over 1.5", 1, 1))
        self.assertFalse(self.settler.evaluate_leg("Total Goals", "Over 1.5", 1, 0))

        # Under 3.5 Goals
        self.assertTrue(self.settler.evaluate_leg("Total Goals", "Under 3.5", 2, 1))
        self.assertFalse(self.settler.evaluate_leg("Total Goals", "Under 3.5", 3, 2))

    def test_evaluate_btts_gg(self):
        # GG: 1-1 -> True
        self.assertTrue(self.settler.evaluate_leg("Both Teams to Score", "GG", 1, 1))
        # GG: 2-0 -> False
        self.assertFalse(self.settler.evaluate_leg("Both Teams to Score", "GG", 2, 0))
        # NG: 2-0 -> True
        self.assertTrue(self.settler.evaluate_leg("Both Teams to Score", "NG", 2, 0))

    def test_evaluate_team_goals(self):
        # Home Over 0.5 Goals: 1-0 -> True, 0-1 -> False
        self.assertTrue(self.settler.evaluate_leg("Home Team Goals", "Over 0.5", 1, 0))
        self.assertFalse(self.settler.evaluate_leg("Home Team Goals", "Over 0.5", 0, 1))

        # Away Over 1.5 Goals: 1-2 -> True, 1-1 -> False
        self.assertTrue(self.settler.evaluate_leg("Away Team Goals", "Over 1.5", 1, 2))
        self.assertFalse(self.settler.evaluate_leg("Away Team Goals", "Over 1.5", 1, 1))

    def test_evaluate_basketball_winner(self):
        # Home Winner: 110 - 102 -> True
        self.assertTrue(self.settler.evaluate_leg("Winner (incl. overtime)", "Boston Celtics", 110, 102, home_team="Boston Celtics", away_team="Detroit Pistons"))
        # Away Winner: 98 - 105 -> True
        self.assertTrue(self.settler.evaluate_leg("Winner (incl. overtime)", "Away", 98, 105))
        # Home Winner when Away won: 95 - 100 -> False
        self.assertFalse(self.settler.evaluate_leg("Winner (incl. overtime)", "Home", 95, 100))


class TestAutoSettlerIntegration(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test_ledger.db"
        self.ledger = LedgerDB(db_path=self.db_path)
        self.mock_sporty = MagicMock()
        self.settler = AutoSettler(ledger=self.ledger, sporty=self.mock_sporty)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_settle_single_bet_won(self):
        user_id = 999
        self.ledger.get_or_create_user(user_id, initial_stake=500.0)

        bet = BetRecord(
            day_number=1,
            event_name="Arsenal vs Chelsea",
            market="Double Chance",
            selection="1X",
            odds=1.55,
            stake=500.0,
            potential_return=775.0,
            outcome="PENDING",
        )
        bet_id = self.ledger.record_bet(user_id=user_id, bet=bet)
        bet.id = bet_id

        # Mock ESPN cache score: Arsenal 2 - 1 Chelsea (completed)
        espn_cache = {
            "arsenal vs chelsea": {
                "home_score": 2,
                "away_score": 1,
                "completed": True,
                "status": "Final",
            }
        }

        res = self.settler.settle_single_bet(user_id=user_id, bet=bet, espn_cache=espn_cache)
        self.assertIsNotNone(res)
        self.assertTrue(res["won"])
        self.assertEqual(res["transition"]["next_day"], 2)
        self.assertAlmostEqual(res["transition"]["new_balance"], 775.0, places=1)

        # Verify database record updated
        updated_state = self.ledger.get_or_create_user(user_id)
        self.assertEqual(updated_state.current_day, 2)
        self.assertEqual(updated_state.current_streak, 1)
        self.assertEqual(len(self.ledger.get_pending_bets(user_id)), 0)

    def test_settle_single_bet_lost(self):
        user_id = 888
        self.ledger.get_or_create_user(user_id, initial_stake=500.0)

        bet = BetRecord(
            day_number=1,
            event_name="Bayern vs Dortmund",
            market="Total Goals",
            selection="Over 1.5",
            odds=1.52,
            stake=500.0,
            potential_return=760.0,
            outcome="PENDING",
        )
        bet_id = self.ledger.record_bet(user_id=user_id, bet=bet)
        bet.id = bet_id

        # Mock score: 1 - 0 (Total 1 goal -> Lost)
        espn_cache = {
            "bayern vs dortmund": {
                "home_score": 1,
                "away_score": 0,
                "completed": True,
                "status": "Final",
            }
        }

        res = self.settler.settle_single_bet(user_id=user_id, bet=bet, espn_cache=espn_cache)
        self.assertIsNotNone(res)
        self.assertFalse(res["won"])
        self.assertEqual(res["transition"]["next_day"], 1)


        updated_state = self.ledger.get_or_create_user(user_id)
        self.assertEqual(updated_state.current_streak, 0)
        self.assertEqual(updated_state.total_lost_bets, 1)


if __name__ == "__main__":
    unittest.main()
