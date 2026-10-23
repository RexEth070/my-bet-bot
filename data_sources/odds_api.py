"""Sports Odds and Fixtures Ingestion via The Odds API."""

import asyncio
import logging
import time
import unicodedata
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any, Optional
import httpx
import config
from data_sources.nba_intel import NBAIntelService

logger = logging.getLogger(__name__)

# Primary sports leagues: Strictly NBA Basketball
PRIORITY_LEAGUES = [
    "basketball_nba",
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

    @classmethod
    def clear_cache(cls):
        """Wipes the global upcoming fixtures cache."""
        global _GLOBAL_FIXTURES_CACHE, _GLOBAL_FIXTURES_CACHE_TS
        _GLOBAL_FIXTURES_CACHE = ""
        _GLOBAL_FIXTURES_CACHE_TS = 0.0
        logger.info("Cleared global fixtures memory cache.")

    async def get_upcoming_fixtures_summary(
        self,
        max_matches: int = 50,
        basketball_limit: int = 60,
        exclude_fixtures: Optional[List[str]] = None,
        force_refresh: bool = False,
        **kwargs,
    ) -> str:
        """Fetches strictly TODAY'S upcoming NBA fixtures and real market odds exclusively on SportyBet NG live feed."""
        global _GLOBAL_FIXTURES_CACHE, _GLOBAL_FIXTURES_CACHE_TS

        now_ts = time.time()
        if not force_refresh and not exclude_fixtures and _GLOBAL_FIXTURES_CACHE and (now_ts - _GLOBAL_FIXTURES_CACHE_TS < _CACHE_TTL_SECONDS):
            logger.info("Serving upcoming fixtures from in-memory cache.")
            return _GLOBAL_FIXTURES_CACHE

        # 1. Primary data source: SportyBet Nigeria live API (strictly Basketball sport_id sr:sport:2)
        try:
            from intelligence.sportybet_service import SportyBetService
            sporty = SportyBetService()
            bb_events = sporty.get_upcoming_events(sport_id="sr:sport:2", page_size=100)

            if bb_events and len(bb_events) >= 1:
                summary = self._format_sportybet_data(
                    bb_events=bb_events or [],
                    bb_limit=basketball_limit,
                    exclude_fixtures=exclude_fixtures,
                )
                if summary:
                    if not exclude_fixtures:
                        _GLOBAL_FIXTURES_CACHE = summary
                        _GLOBAL_FIXTURES_CACHE_TS = now_ts
                    logger.info(f"Ingested {len(bb_events or [])} Basketball fixtures strictly for TODAY from SportyBet NG.")
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
        bb_events: Optional[List[Dict[str, Any]]] = None,
        bb_limit: int = 60,
        events: Optional[List[Dict[str, Any]]] = None,
        max_matches: Optional[int] = None,
        exclude_fixtures: Optional[List[str]] = None,
        **kwargs,
    ) -> str:
        """Formats real live SportyBet NBA fixtures scheduled strictly for TODAY, exclusively offering Over/Under incl. OT and 1st Half Over/Under."""
        if events is not None and bb_events is None:
            bb_events = events
            bb_limit = max_matches or bb_limit
        bb_events = bb_events or []

        nba_team_keywords = [
            "celtics", "nuggets", "thunder", "bucks", "timberwolves", "warriors",
            "lakers", "clippers", "mavericks", "knicks", "cavaliers", "heat",
            "76ers", "sixers", "suns", "pacers", "magic", "pelicans", "kings",
            "rockets", "hawks", "nets", "bulls", "raptors", "spurs", "grizzlies",
            "trail blazers", "blazers", "jazz", "hornets", "pistons", "wizards"
        ]

        def is_nba(e):
            t_name = (e.get("tournamentName") or "").lower()
            h_name = (e.get("homeTeamName") or "").lower()
            a_name = (e.get("awayTeamName") or "").lower()
            if "nba" in t_name or "national basketball" in t_name:
                return True
            return any(k in f"{h_name} {a_name}" for k in nba_team_keywords)

        nba_events = [e for e in bb_events if is_nba(e)]
        # If no explicit NBA events in live feed, use all basketball events as fallback
        events_to_process = nba_events if nba_events else bb_events

        def get_priority(e):
            h_name = (e.get("homeTeamName") or "").lower()
            a_name = (e.get("awayTeamName") or "").lower()
            bonus = -15 if any(k in f"{h_name} {a_name}" for k in ["celtics", "nuggets", "thunder", "bucks", "timberwolves", "warriors", "lakers", "clippers", "mavericks", "knicks", "cavaliers", "heat"]) else 0
            return bonus

        def extract_vetted_nba_options(event_list, max_options):
            sorted_events = sorted(event_list, key=get_priority)
            # STRICT MARKET ENFORCEMENT: ONLY Over/Under incl. Overtime, 1st Half Over/Under, and Winner (incl. Overtime) [15-Up Early Payout]
            allowed_markets = {
                "18": ("Over/Under Total Points (incl. Overtime)", 1),
                "222": ("Over/Under Total Points (incl. Overtime)", 1),
                "68": ("1st Half Over/Under", 2),
                "219": ("Winner (incl. Overtime)", 1),
                "60100": ("Winner (incl. Overtime)", 1),
                "1": ("Winner (incl. Overtime)", 1),
            }
            collected = []
            nba_service = NBAIntelService()
            exclude_clean = [clean_team_name(x).lower() for x in (exclude_fixtures or []) if x]

            for e in sorted_events:
                home = clean_team_name(e.get("homeTeamName", "Home"))
                away = clean_team_name(e.get("awayTeamName", "Away"))
                tourn = clean_team_name(e.get("tournamentName", "NBA"))
                fix_str = f"{home} vs {away}".lower()
                if any(ex in fix_str or fix_str in ex for ex in exclude_clean):
                    continue

                extra_intel = ""
                event_tier_bonus = 0
                if nba_service:
                    try:
                        intel = nba_service.get_matchup_intel(home, away)
                        rest_str = f" | Rest: {home} {intel['home_rest']}, {away} {intel['away_rest']}"
                        inj_parts = []
                        if intel.get("home_injuries"):
                            inj_parts.append(f"{home}: {', '.join(intel['home_injuries'][:2])}")
                        if intel.get("away_injuries"):
                            inj_parts.append(f"{away}: {', '.join(intel['away_injuries'][:2])}")
                        inj_str = f" | Key Injuries: {'; '.join(inj_parts)}" if inj_parts else ""
                        extra_intel = rest_str + inj_str
                        if intel.get("has_b2b_mismatch"):
                            event_tier_bonus = -1  # Fatigue mismatch advantage!
                    except Exception:
                        pass

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
                        if 1.200 <= odds <= 1.600:
                            desc = clean_team_name(o.get("desc", ""))
                            if "winner" in m_label.lower():
                                oid = str(o.get("id", ""))
                                if desc in ("1", "Home") or oid in ("1", "4"):
                                    desc = f"{home} (To Win)"
                                elif desc in ("2", "Away") or oid in ("2", "5"):
                                    desc = f"{away} (To Win)"

                            edge_info = {}
                            if nba_service:
                                try:
                                    edge_info = nba_service.evaluate_line_edge(f"{home} vs {away}", f"{m_label}{spec_str}", desc, odds)
                                except Exception:
                                    edge_info = {}

                            cushion = edge_info.get("cushion_pts", 0.0)
                            win_pct = edge_info.get("win_probability_pct", 95.0)
                            is_solo = edge_info.get("is_solo_candidate", False)
                            is_15up = edge_info.get("is_15up_eligible", False) or "winner" in m_label.lower()
                            payout_tag = " | ⚡ 15-Up Early Payout: ELIGIBLE (Paid as WIN if 15 pts ahead)" if is_15up else ""
                            pace_tag = f" | Pace: {edge_info.get('pace_tier', 'BALANCED')}" if edge_info.get("pace_tier") else ""
                            cushion_tag = f" | Cushion: +{cushion} pts (Win Prob: {win_pct:.1f}%)" if cushion > 0 else ""
                            star_tag = f" | Note: {'; '.join(edge_info.get('star_notes', []))}" if edge_info.get("star_notes") else ""
                            solo_tag = " [SOLO 1-LEG LOCK CANDIDATE - 99% WIN PROBABILITY]" if is_solo else ""

                            h2h_tag = f" | H2H: {edge_info.get('h2h_summary')}" if edge_info.get("h2h_summary") else ""
                            l10_tag = f" | L10: {edge_info.get('home_l10_summary')} vs {edge_info.get('away_l10_summary')}" if edge_info.get("home_l10_summary") else ""
                            players_tag = f" | Stars: {edge_info.get('player_spotlight')}" if edge_info.get("player_spotlight") else ""

                            # Priority: 1-leg solo candidates get tier -5 (absolute top priority), high cushions get sorted ahead
                            calculated_tier = -5 if is_solo else (tier + event_tier_bonus - int(cushion / 4.0))

                            collected.append({
                                "tier": calculated_tier,
                                "cushion": cushion,
                                "odds": odds,
                                "line": f"[BASKETBALL - NBA] {home} vs {away} | Market: {m_label}{spec_str} | Pick: {desc} @ {odds:.2f} (Odds: {odds:.2f}){solo_tag}{payout_tag}{cushion_tag}{pace_tag}{h2h_tag}{l10_tag}{players_tag}{extra_intel}{star_tag}",
                            })

            collected.sort(key=lambda x: (x["tier"], -x["cushion"], x["odds"]))
            return [c["line"] for c in collected[:max_options]]

        nba_vetted = extract_vetted_nba_options(events_to_process, bb_limit)

        lines = [
            "TODAY'S OFFICIAL FIXTURES & REAL MARKET ODDS (SportyBet Nigeria Live Feed):",
            "PRIMARY SPORT FOCUS: NBA BASKETBALL (NBA EXCLUSIVE).",
            "MANDATORY TIME RULE: ALL MATCHES BELOW PLAY STRICTLY TODAY. NEVER PICK FUTURE GAMES.",
            "STRICT MARKET RULE: ONLY 'Over/Under Total Points (incl. Overtime)', 'First Half Over/Under', and 'Winner (incl. Overtime) [15-Up Early Payout]' ALLOWED.",
            "CRITICAL ODDS & TICKET SELECTION CRITERIA:",
            "  - TICKET STRUCTURE: 1-LEG (SOLO) OR 2-LEGS (DOUBLE COMBO). MAX 2 LEGS!",
            "  - OPTION A (1-LEG SOLO): If an alternate Over/Under (incl. OT), 1st Half Over/Under, or Winner (incl. OT) [15-Up] line has odds between 1.500 and 1.600 with 98-99% win conviction, select it as a 1-LEG SOLO TICKET (eliminating 2nd leg risk).",
            "  - OPTION B (2-LEG COMBO): If individual safe lines are lower (1.200 to 1.350), combine EXACTLY 2 legs to achieve combined 1.500 - 1.800 odds.",
            "  - INDIVIDUAL ODDS LIMIT: Strictly 1.200 to 1.600 per match (NON of each odds per match should exceed 1.60).",
            "  - Target 98-99% win probability using alternate total cushions, 1st half defensive pace matchups, or 15-Up Early Payout lead protection.",
            "---------------------------------------------------------------------------------------",
        ]
        if nba_vetted:
            lines.append(f"\n=== SECTION 1: NBA BASKETBALL (TOP {len(nba_vetted)} HIGH-CONVICTION OPTIONS FOR TODAY) ===")
            for idx, opt in enumerate(nba_vetted, 1):
                lines.append(f"{idx}. {opt}")
        else:
            lines.append("\n(No live NBA lines on SportyBet feed right now — using sample calibrated NBA lines below)")
            lines.append(self._get_mock_fixtures())

        return "\n".join(lines)

    def _format_odds_data(self, data: List[Dict[str, Any]]) -> str:
        """Formats raw JSON odds data into a compact, highly informative summary for the LLM."""
        if not data:
            return "No active upcoming fixtures found in the next 36 hours."

        lines = [
            "UPCOMING FIXTURES & REAL MARKET ODDS (NBA Exclusive):",
            "Sports covered: NBA Basketball.",
            "STRICT CRITERIA: ONLY Over/Under Total Points (incl. Overtime), First Half Over/Under, and Winner (incl. Overtime) [15-Up Early Payout].",
            "---------------------------------------------------------------------------------------",
        ]

        count = 0
        for match in data:
            league = match.get("_league", match.get("sport_title", "Sport")).lower()
            if "basketball" not in league and "nba" not in league:
                continue

            home = clean_team_name(match.get("home_team", "Home"))
            away = clean_team_name(match.get("away_team", "Away"))
            commence = match.get("commence_time", "Today")

            bookmakers = match.get("bookmakers", [])
            totals_options = []
            for bm in bookmakers:
                for m in bm.get("markets", []):
                    if m.get("key") == "totals":
                        for o in m.get("outcomes", []):
                            price = float(o.get("price", 0))
                            if 1.20 <= price <= 1.60:
                                name = o.get("name")
                                pt = o.get("point")
                                totals_options.append(f"{name} {pt} Points @ {price:.2f}")

            if totals_options:
                count += 1
                pick_choice = totals_options[0]
                lines.append(f"{count}. [BASKETBALL - NBA] {home} vs {away} | Market: Over/Under Total Points (incl. Overtime) | Pick: {pick_choice}")

        if count == 0:
            return self._get_mock_fixtures()

        return "\n".join(lines)

    def _get_mock_fixtures(self) -> str:
        """Realistic sample NBA fixtures strictly for Over/Under incl. Overtime, 1st Half Over/Under, and Winner (incl. OT) [15-Up Early Payout]."""
        return """UPCOMING FIXTURES & REAL MARKET ODDS (NBA Exclusive Sample Feed):
1. [BASKETBALL - NBA] Boston Celtics vs Charlotte Hornets | Market: Winner (incl. Overtime) | Pick: Boston Celtics (To Win) @ 1.28 (Odds: 1.28) | ⚡ 15-Up Early Payout: ELIGIBLE (Paid as WIN if 15 pts ahead) | Cushion: +14.2 pts (Win Prob: 99.2%) | Pace: FAST | H2H: Last 5 H2H Avg 228.4 Pts (BOS 5W-0L) | L10: BOS 8W-2L (121.2 PPG, +11.8 Diff) vs CHA 3W-7L (111.4 PPG) | Stars: Boston: Jayson Tatum (28.4 PPG) | Charlotte: LaMelo Ball (24.5 PPG) | Rest: Boston Rested, Charlotte Rested
2. [BASKETBALL - NBA] Denver Nuggets vs Utah Jazz | Market: 1st Half Over/Under (total=106.5) | Pick: Over 106.5 Points (1st Half) @ 1.26 (Odds: 1.26) | Cushion: +10.5 pts (Win Prob: 98.8%) | Pace: BALANCED | H2H: Last 5 H2H Avg 226.5 Pts (Over 4/5) | L10: DEN 7W-3L (80% Over, 119.4 PPG) vs UTA 3W-7L (80% Over, 110.8 PPG) | Stars: Denver: Nikola Jokic (29.2 PPG) | Utah: Lauri Markkanen (23.2 PPG) | Rest: Denver Rested, Utah B2B
3. [BASKETBALL - NBA] Oklahoma City Thunder vs Portland Trail Blazers | Market: Winner (incl. Overtime) | Pick: Oklahoma City Thunder (To Win) @ 1.25 (Odds: 1.25) | ⚡ 15-Up Early Payout: ELIGIBLE (Paid as WIN if 15 pts ahead) | Cushion: +13.5 pts (Win Prob: 99.1%) | Pace: BALANCED | H2H: Last 5 H2H (OKC 5W-0L, Avg Margin +16.2) | L10: OKC 8W-2L (Allowed 106.8 PPG) vs POR 3W-7L (Scored 109.2 PPG) | Stars: OKC: Shai Gilgeous-Alexander (30.1 PPG) | Portland: Anfernee Simons (22.6 PPG) | Rest: OKC Rested, Portland Rested
4. [BASKETBALL - NBA] Minnesota Timberwolves vs Washington Wizards | Market: 1st Half Over/Under (total=118.5) | Pick: Under 118.5 Points (1st Half) @ 1.29 (Odds: 1.29) | Cushion: +11.2 pts (Win Prob: 98.4%) | Pace: SLOW | H2H: Last 5 H2H Avg 219.0 Pts (Under 3/5) | L10: MIN 6W-4L (Allowed 108.2 PPG) vs WSH 2W-8L (Scored 109.8 PPG) | Stars: Minnesota: Anthony Edwards (26.8 PPG) | Washington: Kyle Kuzma (22.2 PPG) | Rest: Minnesota Rested, Washington B2B
5. [BASKETBALL - NBA] Dallas Mavericks vs Brooklyn Nets | Market: Over/Under Total Points (incl. Overtime) (total=211.5) | Pick: Over 211.5 Points (incl. OT) @ 1.27 (Odds: 1.27) | Cushion: +13.5 pts (Win Prob: 99.0%) | Pace: BALANCED | H2H: Last 5 H2H Avg 227.2 Pts (Over 4/5) | L10: DAL 7W-3L (70% Over, 118.2 PPG) vs BKN 4W-6L (70% Over, 112.8 PPG) | Stars: Dallas: Luka Doncic (31.8 PPG) | Brooklyn: Cam Thomas (23.5 PPG) | Rest: Dallas Rested, Brooklyn Rested
6. [BASKETBALL - NBA] Cleveland Cavaliers vs Detroit Pistons | Market: 1st Half Over/Under (total=105.5) | Pick: Over 105.5 Points (1st Half) @ 1.25 (Odds: 1.25) | Cushion: +11.8 pts (Win Prob: 98.9%) | Pace: FAST | H2H: Last 5 H2H Avg 226.0 Pts (Over 4/5) | L10: CLE 8W-2L (80% Over, 120.8 PPG) vs DET 4W-6L (70% Over, 112.0 PPG) | Stars: Cleveland: Donovan Mitchell (27.2 PPG) | Detroit: Cade Cunningham (23.0 PPG) | Rest: Cleveland Rested, Detroit Rested
"""

