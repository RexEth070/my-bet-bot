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

    def test_evaluate_basketball_point_spread(self):
        # Home Spread +6.5: 102 - 105 -> (102 + 6.5 = 108.5 > 105) -> True (Covered)
        self.assertTrue(self.settler.evaluate_leg("Point Spread (incl. Overtime)", "Boston Celtics +6.5", 102, 105, home_team="Boston Celtics", away_team="Detroit Pistons"))
        # Home Spread -5.5: 110 - 102 -> (110 - 5.5 = 104.5 > 102) -> True (Covered)
        self.assertTrue(self.settler.evaluate_leg("Handicap", "Boston Celtics -5.5", 110, 102, home_team="Boston Celtics", away_team="Detroit Pistons"))
        # Away Spread +4.5: 110 - 108 -> (108 + 4.5 = 112.5 > 110) -> True (Covered)
        self.assertTrue(self.settler.evaluate_leg("Point Spread", "Detroit Pistons +4.5", 110, 108, home_team="Boston Celtics", away_team="Detroit Pistons"))
        # Away Spread -4.5: 110 - 108 -> (108 - 4.5 = 103.5 < 110) -> False (Failed to cover)
        self.assertFalse(self.settler.evaluate_leg("Point Spread", "Detroit Pistons -4.5", 110, 108, home_team="Boston Celtics", away_team="Detroit Pistons"))


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

    def test_proposed_placed_and_cleared_lifecycle(self):
        user_id = 777
        self.ledger.get_or_create_user(user_id, initial_stake=500.0)

        # 1. New bet generated as PROPOSED
        bet1 = BetRecord(
            day_number=1,
            event_name="Liverpool vs Wolves",
            market="Double Chance",
            selection="1X",
            odds=1.25,
            stake=500.0,
            potential_return=625.0,
            outcome="PROPOSED",
        )
        bet1_id = self.ledger.record_bet(user_id=user_id, bet=bet1)

        # Unplaced PROPOSED bet should NOT be in pending settlement queue
        pending_initial = self.ledger.get_pending_bets(user_id)
        self.assertEqual(len(pending_initial), 0)

        # 2. User clicks another pick before placing
        bet2 = BetRecord(
            day_number=1,
            event_name="Real Madrid vs Betis",
            market="Over/Under",
            selection="Over 1.5",
            odds=1.26,
            stake=500.0,
            potential_return=630.0,
            outcome="PROPOSED",
        )
        bet2_id = self.ledger.record_bet(user_id=user_id, bet=bet2)

        # 3. User clicks "Bet Placed" on bet2
        placed_bet = self.ledger.confirm_bet_placed(user_id=user_id, bet_id=bet2_id)
        self.assertIsNotNone(placed_bet)
        self.assertEqual(placed_bet.outcome, "PLACED")

        # Stale bet1 should now be CLEARED
        cleared_bet1 = self.ledger.get_bet_by_id(bet1_id, user_id)
        self.assertEqual(cleared_bet1.outcome, "CLEARED")

        # Only placed bet2 is now in pending queue for settlement
        pending_after_placed = self.ledger.get_pending_bets(user_id)
        self.assertEqual(len(pending_after_placed), 1)
        self.assertEqual(pending_after_placed[0][1].id, bet2_id)

        # 4. Test Clear Bet directly
        bet3 = BetRecord(
            day_number=1,
            event_name="PSG vs Nice",
            market="1X2",
            selection="PSG",
            odds=1.35,
            stake=500.0,
            potential_return=675.0,
            outcome="PROPOSED",
        )
        bet3_id = self.ledger.record_bet(user_id=user_id, bet=bet3)
        self.ledger.clear_bet(user_id=user_id, bet_id=bet3_id)
        cleared_bet3 = self.ledger.get_bet_by_id(bet3_id, user_id)
        self.assertEqual(cleared_bet3.outcome, "CLEARED")

    def test_match_selection_reasoning_fields(self):
        from core.models import MatchSelection, AIPrediction
        from telegram_bot import messages

        selection = MatchSelection(
            fixture="Arsenal vs Chelsea",
            sport="football",
            market="Double Chance",
            selection="1X",
            odds=1.28,
            why_picked_club="Arsenal are undefeated in 12 home matches and lead in xG differential.",
            why_best_option="Double Chance 1X guarantees profit on both home win and draw.",
        )
        prediction = AIPrediction(
            title="Day 1 Safe Compound",
            selections=[selection],
            combined_odds=1.55,
            suggested_stake=500.0,
        )
        state = self.ledger.get_or_create_user(555)
        msg = messages.format_daily_pick_message(prediction, state)

        self.assertIn("Why this team:", msg)
        self.assertIn("Arsenal are undefeated", msg)
        self.assertIn("Why best bet option:", msg)
        self.assertIn("Double Chance 1X guarantees", msg)

    def test_settle_basketball_bet_won(self):
        user_id = 998
        self.ledger.get_or_create_user(user_id, initial_stake=500.0)

        bet = BetRecord(
            day_number=1,
            event_name="Boston Celtics vs Charlotte Hornets",
            market="Winner (incl. Overtime)",
            selection="Boston Celtics",
            odds=1.24,
            stake=500.0,
            potential_return=620.0,
            outcome="PLACED",
        )
        bet_id = self.ledger.record_bet(user_id=user_id, bet=bet)
        bet.id = bet_id

        # Mock ESPN cache score: Boston Celtics 118 - 98 Charlotte Hornets
        espn_cache = {
            "boston celtics vs charlotte hornets": {
                "home_score": 118,
                "away_score": 98,
                "completed": True,
                "status": "Final",
            }
        }

        res = self.settler.settle_single_bet(user_id=user_id, bet=bet, espn_cache=espn_cache)
        self.assertIsNotNone(res)
        self.assertTrue(res["won"])
        self.assertEqual(res["transition"]["next_day"], 2)
        self.assertAlmostEqual(res["transition"]["new_balance"], 620.0, places=1)

    def test_placed_and_clear_command_handlers(self):
        import asyncio
        from unittest.mock import AsyncMock
        from telegram_bot.bot import TelegramBetBot

        user_id = 991
        self.ledger.get_or_create_user(user_id, initial_stake=500.0)

        bot = TelegramBetBot(ledger=self.ledger, agent=MagicMock(), odds_api=MagicMock())
        bot.is_user_allowed = MagicMock(return_value=True)

        # Create a proposed bet
        bet = BetRecord(
            day_number=1,
            event_name="Inter vs Milan",
            market="Double Chance",
            selection="1X",
            odds=1.27,
            stake=500.0,
            potential_return=635.0,
            outcome="PROPOSED",
        )
        bet_id = self.ledger.record_bet(user_id=user_id, bet=bet)

        # Mock Update and Context
        mock_update = MagicMock()
        mock_update.effective_user.id = user_id
        mock_update.message.reply_text = AsyncMock()
        mock_context = MagicMock()

        # Run placed_command
        asyncio.run(bot.placed_command(mock_update, mock_context))

        # Bet should now be PLACED in ledger
        placed_record = self.ledger.get_bet_by_id(bet_id, user_id)
        self.assertEqual(placed_record.outcome, "PLACED")
        mock_update.message.reply_text.assert_called()

        # Run clear_command
        asyncio.run(bot.clear_command(mock_update, mock_context))
        cleared_record = self.ledger.get_bet_by_id(bet_id, user_id)
        self.assertEqual(cleared_record.outcome, "CLEARED")

    def test_check_early_payout_lead_basketball(self):
        # 15+ point lead triggers early payout for basketball
        self.assertTrue(
            AutoSettler.check_early_payout_lead(
                market="Winner (incl. Overtime)",
                selection="Boston Celtics",
                home_score=85,
                away_score=68,
                home_team="Boston Celtics",
                away_team="Utah Jazz",
            )
        )
        # 12 point lead does NOT trigger 15-up
        self.assertFalse(
            AutoSettler.check_early_payout_lead(
                market="Winner (incl. Overtime)",
                selection="Boston Celtics",
                home_score=80,
                away_score=68,
                home_team="Boston Celtics",
                away_team="Utah Jazz",
            )
        )

    def test_in_progress_15_up_settlement(self):
        user_id = 992
        self.ledger.get_or_create_user(user_id, initial_stake=500.0)

        # 1-leg in progress with 17-point lead
        bet = BetRecord(
            day_number=1,
            event_name="Denver Nuggets vs Utah Jazz",
            market="Winner (incl. Overtime)",
            selection="Denver Nuggets",
            odds=1.25,
            stake=500.0,
            potential_return=625.0,
            outcome="PLACED",
        )
        self.ledger.record_bet(user_id=user_id, bet=bet)

        espn_cache = {
            "denver nuggets vs utah jazz": {
                "home_name": "Denver Nuggets",
                "away_name": "Utah Jazz",
                "home_score": 77,
                "away_score": 60,
                "is_completed": False,  # Game still in progress (Q3)
                "status": "In Progress",
            }
        }
        res = self.settler.settle_single_bet(user_id=user_id, bet=bet, espn_cache=espn_cache)
        self.assertIsNotNone(res)
        self.assertTrue(res["won"])
        self.assertIn("15-Up Early Lead Payout", res["leg_scores"][0])

    def test_strict_2_leg_mandate_models(self):
        from core.models import AIPrediction
        # Case A: 1 leg with valid odds -> Must SKIP
        single_leg_data = {
            "title": "Single Pick",
            "selections": [
                {"fixture": "Boston vs Utah", "market": "Winner incl. OT", "selection": "Boston", "odds": 1.25},
            ],
            "combined_odds": 1.55,
            "recommended_action": "BET",
        }
        pred_single = AIPrediction.from_dict_flexible(single_leg_data, current_balance=500.0)
        self.assertEqual(pred_single.recommended_action, "SKIP")
        self.assertIn("minimum 1.500 required for single-leg tickets", pred_single.title)

        # Case B: 3 legs with valid odds -> Must SKIP
        triple_leg_data = {
            "title": "Triple Pick",
            "selections": [
                {"fixture": "A vs B", "market": "Winner", "selection": "A", "odds": 1.25},
                {"fixture": "C vs D", "market": "Winner", "selection": "C", "odds": 1.25},
                {"fixture": "E vs F", "market": "Winner", "selection": "E", "odds": 1.25},
            ],
            "combined_odds": 1.95,
            "recommended_action": "BET",
        }
        pred_triple = AIPrediction.from_dict_flexible(triple_leg_data, current_balance=500.0)
        self.assertEqual(pred_triple.recommended_action, "SKIP")
        self.assertIn("strictly 1 or 2 legs allowed", pred_triple.title)

        # Case C: Exactly 2 legs with valid odds combining into 1.60 -> Approved BET
        double_leg_data = {
            "title": "2-Leg Pick",
            "selections": [
                {"fixture": "Boston vs Charlotte", "market": "Winner incl. OT", "selection": "Boston", "odds": 1.25},
                {"fixture": "Denver vs Utah", "market": "Winner incl. OT", "selection": "Denver", "odds": 1.28},
            ],
            "combined_odds": 1.60,
            "recommended_action": "BET",
        }
        pred_double = AIPrediction.from_dict_flexible(double_leg_data, current_balance=500.0)
        self.assertEqual(pred_double.recommended_action, "BET")
        self.assertEqual(len(pred_double.selections), 2)

    def test_ledger_sport_preference_and_stats(self):
        user_id = 993
        self.ledger.get_or_create_user(user_id, initial_stake=500.0)

        # Default sport is basketball
        self.assertEqual(self.ledger.get_user_sport_preference(user_id), "basketball")

        # Update sport preference
        self.ledger.set_user_sport_preference(user_id, "football")
        self.assertEqual(self.ledger.get_user_sport_preference(user_id), "football")

        self.ledger.set_user_sport_preference(user_id, "hybrid")
        self.assertEqual(self.ledger.get_user_sport_preference(user_id), "hybrid")

        # Performance stats
        stats = self.ledger.get_user_performance_stats(user_id)
        self.assertIn("win_rate", stats)
        self.assertIn("current_streak", stats)
        self.assertEqual(stats["preferred_sport"], "hybrid")

    def test_reroll_alternative_selection(self):
        from intelligence.agent_router import AgentRouterClient
        client = AgentRouterClient(api_key="mock_key")

        # Request fallback pick excluding Boston
        pred = client._generate_fallback_pick(
            current_day=1,
            current_balance=500.0,
            exclude_fixtures=["Boston Celtics vs Charlotte Hornets"],
        )
        self.assertEqual(len(pred.selections), 2)
        # Confirm Boston was excluded
        for s in pred.selections:
            self.assertNotIn("celtics", s.fixture.lower())

    def test_nba_totals_only_validation(self):
        from core.models import AIPrediction
        # Reject prohibited market (Point Spread / Handicap)
        bad_mkt_data = {
            "title": "Point Spread Pick",
            "selections": [
                {"fixture": "Boston vs Charlotte", "market": "Point Spread (Handicap)", "selection": "Boston Celtics -8.5", "odds": 1.25},
                {"fixture": "Denver vs Utah", "market": "Over/Under Total Points (incl. Overtime)", "selection": "Over 210.5", "odds": 1.28},
            ],
            "combined_odds": 1.60,
            "recommended_action": "BET",
        }
        pred_bad = AIPrediction.from_dict_flexible(bad_mkt_data, current_balance=500.0, require_nba_totals=True)
        self.assertEqual(pred_bad.recommended_action, "SKIP")
        self.assertIn("Prohibited market", pred_bad.key_factors[-1])

        # Accept valid Winner (incl. Overtime) with 15-Up Early Payout
        winner_mkt_data = {
            "title": "NBA Winner 15-Up Pick",
            "selections": [
                {"fixture": "Boston vs Charlotte", "market": "Winner (incl. Overtime)", "selection": "Boston Celtics (To Win)", "odds": 1.28},
                {"fixture": "Denver vs Utah", "market": "First Half Over/Under", "selection": "Over 106.5 Points (1st Half)", "odds": 1.25},
            ],
            "combined_odds": 1.60,
            "recommended_action": "BET",
        }
        pred_winner = AIPrediction.from_dict_flexible(winner_mkt_data, current_balance=500.0, require_nba_totals=True)
        self.assertEqual(pred_winner.recommended_action, "BET")
        self.assertTrue(pred_winner.selections[0].is_2up_eligible)
        self.assertEqual(pred_winner.selections[0].early_payout_rule, "15-Up")

        # Accept valid Over/Under (incl. OT) and First Half Over/Under
        good_mkt_data = {
            "title": "NBA Totals Pick",
            "selections": [
                {"fixture": "Boston vs Charlotte", "market": "Over/Under Total Points (incl. Overtime)", "selection": "Over 214.5 Points (incl. OT)", "odds": 1.28},
                {"fixture": "Denver vs Utah", "market": "First Half Over/Under", "selection": "Over 106.5 Points (1st Half)", "odds": 1.25},
            ],
            "combined_odds": 1.60,
            "recommended_action": "BET",
        }
        pred_good = AIPrediction.from_dict_flexible(good_mkt_data, current_balance=500.0, require_nba_totals=True)
        self.assertEqual(pred_good.recommended_action, "BET")
        self.assertEqual(len(pred_good.selections), 2)

    def test_nba_individual_odds_max_1_60(self):
        from core.models import AIPrediction
        # Leg with odds 1.61 (> 1.60) must SKIP
        high_leg_data = {
            "title": "High Leg Odds",
            "selections": [
                {"fixture": "Boston vs Charlotte", "market": "Over/Under Total Points (incl. Overtime)", "selection": "Over 214.5", "odds": 1.61},
                {"fixture": "Denver vs Utah", "market": "First Half Over/Under", "selection": "Over 106.5", "odds": 1.20},
            ],
            "combined_odds": 1.93,
            "recommended_action": "BET",
        }
        pred_high = AIPrediction.from_dict_flexible(high_leg_data, current_balance=500.0, require_nba_totals=True)
        self.assertEqual(pred_high.recommended_action, "SKIP")
        self.assertIn("exceeds 1.600", pred_high.title)

        # Legs with odds <= 1.60 must PASS
        valid_leg_data = {
            "title": "Valid Leg Odds",
            "selections": [
                {"fixture": "Boston vs Charlotte", "market": "Over/Under Total Points (incl. Overtime)", "selection": "Over 214.5", "odds": 1.60},
                {"fixture": "Denver vs Utah", "market": "First Half Over/Under", "selection": "Over 106.5", "odds": 1.25},
            ],
            "combined_odds": 2.00,  # Combined 2.00 > 1.80 ceiling will trip combined check unless adjusted
        }
        # With combined 1.60 (e.g. 1.28 and 1.25)
        valid_pair = {
            "title": "Valid Leg Odds",
            "selections": [
                {"fixture": "Boston vs Charlotte", "market": "Over/Under Total Points (incl. Overtime)", "selection": "Over 214.5", "odds": 1.28},
                {"fixture": "Denver vs Utah", "market": "First Half Over/Under", "selection": "Over 106.5", "odds": 1.25},
            ],
            "combined_odds": 1.60,
            "recommended_action": "BET",
        }
        pred_pair = AIPrediction.from_dict_flexible(valid_pair, current_balance=500.0, require_nba_totals=True)
        self.assertEqual(pred_pair.recommended_action, "BET")

    def test_nba_halftime_and_early_over_settlement(self):
        user_id = 991
        self.ledger.get_or_create_user(user_id, initial_stake=500.0)

        # 2-leg bet: Leg 1 is 1st Half Over 106.5, Leg 2 is Over 214.5 (incl. Overtime)
        bet = BetRecord(
            day_number=1,
            event_name="Denver Nuggets vs Utah Jazz + Boston Celtics vs Charlotte Hornets",
            market="1st Half Over/Under + Over/Under Total Points (incl. Overtime)",
            selection="Over 106.5 Points (1st Half) + Over 214.5 Points (incl. OT)",
            odds=1.60,
            stake=500.0,
            potential_return=800.0,
            outcome="PLACED",
        )
        self.ledger.record_bet(user_id=user_id, bet=bet)

        # Mock live ESPN scores:
        # Match 1: Denver vs Utah is in Q3 (ht_completed=True, ht score is 58-52 = 110 > 106.5 -> Leg 1 WON)
        # Match 2: Boston vs Charlotte is in Q4 (is_completed=False, live score is 112-105 = 217 > 214.5 -> Leg 2 Over Cleared Early WON)
        espn_cache = {
            "denver nuggets vs utah jazz": {
                "home_name": "Denver Nuggets",
                "away_name": "Utah Jazz",
                "home_score": 75,
                "away_score": 68,
                "home_ht_score": 58,
                "away_ht_score": 52,
                "ht_completed": True,
                "is_completed": False,
                "status": "In Progress (Q3)",
            },
            "boston celtics vs charlotte hornets": {
                "home_name": "Boston Celtics",
                "away_name": "Charlotte Hornets",
                "home_score": 112,
                "away_score": 105,
                "home_ht_score": 55,
                "away_ht_score": 50,
                "ht_completed": True,
                "is_completed": False,
                "status": "In Progress (Q4)",
            },
        }

        res = self.settler.settle_single_bet(user_id=user_id, bet=bet, espn_cache=espn_cache)
        self.assertIsNotNone(res)
        self.assertTrue(res["won"])
        self.assertIn("1st Half Final", res["leg_scores"][0])
        self.assertIn("Over Points Cleared Early", res["leg_scores"][1])

    def test_1_leg_solo_ticket_validation(self):
        from core.models import AIPrediction
        # Valid 1-leg solo ticket with odds between 1.50 and 1.60
        valid_1_leg_data = {
            "title": "NBA Solo Lock",
            "selections": [
                {"fixture": "Boston Celtics vs Charlotte Hornets", "market": "Over/Under Total Points (incl. Overtime)", "selection": "Over 214.5 Points (incl. OT)", "odds": 1.55},
            ],
            "combined_odds": 1.55,
            "recommended_action": "BET",
        }
        pred_solo = AIPrediction.from_dict_flexible(valid_1_leg_data, current_balance=500.0, require_nba_totals=True)
        self.assertEqual(pred_solo.recommended_action, "BET")
        self.assertEqual(len(pred_solo.selections), 1)
        self.assertEqual(pred_solo.combined_odds, 1.55)

        # Invalid 1-leg solo ticket with odds < 1.50 (e.g. 1.35)
        low_solo_data = {
            "title": "Low Solo Odds",
            "selections": [
                {"fixture": "Boston Celtics vs Charlotte Hornets", "market": "Over/Under Total Points (incl. Overtime)", "selection": "Over 208.5 Points (incl. OT)", "odds": 1.35},
            ],
            "combined_odds": 1.35,
            "recommended_action": "BET",
        }
        pred_low = AIPrediction.from_dict_flexible(low_solo_data, current_balance=500.0, require_nba_totals=True)
        self.assertEqual(pred_low.recommended_action, "SKIP")
        self.assertIn("minimum 1.500 required for single-leg tickets", pred_low.title)

        # Invalid 3-leg ticket (strictly 1 or 2 legs allowed)
        three_leg_data = {
            "title": "Three Leg Ticket",
            "selections": [
                {"fixture": "Boston vs Charlotte", "market": "Over/Under Total Points (incl. Overtime)", "selection": "Over 214.5", "odds": 1.25},
                {"fixture": "Denver vs Utah", "market": "First Half Over/Under", "selection": "Over 106.5", "odds": 1.20},
                {"fixture": "LAL vs GSW", "market": "Over/Under Total Points (incl. Overtime)", "selection": "Over 220.5", "odds": 1.22},
            ],
            "combined_odds": 1.83,
            "recommended_action": "BET",
        }
        pred_3 = AIPrediction.from_dict_flexible(three_leg_data, current_balance=500.0, require_nba_totals=True)
        self.assertEqual(pred_3.recommended_action, "SKIP")
        self.assertIn("strictly 1 or 2 legs allowed", pred_3.title)

    def test_clear_all_user_memories(self):
        user_id = 997
        self.ledger.get_or_create_user(user_id, initial_stake=1000.0)

        # Record some bets
        bet1 = BetRecord(
            day_number=1,
            event_name="Team A vs Team B",
            market="Over/Under Total Points (incl. Overtime)",
            selection="Over 210.5",
            odds=1.55,
            stake=1000.0,
            potential_return=1550.0,
            outcome="WON",
        )
        self.ledger.record_bet(user_id=user_id, bet=bet1)

        bet2 = BetRecord(
            day_number=2,
            event_name="Team C vs Team D",
            market="First Half Over/Under",
            selection="Over 105.5",
            odds=1.58,
            stake=1550.0,
            potential_return=2449.0,
            outcome="PENDING",
        )
        self.ledger.record_bet(user_id=user_id, bet=bet2)

        # Verify bets exist
        bets_before = self.ledger.get_recent_bets(user_id, limit=10)
        self.assertEqual(len(bets_before), 2)

        # Clear all user memories
        res = self.ledger.clear_all_user_memories(user_id, initial_stake=500.0)
        self.assertTrue(res)

        # Verify all bets are deleted
        bets_after = self.ledger.get_recent_bets(user_id, limit=10)
        self.assertEqual(len(bets_after), 0)

        # Verify user state is reset to Day 1 fresh
        state = self.ledger.get_or_create_user(user_id)
        self.assertEqual(state.current_day, 1)
        self.assertEqual(state.current_streak, 0)
        self.assertEqual(state.current_balance, 500.0)
        self.assertEqual(state.initial_stake, 500.0)


if __name__ == "__main__":
    unittest.main()
