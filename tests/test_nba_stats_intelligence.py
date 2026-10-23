"""Unit tests for NBA Head-to-Head (H2H), Last 10 Matches Performance & Player Stats Intelligence."""

import unittest
from unittest.mock import patch, MagicMock

from data_sources.nba_intel import (
    NBAIntelService,
    NBA_TEAM_LAST_10_METRICS,
    NBA_KEY_PLAYERS,
    ESPN_TEAM_IDS,
)
from core.models import AIPrediction, MatchSelection, LedgerState
from telegram_bot.messages import format_daily_pick_message


class TestNBAStatsIntelligence(unittest.TestCase):
    def setUp(self):
        self.intel = NBAIntelService()

    def test_all_30_teams_have_last_10_metrics(self):
        """Verify all 30 NBA teams have Last 10 matches data."""
        self.assertEqual(len(NBA_TEAM_LAST_10_METRICS), 30)
        for key, m in NBA_TEAM_LAST_10_METRICS.items():
            self.assertEqual(m["wins"] + m["losses"], 10, f"Team {key} wins+losses != 10")
            self.assertEqual(m["over"] + m["under"], 10, f"Team {key} over+under != 10")
            self.assertGreater(m["ppg_scored"], 100.0)
            self.assertGreater(m["ppg_allowed"], 100.0)
            self.assertGreaterEqual(m["over_pct"], 0.0)
            self.assertLessEqual(m["over_pct"], 100.0)
            self.assertEqual(len(m["recent_scores"]), 10)

    def test_all_30_teams_have_key_players(self):
        """Verify all 30 NBA teams have 2-3 key players with scoring stats."""
        self.assertEqual(len(NBA_KEY_PLAYERS), 30)
        for key, players in NBA_KEY_PLAYERS.items():
            self.assertGreaterEqual(len(players), 2, f"Team {key} has < 2 key players")
            for p in players:
                self.assertIn("name", p)
                self.assertIn("pos", p)
                self.assertIn("ppg", p)
                self.assertGreater(p["ppg"], 8.0)
                self.assertIn("form", p)

    def test_espn_team_ids_coverage(self):
        """Verify ESPN team IDs map 30 teams."""
        self.assertEqual(len(ESPN_TEAM_IDS), 30)
        self.assertEqual(ESPN_TEAM_IDS["celtics"], 2)
        self.assertEqual(ESPN_TEAM_IDS["lakers"], 13)
        self.assertEqual(ESPN_TEAM_IDS["nuggets"], 7)

    def test_get_team_last_10_stats(self):
        """Verify get_team_last_10_stats returns calculated performance."""
        stats = self.intel.get_team_last_10_stats("Boston Celtics")
        self.assertEqual(stats["team_key"], "celtics")
        self.assertEqual(stats["wins"] + stats["losses"], 10)
        self.assertGreaterEqual(stats["wins"], 6)
        self.assertEqual(stats["win_pct"], round((stats["wins"] / 10.0) * 100, 1))
        self.assertGreaterEqual(stats["ppg_scored"], 115.0)
        self.assertEqual(stats["over_count"] + stats["under_count"], 10)
        self.assertGreaterEqual(stats["over_pct"], 60.0)
        self.assertIn("Boston Celtics Last 10:", stats["form_narrative"])
        self.assertIn("Over Hit Rate", stats["form_narrative"])

    def test_get_h2h_stats(self):
        """Verify get_h2h_stats computes historical meetings and Over/Under split."""
        h2h = self.intel.get_h2h_stats("Boston Celtics", "Charlotte Hornets")
        self.assertEqual(h2h["total_meetings_analyzed"], 5)
        self.assertGreaterEqual(h2h["h2h_avg_total"], 220.0)
        self.assertIn("h2h_summary", h2h)
        self.assertIn("Last 5 H2H Meetings", h2h["h2h_summary"])
        self.assertIn("O/U Split", h2h["h2h_summary"])

    def test_get_team_key_players(self):
        """Verify get_team_key_players returns active stars and PPG."""
        players = self.intel.get_team_key_players("Denver Nuggets")
        self.assertGreaterEqual(len(players), 3)
        jokic = players[0]
        self.assertEqual(jokic["name"], "Nikola Jokic")
        self.assertGreater(jokic["ppg"], 28.0)
        self.assertIn("Triple-Double", jokic["role"])
        self.assertEqual(jokic["status"], "Active")

    def test_evaluate_line_edge_convergence_boost(self):
        """Verify line evaluation factors H2H and L10 alignment towards 98-99%+ conviction."""
        edge = self.intel.evaluate_line_edge(
            fixture="Boston Celtics vs Charlotte Hornets",
            market="Over/Under Total Points (incl. Overtime)",
            selection="Over 214.5 Points (incl. OT)",
            odds=1.55,
        )
        self.assertGreater(edge["cushion_pts"], 10.0)
        self.assertGreaterEqual(edge["win_probability_pct"], 98.0)
        self.assertTrue(edge["is_solo_candidate"])
        self.assertIn("h2h_summary", edge)
        self.assertIn("home_l10_summary", edge)
        self.assertIn("player_spotlight", edge)

    def test_telegram_pick_card_renders_h2h_and_l10(self):
        """Verify Telegram message formatter renders H2H, L10, and Key Players without errors."""
        pred = AIPrediction(
            title="High-Conviction NBA Over Lock",
            selections=[
                MatchSelection(
                    fixture="Boston Celtics vs Charlotte Hornets",
                    sport="basketball",
                    market="Over/Under Total Points (incl. Overtime)",
                    selection="Over 214.5 Points (incl. OT)",
                    odds=1.55,
                    commence_time="Today",
                    why_picked_club="Celtics and Hornets combined pace 102.5 with 80% Over hit rate.",
                    why_best_option="Over 214.5 is cushioned 14 points below projected total with OT included.",
                )
            ],
            combined_odds=1.55,
            confidence_score=10,
            risk_level="LOW",
            key_factors=[
                "H2H & L10 Form Audit: Boston and Charlotte both cleared this total in 8/10 games.",
                "Pace & Net Rating: Expected pace exceeds 101.5 possessions per 48m.",
            ],
            suggested_stake=500.0,
            recommended_action="BET",
        )
        state = LedgerState(user_id=123456, current_day=1, current_balance=500.0)
        msg = format_daily_pick_message(pred, state)

        # Assert key intelligence components are rendered
        self.assertIn("1-LEG SOLO PICK", msg)
        self.assertIn("H2H Trend", msg)
        self.assertIn("Home L10 Form", msg)
        self.assertIn("Away L10 Form", msg)
        self.assertIn("Key Players", msg)
        self.assertIn("Safety Cushion", msg)


if __name__ == "__main__":
    unittest.main()
