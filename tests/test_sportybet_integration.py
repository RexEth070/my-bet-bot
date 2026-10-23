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
        bb_events = self.service.get_upcoming_events(sport_id="sr:sport:2", page_size=20)
        fb_events = self.service.get_upcoming_events(sport_id="sr:sport:1", page_size=20)
        summary = self.odds_client._format_sportybet_data(bb_events=bb_events, fb_events=fb_events, max_matches=5)
        self.assertIn("TODAY'S OFFICIAL FIXTURES & REAL MARKET ODDS (SportyBet", summary)
        self.assertTrue("1. [BASKETBALL" in summary or "1. [FOOTBALL" in summary or "1. [SOCCER" in summary)

    def test_match_selection_and_booking_code(self):
        fb_events = self.service.get_upcoming_events(sport_id="sr:sport:1", page_size=50)
        self.assertGreater(len(fb_events), 0)
        first_event = fb_events[0]
        home = first_event["homeTeamName"]
        away = first_event["awayTeamName"]
        
        # Test Double Chance on Football
        sel_dc = self.service.match_selection(f"{home} vs {away}", "Double Chance", "1X", fb_events)
        self.assertIsNotNone(sel_dc)
        self.assertEqual(sel_dc["marketId"], "10")
        
        # Test Over/Under Goals on Football
        sel_ou = self.service.match_selection(f"{home} vs {away}", "Over/Under", "Over 1.5", fb_events)
        self.assertIsNotNone(sel_ou)
        self.assertEqual(sel_ou["marketId"], "18")

        # Test Both Teams to Score (GG) on Football
        sel_gg = self.service.match_selection(f"{home} vs {away}", "Both Teams to Score", "GG", fb_events)
        if sel_gg:
            self.assertEqual(sel_gg["marketId"], "29")
            self.assertEqual(sel_gg["outcomeId"], "74")

        # Test Basketball Winner (incl. Overtime)
        bb_events = self.service.get_upcoming_events(sport_id="sr:sport:2", page_size=50)
        if bb_events:
            bb_first = bb_events[0]
            bb_home = bb_first["homeTeamName"]
            bb_away = bb_first["awayTeamName"]
            sel_bb = self.service.match_selection(f"{bb_home} vs {bb_away}", "Winner (incl. Overtime)", bb_home, bb_events)
            if sel_bb:
                self.assertEqual(sel_bb["marketId"], "219")
        
        code, url = self.service.create_booking_code([sel_dc])
        self.assertIsNotNone(code)
        self.assertTrue(len(code) >= 5)
        self.assertTrue(url.startswith("https://www.sportybet.com/ng/?shareCode="))

if __name__ == "__main__":
    unittest.main()
