"""Sports Odds and Fixtures Ingestion via The Odds API."""

import asyncio
import logging
import time
import unicodedata
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any, Optional
import httpx
import config

logger = logging.getLogger(__name__)

# Primary sports leagues prioritized by liquidity, volume, and predictability
PRIORITY_LEAGUES = [
    "soccer_uefa_champs_league",
    "soccer_epl",
    "soccer_spain_la_liga",
    "soccer_germany_bundesliga",
    "soccer_italy_serie_a",
    "soccer_france_ligue_one",
    "soccer_netherlands_eredivisie",
    "soccer_portugal_primeira_liga",
    "soccer_uefa_europa_league",
    "soccer_uefa_europa_conference_league",
    "soccer_england_championship",
    "soccer_saudi_pro_league",
    "soccer_turkey_super_lig",
    "basketball_nba",
    "basketball_euroleague",
]

# Global cache shared across bot sessions to conserve API quota
_GLOBAL_FIXTURES_CACHE: Optional[str] = None
_GLOBAL_FIXTURES_CACHE_TS: float = 0.0
_CACHE_TTL_SECONDS: int = 600  # 10 minutes cache for dynamic live line changes


def clean_team_name(name: str) -> str:
    """Normalizes accented/diacritic characters to clean ASCII (e.g. ŠK Slovan -> SK Slovan)."""
    if not name:
        return ""
    normalized = unicodedata.normalize("NFKD", name)
    cleaned = "".join(c for c in normalized if not unicodedata.combining(c))
    return cleaned.encode("ascii", "ignore").decode("ascii").strip()


class OddsApiClient:
    BASE_URL = "https://api.the-odds-api.com/v4"

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or config.ODDS_API_KEY
        self.regions = config.ODDS_API_REGIONS

    async def get_upcoming_fixtures_summary(self, max_matches: int = 50, football_limit: int = 50, basketball_limit: int = 20) -> str:
        """Fetches strictly TODAY'S upcoming fixtures and real market odds, prioritizing SportyBet NG live feed (50 Football + 20 Basketball options)."""
        global _GLOBAL_FIXTURES_CACHE, _GLOBAL_FIXTURES_CACHE_TS

        now_ts = time.time()
        if _GLOBAL_FIXTURES_CACHE and (now_ts - _GLOBAL_FIXTURES_CACHE_TS < _CACHE_TTL_SECONDS):
            logger.info("Serving upcoming fixtures from in-memory cache.")
            return _GLOBAL_FIXTURES_CACHE

        # 1. Primary data source: SportyBet Nigeria live API (100% matched for booking code generation)
        try:
            from intelligence.sportybet_service import SportyBetService
            sporty = SportyBetService()
            fb_events = sporty.get_upcoming_events(sport_id="sr:sport:1", page_size=100)
            bb_events = sporty.get_upcoming_events(sport_id="sr:sport:2", page_size=50)

            if (fb_events and len(fb_events) >= 3) or (bb_events and len(bb_events) >= 1):
                summary = self._format_sportybet_data(
                    fb_events=fb_events or [],
                    bb_events=bb_events or [],
                    fb_limit=football_limit,
                    bb_limit=basketball_limit,
                )
                if summary:
                    _GLOBAL_FIXTURES_CACHE = summary
                    _GLOBAL_FIXTURES_CACHE_TS = now_ts
                    logger.info(f"Ingested {len(fb_events or [])} Football and {len(bb_events or [])} Basketball fixtures strictly for TODAY from SportyBet NG.")
                    return summary
        except Exception as se:
            logger.warning(f"Could not load SportyBet feed ({se}). Falling back to secondary odds feed.")

        # 2. Secondary data source: The Odds API
        if not self.api_key or "your_" in self.api_key or len(self.api_key) < 10:
            logger.info("Using mock fixtures feed (no API key configured).")
            return self._get_mock_fixtures()

        now_utc = datetime.now(timezone.utc)
        horizon_utc = now_utc + timedelta(hours=24)

        async def fetch_league(client: httpx.AsyncClient, league: str) -> List[Dict[str, Any]]:
            url = f"{self.BASE_URL}/sports/{league}/odds/"
            markets = "h2h,spreads,totals" if "basketball" in league else "h2h,totals"
            params = {
                "apiKey": self.api_key,
                "regions": self.regions,
                "markets": markets,
                "oddsFormat": "decimal",
            }
            try:
                res = await client.get(url, params=params)
                if res.status_code == 200:
                    data = res.json()
                    if isinstance(data, list):
                        valid = []
                        for m in data:
                            commence_str = m.get("commence_time")
                            if commence_str:
                                dt = datetime.fromisoformat(commence_str.replace("Z", "+00:00"))
                                if now_utc <= dt <= horizon_utc:
                                    m["_league"] = league
                                    valid.append(m)
                        return valid
            except Exception as e:
                logger.warning(f"Failed to fetch {league}: {e}")
            return []

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                tasks = [fetch_league(client, lg) for lg in PRIORITY_LEAGUES]
                results = await asyncio.gather(*tasks)

            collected_matches: List[Dict[str, Any]] = []
            for match_list in results:
                collected_matches.extend(match_list)
                if len(collected_matches) >= max_matches:
                    break

            if not collected_matches:
                logger.warning("No matches found in 24h window across priority leagues. Using fallback.")
                summary = self._get_mock_fixtures()
            else:
                summary = self._format_odds_data(collected_matches[:max_matches])

            _GLOBAL_FIXTURES_CACHE = summary
            _GLOBAL_FIXTURES_CACHE_TS = now_ts
            return summary

        except Exception as e:
            logger.error(f"Error fetching odds from TheOddsAPI: {e}. Falling back to sample feed.")
            return self._get_mock_fixtures()

    def _format_sportybet_data(
        self,
        fb_events: Optional[List[Dict[str, Any]]] = None,
        bb_events: Optional[List[Dict[str, Any]]] = None,
        fb_limit: int = 50,
        bb_limit: int = 20,
        events: Optional[List[Dict[str, Any]]] = None,
        max_matches: Optional[int] = None,
    ) -> str:
        """Formats real live SportyBet fixtures scheduled strictly for TODAY with up to 50 Football and 20 Basketball options."""
        if events is not None and fb_events is None:
            fb_events = events
            fb_limit = max_matches or fb_limit
        fb_events = fb_events or []
        bb_events = bb_events or []

        priority_tourns = [
            "champions league", "premier league", "la liga", "laliga", "bundesliga",
            "serie a", "ligue 1", "europa league", "conference league", "eredivisie",
            "primeira liga", "championship", "saudi pro league", "super lig", "fa cup",
            "copa del rey", "coppa italia", "dfb pokal", "brasileiro", "nba", "euroleague",
        ]

        def get_priority(e):
            t_name = (e.get("tournamentName") or "").lower()
            h_name = (e.get("homeTeamName") or "").lower()
            a_name = (e.get("awayTeamName") or "").lower()
            bonus = -10 if any(k in f"{h_name} {a_name}" for k in ["arsenal", "city", "liverpool", "bayern", "madrid", "barcelona", "inter", "dortmund", "psg", "napoli", "chelsea", "juventus", "celtics", "lakers", "warriors", "bucks"]) else 0
            for idx, p in enumerate(priority_tourns):
                if p in t_name:
                    return idx + bonus
            return 99 + bonus

        def extract_vetted_sport_options(event_list, sport_name, max_options):
            sorted_events = sorted(event_list, key=get_priority)
            allowed_fb = {
                "10": ("Double Chance", 1),
                "60110": ("Double Chance 1-Up", 1),
                "18": ("Over/Under Goals", 2),
                "19": ("Home Team Goals", 2),
                "20": ("Away Team Goals", 2),
                "11": ("Draw No Bet", 3),
                "60100": ("1X2 2-Up", 4),
                "1": ("1X2 Match Winner", 4),
                "29": ("Both Teams to Score", 5),
            }
            allowed_bb = {
                "219": ("Winner incl. Overtime", 1),
                "18": ("Total Points", 2),
                "1": ("Regulation 1X2", 3),
            }
            allowed_markets = allowed_fb if sport_name == "Football" else allowed_bb
            collected = []

            for e in sorted_events:
                home = clean_team_name(e.get("homeTeamName", "Home"))
                away = clean_team_name(e.get("awayTeamName", "Away"))
                tourn = clean_team_name(e.get("tournamentName", sport_name))
                for m in e.get("markets", []):
                    mid = str(m.get("id"))
                    if mid not in allowed_markets:
                        continue
                    m_label, tier = allowed_markets[mid]
                    spec = m.get("specifier") or ""
                    spec_str = f" ({spec})" if spec else ""
                    for o in m.get("outcomes", []):
                        if o.get("isActive") != 1:
                            continue
                        try:
                            odds = float(o.get("odds", 0))
                        except (ValueError, TypeError):
                            continue
                        if 1.200 <= odds <= 1.590:
                            desc = clean_team_name(o.get("desc", ""))
                            collected.append({
                                "tier": tier,
                                "odds": odds,
                                "line": f"[{sport_name.upper()} - {tourn}] {home} vs {away} | Market: {m_label}{spec_str} | Pick: {desc} @ {odds:.2f} (Odds: {odds:.2f})",
                            })

            collected.sort(key=lambda x: (x["tier"], x["odds"]))
            return [c["line"] for c in collected[:max_options]]

        fb_vetted = extract_vetted_sport_options(fb_events, "Football", fb_limit)
        bb_vetted = extract_vetted_sport_options(bb_events, "Basketball", bb_limit)

        lines = [
            "TODAY'S OFFICIAL FIXTURES & REAL MARKET ODDS (SportyBet Nigeria Live Feed):",
            "MANDATORY TIME RULE: ALL MATCHES BELOW PLAY STRICTLY TODAY. NEVER PICK FUTURE GAMES.",
            "CRITICAL ODDS CRITERIA:",
            "  - Individual leg odds MUST be strictly between 1.200 and 1.590 (all options below already vetted).",
            "  - Total combined ticket odds MUST be strictly between 1.500 and 1.800 (1 or 2 legs max).",
            "  - Target 98-99% win probability across diversified low-variance markets.",
            "---------------------------------------------------------------------------------------",
            f"\n=== SECTION 1: FOOTBALL (TOP {len(fb_vetted)} HIGH-CONVICTION WINNING OPTIONS FOR TODAY) ===",
        ]
        for idx, opt in enumerate(fb_vetted, 1):
            lines.append(f"{idx}. {opt}")

        if bb_vetted:
            lines.append(f"\n=== SECTION 2: BASKETBALL (TOP {len(bb_vetted)} HIGH-CONVICTION WINNING OPTIONS FOR TODAY) ===")
            for idx, opt in enumerate(bb_vetted, 1):
                lines.append(f"{idx}. {opt}")

        return "\n".join(lines)

    def _format_odds_data(self, data: List[Dict[str, Any]]) -> str:
        """Formats raw JSON odds data into a compact, highly informative summary for the LLM."""
        if not data:
            return "No active upcoming fixtures found in the next 36 hours."

        lines = [
            "UPCOMING FIXTURES & REAL MARKET ODDS (Next 24-36h):",
            "Sports covered: European Soccer & Basketball (NBA / EuroLeague).",
            "MANDATORY 4-PILLAR ANALYSIS PROTOCOL:",
            "  1. Flashscore: Verify form guide (last 5 W/D/L), H2H history, and home/away goal differentials.",
            "  2. WhoScored: Check team tactical ratings, xG/xGA dominance, and style mismatches.",
            "  3. Bet365: Check sharp market consensus, line movement, and 1-Up / 2-Up early payout eligibility.",
            "  4. Injury & Lineup Reports: Check that core spine players (GK, CB, Midfield pivot, Top Scorer) are fit.",
            "GOAL: Pick 1-2 ultra high-probability, low-volatility legs to accumulate ~1.50 cumulative odds.",
            "---------------------------------------------------------------------------------------",
        ]

        for i, match in enumerate(data, 1):
            home = clean_team_name(match.get("home_team", "Home"))
            away = clean_team_name(match.get("away_team", "Away"))
            commence = match.get("commence_time", "Upcoming")
            league = match.get("_league", match.get("sport_title", "Sport"))
            is_basketball = "basketball" in league.lower()

            h2h_summary = "N/A"
            totals_summary = "N/A"
            spreads_summary = "N/A"
            selected_bookmaker_title = "Consensus"

            bookmakers = match.get("bookmakers", [])
            if bookmakers:
                # Prioritize Bet365 or Pinnacle for sharp lines
                bm = bookmakers[0]
                for b in bookmakers:
                    b_key = b.get("key", "").lower()
                    if "bet365" in b_key:
                        bm = b
                        break
                    elif "pinnacle" in b_key or "unibet" in b_key or "williamhill" in b_key:
                        bm = b

                selected_bookmaker_title = bm.get("title", bm.get("key", "Bookmaker"))
                markets = bm.get("markets", [])
                for m in markets:
                    key = m.get("key")
                    outcomes = m.get("outcomes", [])
                    if key == "h2h":
                        h2h_parts = [f"{clean_team_name(o.get('name'))}: {o.get('price')}" for o in outcomes]
                        h2h_summary = " | ".join(h2h_parts)
                    elif key == "totals":
                        tot_parts = [f"{o.get('name')} {o.get('point', '')}: {o.get('price')}" for o in outcomes]
                        totals_summary = " | ".join(tot_parts)
                    elif key == "spreads":
                        sp_parts = [f"{clean_team_name(o.get('name'))} ({o.get('point')}): {o.get('price')}" for o in outcomes]
                        spreads_summary = " | ".join(sp_parts)

            sport_tag = "BASKETBALL" if is_basketball else "SOCCER"
            league_tag = league.replace("soccer_", "").replace("basketball_", "").upper()
            match_details = [
                f"{i}. [{sport_tag} - {league_tag}] {home} vs {away}",
                f"   Kickoff: {commence}",
                f"   Market Odds ({selected_bookmaker_title}): {h2h_summary}",
                f"   Totals: {totals_summary}"
            ]
            if is_basketball and spreads_summary != "N/A":
                match_details.append(f"   Spreads: {spreads_summary}")

            lines.append("\n".join(match_details))

        return "\n".join(lines)

    def _get_mock_fixtures(self) -> str:
        """Realistic sample fixtures for testing without API keys."""
        return """UPCOMING FIXTURES & MARKET ODDS (Sample Feed):
1. Real Madrid vs Celta Vigo | Starts: 20:00 UTC | Odds: Real Madrid (1.25), Draw (6.00), Celta Vigo (11.00) | Double Chance 1X (1.18)
2. Bayern Munich vs Augsburg | Starts: 19:30 UTC | Odds: Bayern (1.15), Draw (8.50), Augsburg (15.00) | Over 1.5 Goals (1.28)
3. Arsenal vs Southampton | Starts: 15:00 UTC | Odds: Arsenal (1.20), Draw (7.00), Southampton (13.00) | Arsenal DNB (1.08)
4. Paris Saint-Germain vs Angers | Starts: 21:00 UTC | Odds: PSG (1.22), Draw (6.50), Angers (12.00) | Over 1.5 Goals (1.20)
5. Manchester City vs Ipswich Town | Starts: 17:30 UTC | Odds: Man City (1.12), Draw (9.00), Ipswich (19.00) | Man City or Draw (1.05)
"""

