"""Integration and Unit Tests for SportyBet Ingestion and Booking."""

import unittest
from intelligence.sportybet_service import SportyBetService
from data_sources.odds_api import OddsApiClient
from core.models import AIPrediction, MatchSelection

class TestSportyBetIntegration(unittest.TestCase):
    def setUp(self):
        self.service = SportyBetService()
        self.odds_client = OddsApiClient()

    def test_fetch_upcoming_events(self):
        events = self.service.get_upcoming_events(page_size=30)
        self.assertIsInstance(events, list)
        self.assertGreater(len(events), 0)
        first = events[0]
        self.assertIn("eventId", first)
        self.assertIn("homeTeamName", first)
        self.assertIn("awayTeamName", first)

    def test_format_sportybet_data(self):
        events = self.service.get_upcoming_events(page_size=20)
        summary = self.odds_client._format_sportybet_data(events, max_matches=5)
        self.assertIn("TODAY'S OFFICIAL FIXTURES & REAL MARKET ODDS (SportyBet", summary)
        self.assertTrue("1. [FOOTBALL" in summary or "1. [SOCCER" in summary)

    def test_match_selection_and_booking_code(self):
        events = self.service.get_upcoming_events(page_size=50)
        self.assertGreater(len(events), 0)
        first_event = events[0]
        home = first_event["homeTeamName"]
        away = first_event["awayTeamName"]
        
        # Test Double Chance
        sel_dc = self.service.match_selection(f"{home} vs {away}", "Double Chance", "1X", events)
        self.assertIsNotNone(sel_dc)
        self.assertEqual(sel_dc["marketId"], "10")
        
        # Test Over/Under Goals
        sel_ou = self.service.match_selection(f"{home} vs {away}", "Over/Under", "Over 1.5", events)
        self.assertIsNotNone(sel_ou)
        self.assertEqual(sel_ou["marketId"], "18")

        # Test Both Teams to Score (GG)
        sel_gg = self.service.match_selection(f"{home} vs {away}", "Both Teams to Score", "GG", events)
        if sel_gg:
            self.assertEqual(sel_gg["marketId"], "29")
            self.assertEqual(sel_gg["outcomeId"], "74")
        
        code, url = self.service.create_booking_code([sel_dc])
        self.assertIsNotNone(code)
        self.assertTrue(len(code) >= 5)
        self.assertTrue(url.startswith("https://www.sportybet.com/ng/?shareCode="))

if __name__ == "__main__":
    unittest.main()
