"""Unit and Integration tests for strict 2-leg odds clamping (1.50 - 1.80),
line extraction/nearest-line verification, and Flash Win / 15-Up Early Payout integration.
"""

import unittest
from intelligence.sportybet_service import SportyBetService, _extract_spec_line
from intelligence.agent_router import AgentRouterClient
from core.models import AIPrediction, MatchSelection, LedgerState
from telegram_bot.messages import format_daily_pick_message


class TestOddsClampingAndLineVerification(unittest.TestCase):
    def setUp(self):
        self.service = SportyBetService()
        self.router = AgentRouterClient()

    def test_extract_spec_line_robustness(self):
        """Ensures ordinals like '1st' or '2nd' never pollute line extraction."""
        self.assertEqual(_extract_spec_line("1st Half Over/Under (total=122.5) Under 122.5"), "122.5")
        self.assertEqual(_extract_spec_line("First Half Over/Under Under 120.5 Points (1st Half)"), "120.5")
        self.assertEqual(_extract_spec_line("Over/Under Total Points (incl. Overtime) Over 208.5 Points (incl. OT)"), "208.5")
        self.assertEqual(_extract_spec_line("Under 114.5"), "114.5")
        self.assertEqual(_extract_spec_line("Over 106.5 Points (1st Half)"), "106.5")
        self.assertEqual(_extract_spec_line("2nd Half Over/Under total=115.5"), "115.5")
        self.assertIsNone(_extract_spec_line("Winner (incl. Overtime)"))

    def test_market_68_exact_and_nearest_line_matching(self):
        """Verifies SportyBet line matching picks the exact line, or nearest safe active line, and rejects distant lines."""
        mock_event = {
            "eventId": "sr:match:999999",
            "homeTeamName": "Philadelphia 76ers",
            "awayTeamName": "Milwaukee Bucks",
            "markets": [
                {
                    "id": "68",
                    "desc": "1st Half - Over/Under",
                    "specifier": "total=110.5",
                    "outcomes": [{"id": "12", "desc": "Over 110.5", "odds": "1.45"}, {"id": "13", "desc": "Under 110.5", "odds": "2.75"}],
                },
                {
                    "id": "68",
                    "desc": "1st Half - Over/Under",
                    "specifier": "total=120.5",
                    "outcomes": [{"id": "12", "desc": "Over 120.5", "odds": "2.75"}, {"id": "13", "desc": "Under 120.5", "odds": "1.45"}],
                },
                {
                    "id": "68",
                    "desc": "1st Half - Over/Under",
                    "specifier": "total=122.5",
                    "outcomes": [{"id": "12", "desc": "Over 122.5", "odds": "2.90"}, {"id": "13", "desc": "Under 122.5", "odds": "1.42"}],
                },
                {
                    "id": "219",
                    "desc": "Winner (incl. overtime)",
                    "specifier": None,
                    "outcomes": [{"id": "4", "desc": "Philadelphia 76ers", "odds": "1.21"}, {"id": "5", "desc": "Milwaukee Bucks", "odds": "4.88"}],
                },
            ],
        }
        events = [mock_event]

        # 1. Exact match for Under 122.5 MUST match total=122.5, NEVER total=110.5!
        sel_exact = self.service.match_selection(
            fixture="Philadelphia 76ers vs Milwaukee Bucks",
            market="1st Half Over/Under (total=122.5)",
            selection="Under 122.5",
            events=events,
        )
        self.assertIsNotNone(sel_exact)
        self.assertEqual(sel_exact["marketId"], "68")
        self.assertEqual(sel_exact["specifier"], "total=122.5")
        self.assertEqual(sel_exact["outcomeId"], "13")

        # 2. Nearest active match when target is 121.0 -> should match total=120.5 (dist 0.5)
        sel_near = self.service.match_selection(
            fixture="Philadelphia 76ers vs Milwaukee Bucks",
            market="1st Half Over/Under (total=121.0)",
            selection="Under 121.0",
            events=events,
        )
        self.assertIsNotNone(sel_near)
        self.assertEqual(sel_near["specifier"], "total=120.5")

        # 3. Distant line (140.0) beyond safe margin -> MUST return None (prevent loss of funds)
        sel_distant = self.service.match_selection(
            fixture="Philadelphia 76ers vs Milwaukee Bucks",
            market="1st Half Over/Under (total=140.0)",
            selection="Under 140.0",
            events=events,
        )
        self.assertIsNone(sel_distant)

        # 4. Flash Win / 15-Up match winner
        sel_flash = self.service.match_selection(
            fixture="Philadelphia 76ers vs Milwaukee Bucks",
            market="Winner (incl. Overtime) [⚡ Flash Win / 15-Up Early Payout]",
            selection="Philadelphia 76ers (To Win)",
            events=events,
        )
        self.assertIsNotNone(sel_flash)
        self.assertEqual(sel_flash["marketId"], "219")
        self.assertEqual(sel_flash["outcomeId"], "4")

    def test_2leg_odds_clamping_boundaries(self):
        """Validates that 2-leg combination tickets strictly stay between 1.500 and 1.800."""
        # Case A: Too low (< 1.50) -> SKIP
        data_low = {
            "title": "Low Combo",
            "recommended_action": "BET",
            "selections": [
                {"fixture": "Team A vs Team B", "sport": "basketball", "market": "Market 1", "selection": "Pick 1", "odds": 1.20},
                {"fixture": "Team C vs Team D", "sport": "basketball", "market": "Market 2", "selection": "Pick 2", "odds": 1.22},
            ],
        }
        pred_low = AIPrediction.from_dict_flexible(data_low, current_balance=1000.0)
        self.assertEqual(pred_low.recommended_action, "SKIP")
        self.assertIn("below 1.500", pred_low.title)

        # Case B: Too high (> 1.80) -> SKIP
        data_high = {
            "title": "High Combo",
            "recommended_action": "BET",
            "selections": [
                {"fixture": "Team A vs Team B", "sport": "basketball", "market": "Market 1", "selection": "Pick 1", "odds": 1.40},
                {"fixture": "Team C vs Team D", "sport": "basketball", "market": "Market 2", "selection": "Pick 2", "odds": 1.40},
            ],
        }
        pred_high = AIPrediction.from_dict_flexible(data_high, current_balance=1000.0)
        self.assertEqual(pred_high.recommended_action, "SKIP")
        self.assertIn("exceeds 1.800", pred_high.title)

        # Case C: Sweet spot (1.50 - 1.80) -> BET
        data_valid = {
            "title": "Valid Combo",
            "recommended_action": "BET",
            "selections": [
                {"fixture": "Team A vs Team B", "sport": "basketball", "market": "Winner (incl. Overtime)", "selection": "Team A (To Win)", "odds": 1.24},
                {"fixture": "Team C vs Team D", "sport": "basketball", "market": "First Half Over/Under", "selection": "Under 118.5", "odds": 1.29},
            ],
        }
        pred_valid = AIPrediction.from_dict_flexible(data_valid, current_balance=1000.0)
        self.assertEqual(pred_valid.recommended_action, "BET")
        self.assertEqual(pred_valid.combined_odds, 1.60)
        self.assertTrue(1.50 <= pred_valid.combined_odds <= 1.80)

    def test_router_fallback_2leg_odds_and_flash_win(self):
        """Verifies agent_router fallback generates 2-leg picks between 1.50 and 1.80 with Flash Win badges."""
        pick = self.router._generate_fallback_pick(current_day=1, current_balance=1000.0, preferred_mode="combo")
        self.assertEqual(len(pick.selections), 2)
        self.assertTrue(1.50 <= pick.combined_odds <= 1.80, f"Odds {pick.combined_odds} outside 1.50-1.80!")
        self.assertEqual(pick.combined_odds, round(pick.selections[0].odds * pick.selections[1].odds, 2))

    def test_telegram_flash_win_badge(self):
        """Ensures telegram pick card displays Flash Win / 15-Up Early Payout badge."""
        sel = MatchSelection(
            fixture="Cleveland Cavaliers vs Brooklyn Nets",
            sport="basketball",
            market="Winner (incl. Overtime) [⚡ Flash Win / 15-Up Early Payout]",
            selection="Cleveland Cavaliers (To Win)",
            odds=1.24,
            is_2up_eligible=True,
            early_payout_rule="15-Up",
            why_picked_club="Dominant Net Rating differential.",
            why_best_option="Flash Win / 15-Up Early Payout: Settle as full WIN as soon as team leads by 15+ points.",
        )
        pred = AIPrediction(
            title="Test Flash Win",
            selections=[sel],
            combined_odds=1.55,
            suggested_stake=500.0,
        )
        state = LedgerState(user_id=123, current_day=1, current_balance=500.0)
        card_text = format_daily_pick_message(pred, state)
        self.assertIn("Flash Win / 15-Up Early Payout", card_text)
        self.assertIn("Instant Full WIN Payout", card_text)


if __name__ == "__main__":
    unittest.main()
