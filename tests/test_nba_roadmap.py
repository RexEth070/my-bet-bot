"""Unit tests for the NBA Roadmap Intelligence Engines:
1. NBA Injury & Star / Rim Protector Impact Tracker
2. 30-Team Pace & Defensive Efficiency Analytics Engine
3. Automated SportyBet Fast-Booking Direct Injection
"""

import unittest
from unittest.mock import MagicMock, patch

from data_sources.nba_intel import NBAIntelService, NBA_TEAM_METRICS
from intelligence.sportybet_service import SportyBetService
from core.models import AIPrediction, MatchSelection


class TestNBARoadmapEngines(unittest.TestCase):
    def setUp(self):
        self.intel = NBAIntelService()

    def test_nba_team_metrics_integrity(self):
        # Verify 30 NBA teams exist with realistic metrics
        self.assertEqual(len(NBA_TEAM_METRICS), 30)
        celtics = NBA_TEAM_METRICS["celtics"]
        self.assertGreater(celtics["pace"], 90.0)
        self.assertGreater(celtics["off_rtg"], 100.0)
        self.assertGreater(celtics["def_rtg"], 100.0)

    def test_matchup_projections_calculation(self):
        # Calculate projection between Pacers (high pace) and Knicks (slow pace)
        proj = self.intel.calculate_matchup_projections("Indiana Pacers", "New York Knicks")
        self.assertIn("projected_pace", proj)
        self.assertIn("projected_total_pts", proj)
        self.assertIn("projected_1st_half_pts", proj)
        self.assertIn("pace_tier", proj)

        # 1st half projection should be approximately 50.5% of total
        expected_1st_half = round(proj["projected_total_pts"] * 0.505, 1)
        self.assertAlmostEqual(proj["projected_1st_half_pts"], expected_1st_half, places=1)

    def test_line_edge_cushion_and_win_probability(self):
        # If projected total is ~228 and line is Over 214.5 -> cushion should be > 10 pts
        with patch.object(self.intel, "calculate_matchup_projections", return_value={
            "projected_pace": 101.5,
            "pace_tier": "FAST (High Tempo)",
            "projected_total_pts": 228.5,
            "projected_1st_half_pts": 115.4,
            "star_absence_notes": [],
            "fatigue_notes": "Rested",
        }):
            edge_over = self.intel.evaluate_line_edge(
                fixture="Boston Celtics vs Charlotte Hornets",
                market="Over/Under Total Points (incl. Overtime)",
                selection="Over 214.5 Points (incl. OT)",
                odds=1.55,
            )
            # 228.5 - 214.5 = 14.0 cushion
            self.assertEqual(edge_over["cushion_pts"], 14.0)
            self.assertGreaterEqual(edge_over["win_probability_pct"], 98.0)
            # Odds 1.55 and cushion 14.0 -> Must be flagged as a 1-leg solo lock candidate!
            self.assertTrue(edge_over["is_solo_candidate"])

            # Test 1st Half Over
            edge_ht = self.intel.evaluate_line_edge(
                fixture="Boston Celtics vs Charlotte Hornets",
                market="First Half Over/Under",
                selection="Over 106.5 Points (1st Half)",
                odds=1.26,
            )
            # 115.4 - 106.5 = 8.9 cushion
            self.assertEqual(edge_ht["cushion_pts"], 8.9)
            self.assertGreaterEqual(edge_ht["win_probability_pct"], 95.0)

    def test_star_scorer_and_rim_protector_absence_impact(self):
        mock_intel_data = {
            "injuries_by_team": {
                "milwaukee bucks": [
                    {"name": "Giannis Antetokounmpo", "status": "Out", "desc": "Giannis Antetokounmpo (PF - Out)"}
                ],
                "minnesota timberwolves": [
                    {"name": "Rudy Gobert", "status": "Out", "desc": "Rudy Gobert (C - Out)"}
                ],
            },
            "b2b_teams": set(),
            "fetched_at": 1000.0,
        }
        with patch.object(self.intel, "get_live_intel", return_value=mock_intel_data):
            match_intel = self.intel.get_matchup_intel("Milwaukee Bucks", "Minnesota Timberwolves")
            # Giannis impact detected (approx 9.5 pts)
            self.assertEqual(match_intel["home_off_impact"], 9.5)
            # Gobert rim anchor impact detected (approx 5.5 pts)
            self.assertEqual(match_intel["away_rim_impact"], 5.5)
            self.assertTrue(any("Giannis Antetokounmpo" in n for n in match_intel["star_absence_notes"]))
            self.assertTrue(any("Rudy Gobert" in n for n in match_intel["star_absence_notes"]))

    def test_sportybet_fast_booking_code_injection(self):
        service = SportyBetService()
        pred = AIPrediction(
            title="NBA Solo Pick",
            recommended_action="BET",
            confidence_score=9,
            risk_level="VERY_LOW",
            selections=[
                MatchSelection(
                    fixture="Boston Celtics vs Charlotte Hornets",
                    sport="basketball",
                    market="Over/Under Total Points (incl. Overtime)",
                    selection="Over 214.5 Points (incl. OT)",
                    odds=1.55,
                )
            ],
            combined_odds=1.55,
            suggested_stake=500.0,
            key_factors=["Pace edge verified", "Star roster intact"],
        )

        booked_pred = service.book_prediction(pred)
        # Should have a valid booking code attached
        self.assertIsNotNone(booked_pred.booking_code)
        self.assertTrue(booked_pred.booking_code.startswith("NB") or len(booked_pred.booking_code) >= 5)
        # Should have a valid booking url attached
        self.assertIsNotNone(booked_pred.booking_url)
        self.assertIn("sportybet.com", booked_pred.booking_url)


if __name__ == "__main__":
    unittest.main()
