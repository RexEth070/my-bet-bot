"""Real-Time NBA Intel: Star Player Injuries, Pace & Defensive Efficiency Engine.

Integrates real-time ESPN injury and scoreboard feeds with comprehensive 30-team
NBA pace and defensive efficiency ratings to compute game projected totals, 
star absence scoring impacts, and mathematical alternate line safety cushions.
"""

import logging
import re
import time
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List, Optional, Tuple
import httpx

logger = logging.getLogger(__name__)

# Cache live intel for 15 minutes to prevent redundant network calls
_NBA_INTEL_CACHE: Optional[Dict[str, Any]] = None
_NBA_INTEL_CACHE_TS: float = 0.0
_INTEL_TTL_SECONDS: float = 900.0  # 15 minutes

# -------------------------------------------------------------------------
# NBA Team Advanced Metrics Database (Pace & Offensive/Defensive Ratings)
# Pace = possessions per 48m, OffRtg = pts/100 poss, DefRtg = pts allowed/100 poss
# -------------------------------------------------------------------------
NBA_TEAM_METRICS: Dict[str, Dict[str, Any]] = {
    "celtics": {"name": "Boston Celtics", "pace": 100.2, "off_rtg": 121.5, "def_rtg": 109.8},
    "thunder": {"name": "Oklahoma City Thunder", "pace": 101.4, "off_rtg": 117.8, "def_rtg": 106.2},
    "nuggets": {"name": "Denver Nuggets", "pace": 98.8, "off_rtg": 119.2, "def_rtg": 113.1},
    "timberwolves": {"name": "Minnesota Timberwolves", "pace": 98.2, "off_rtg": 115.6, "def_rtg": 107.5},
    "knicks": {"name": "New York Knicks", "pace": 97.4, "off_rtg": 118.4, "def_rtg": 112.0},
    "cavaliers": {"name": "Cleveland Cavaliers", "pace": 100.8, "off_rtg": 120.6, "def_rtg": 110.4},
    "pacers": {"name": "Indiana Pacers", "pace": 103.5, "off_rtg": 119.8, "def_rtg": 118.2},
    "mavericks": {"name": "Dallas Mavericks", "pace": 99.8, "off_rtg": 117.9, "def_rtg": 113.8},
    "bucks": {"name": "Milwaukee Bucks", "pace": 100.6, "off_rtg": 117.2, "def_rtg": 114.5},
    "suns": {"name": "Phoenix Suns", "pace": 99.4, "off_rtg": 116.8, "def_rtg": 114.1},
    "warriors": {"name": "Golden State Warriors", "pace": 101.8, "off_rtg": 116.4, "def_rtg": 110.8},
    "lakers": {"name": "Los Angeles Lakers", "pace": 100.9, "off_rtg": 116.0, "def_rtg": 114.6},
    "clippers": {"name": "LA Clippers", "pace": 98.6, "off_rtg": 114.8, "def_rtg": 111.5},
    "kings": {"name": "Sacramento Kings", "pace": 100.5, "off_rtg": 117.0, "def_rtg": 115.2},
    "rockets": {"name": "Houston Rockets", "pace": 100.1, "off_rtg": 114.2, "def_rtg": 109.4},
    "heat": {"name": "Miami Heat", "pace": 97.8, "off_rtg": 113.5, "def_rtg": 111.8},
    "76ers": {"name": "Philadelphia 76ers", "pace": 98.9, "off_rtg": 115.2, "def_rtg": 114.0},
    "magic": {"name": "Orlando Magic", "pace": 98.1, "off_rtg": 112.4, "def_rtg": 108.7},
    "pelicans": {"name": "New Orleans Pelicans", "pace": 99.2, "off_rtg": 114.5, "def_rtg": 113.5},
    "hawks": {"name": "Atlanta Hawks", "pace": 103.8, "off_rtg": 115.4, "def_rtg": 118.9},
    "bulls": {"name": "Chicago Bulls", "pace": 102.4, "off_rtg": 113.8, "def_rtg": 116.5},
    "spurs": {"name": "San Antonio Spurs", "pace": 101.2, "off_rtg": 112.8, "def_rtg": 114.8},
    "grizzlies": {"name": "Memphis Grizzlies", "pace": 102.8, "off_rtg": 116.2, "def_rtg": 112.4},
    "raptors": {"name": "Toronto Raptors", "pace": 101.0, "off_rtg": 112.0, "def_rtg": 117.8},
    "nets": {"name": "Brooklyn Nets", "pace": 99.5, "off_rtg": 112.5, "def_rtg": 116.4},
    "pistons": {"name": "Detroit Pistons", "pace": 99.7, "off_rtg": 111.8, "def_rtg": 115.2},
    "hornets": {"name": "Charlotte Hornets", "pace": 100.4, "off_rtg": 111.2, "def_rtg": 117.1},
    "jazz": {"name": "Utah Jazz", "pace": 101.5, "off_rtg": 110.5, "def_rtg": 119.5},
    "blazers": {"name": "Portland Trail Blazers", "pace": 99.6, "off_rtg": 108.9, "def_rtg": 116.8},
    "wizards": {"name": "Washington Wizards", "pace": 102.6, "off_rtg": 109.4, "def_rtg": 120.2},
}

# -------------------------------------------------------------------------
# Star Scorers (PPG > 20) & Rim Protectors Registry for Absence Impact
# -------------------------------------------------------------------------
NBA_STAR_SCORERS: Dict[str, float] = {
    "doncic": 10.0,
    "antetokounmpo": 9.5,
    "jokic": 9.5,
    "tatum": 8.5,
    "gilgeous-alexander": 9.0,
    "sga": 9.0,
    "curry": 8.5,
    "embiid": 10.0,
    "durant": 8.5,
    "booker": 8.0,
    "edwards": 8.5,
    "mitchell": 8.0,
    "james": 7.5,
    "lillard": 7.5,
    "brunson": 8.5,
    "young": 8.0,
    "haliburton": 7.5,
    "fox": 8.0,
    "morant": 8.5,
    "banchero": 8.0,
    "maxey": 8.0,
    "irving": 7.5,
    "george": 7.0,
    "ball": 7.5,
    "williamson": 8.0,
    "cunningham": 8.0,
    "markkanen": 7.5,
    "lavine": 7.0,
    "siakam": 7.0,
    "wembanyama": 8.5,
    "towns": 7.5,
}

NBA_RIM_PROTECTORS: Dict[str, float] = {
    "gobert": 5.5,
    "davis": 5.0,
    "adebayo": 4.5,
    "wembanyama": 5.5,
    "holmgren": 4.5,
    "lopez": 4.0,
    "turner": 4.0,
    "allen": 4.0,
    "hartenstein": 4.0,
    "claxton": 4.0,
    "jackson jr": 4.5,
    "lively": 3.5,
    "kessler": 4.0,
    "zubac": 3.5,
    "capela": 3.5,
    "poeltl": 3.5,
}


class NBAIntelService:
    INJURIES_URL = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/injuries"
    SCOREBOARD_URL = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard"

    def __init__(self, timeout: float = 4.5):
        self.timeout = timeout

    def get_live_intel(self) -> Dict[str, Any]:
        """Pulls official live injuries and B2B rest data for all NBA teams."""
        global _NBA_INTEL_CACHE, _NBA_INTEL_CACHE_TS
        now = time.time()
        if _NBA_INTEL_CACHE and (now - _NBA_INTEL_CACHE_TS < _INTEL_TTL_SECONDS):
            return _NBA_INTEL_CACHE

        intel = {
            "injuries_by_team": {},
            "b2b_teams": set(),
            "fetched_at": now,
        }

        # 1. Fetch live injuries
        try:
            with httpx.Client(timeout=self.timeout) as client:
                r = client.get(self.INJURIES_URL)
                if r.status_code == 200:
                    data = r.json()
                    for team_entry in data.get("injuries", []):
                        t_name = team_entry.get("displayName", "").lower()
                        inj_list = []
                        for inj in team_entry.get("injuries", []):
                            athlete = inj.get("athlete", {})
                            name = athlete.get("displayName") or athlete.get("name") or "Player"
                            status = inj.get("status", "Questionable")
                            pos = athlete.get("position", {}).get("abbreviation", "")
                            inj_list.append({
                                "name": name,
                                "pos": pos,
                                "status": status,
                                "desc": f"{name} ({pos} - {status})"
                            })
                        if t_name and inj_list:
                            intel["injuries_by_team"][t_name] = inj_list
        except Exception as e:
            logger.warning(f"NBAIntel: Could not fetch injury report ({e})")

        # 2. Fetch yesterday's scoreboard to identify Back-to-Back (0 days rest) teams
        try:
            now_utc = datetime.now(timezone.utc)
            yesterday_str = (now_utc - timedelta(days=1)).strftime("%Y%m%d")
            url = f"{self.SCOREBOARD_URL}?dates={yesterday_str}"
            with httpx.Client(timeout=self.timeout) as client:
                r = client.get(url)
                if r.status_code == 200:
                    evs = r.json().get("events", [])
                    for ev in evs:
                        for c in ev.get("competitions", []):
                            for comp in c.get("competitors", []):
                                t_name = comp.get("team", {}).get("displayName", "").lower()
                                if t_name:
                                    intel["b2b_teams"].add(t_name)
                                    short_name = comp.get("team", {}).get("shortDisplayName", "").lower()
                                    if short_name:
                                        intel["b2b_teams"].add(short_name)
        except Exception as e:
            logger.warning(f"NBAIntel: Could not fetch yesterday's schedule for B2B detection ({e})")

        _NBA_INTEL_CACHE = intel
        _NBA_INTEL_CACHE_TS = now
        return intel

    def _find_team_key(self, team_name: str) -> Optional[str]:
        """Maps any team string (e.g. 'Boston Celtics', 'BOS', 'Celtics') to internal key."""
        t_lower = team_name.lower()
        for key in NBA_TEAM_METRICS:
            if key in t_lower:
                return key
        # Check team full names
        for key, m in NBA_TEAM_METRICS.items():
            if m["name"].lower() in t_lower or t_lower in m["name"].lower():
                return key
        return None

    def get_matchup_intel(self, home_team: str, away_team: str) -> Dict[str, Any]:
        """Returns fatigue & injury context for a specific matchup."""
        intel = self.get_live_intel()
        h_lower = home_team.lower()
        a_lower = away_team.lower()

        h_tokens = [t for t in h_lower.split() if len(t) > 2]
        a_tokens = [t for t in a_lower.split() if len(t) > 2]

        home_b2b = any(any(t in b2b for t in h_tokens) for b2b in intel["b2b_teams"])
        away_b2b = any(any(t in b2b for t in a_tokens) for b2b in intel["b2b_teams"])

        home_injuries_raw = []
        for t_name, injs in intel["injuries_by_team"].items():
            if any(tok in t_name for tok in h_tokens):
                home_injuries_raw = injs
                break

        away_injuries_raw = []
        for t_name, injs in intel["injuries_by_team"].items():
            if any(tok in t_name for tok in a_tokens):
                away_injuries_raw = injs
                break

        home_inj_descriptions = [i["desc"] for i in home_injuries_raw[:3]]
        away_inj_descriptions = [i["desc"] for i in away_injuries_raw[:3]]

        # Analyze Star Scorer & Rim Protector Out impacts
        home_off_impact = 0.0
        away_off_impact = 0.0
        home_rim_impact = 0.0
        away_rim_impact = 0.0
        star_absence_notes = []

        def check_impact(injs):
            off_adj = 0.0
            rim_adj = 0.0
            for item in injs:
                p_name_lower = item["name"].lower()
                status_lower = item["status"].lower()
                is_out = any(s in status_lower for s in ["out", "doubtful", "suspended"])
                if not is_out:
                    continue
                # Star scorer impact
                for star, penalty in NBA_STAR_SCORERS.items():
                    if star in p_name_lower:
                        off_adj += penalty
                        star_absence_notes.append(f"⚠️ Star Scorer Out: {item['name']} (-{penalty:.1f} pts offensive rating)")
                        break
                # Rim protector impact
                for rim, boost in NBA_RIM_PROTECTORS.items():
                    if rim in p_name_lower:
                        rim_adj += boost
                        star_absence_notes.append(f"🛡️ Rim Anchor Out: {item['name']} (+{boost:.1f} pts opponent interior conversion)")
                        break
            return off_adj, rim_adj

        h_off_adj, h_rim_adj = check_impact(home_injuries_raw)
        a_off_adj, a_rim_adj = check_impact(away_injuries_raw)

        return {
            "home_rest": "[B2B - 0 days rest]" if home_b2b else "[Rested - 1+ days rest]",
            "away_rest": "[B2B - 0 days rest]" if away_b2b else "[Rested - 1+ days rest]",
            "home_injuries": home_inj_descriptions,
            "away_injuries": away_inj_descriptions,
            "has_b2b_mismatch": (not home_b2b and away_b2b),
            "home_b2b": home_b2b,
            "away_b2b": away_b2b,
            "home_off_impact": h_off_adj,
            "away_off_impact": a_off_adj,
            "home_rim_impact": h_rim_adj,
            "away_rim_impact": a_rim_adj,
            "star_absence_notes": star_absence_notes,
        }

    def calculate_matchup_projections(self, home_team: str, away_team: str) -> Dict[str, Any]:
        """Calculates advanced pace & defensive efficiency projected game and 1st half totals."""
        h_key = self._find_team_key(home_team) or "celtics"
        a_key = self._find_team_key(away_team) or "nuggets"

        h_metrics = NBA_TEAM_METRICS.get(h_key, {"pace": 100.0, "off_rtg": 115.0, "def_rtg": 113.0})
        a_metrics = NBA_TEAM_METRICS.get(a_key, {"pace": 100.0, "off_rtg": 115.0, "def_rtg": 113.0})

        matchup_intel = self.get_matchup_intel(home_team, away_team)

        # 1. Base Expected Pace
        base_pace = (h_metrics["pace"] + a_metrics["pace"]) / 2.0
        # Fatigue adjustment on pace
        pace_multiplier = 1.0
        if matchup_intel["home_b2b"]:
            pace_multiplier -= 0.012
        if matchup_intel["away_b2b"]:
            pace_multiplier -= 0.015
        projected_pace = round(base_pace * pace_multiplier, 1)

        # 2. Offensive Ratings vs Defensive Ratings
        h_off_eff = (h_metrics["off_rtg"] + a_metrics["def_rtg"]) / 2.0
        a_off_eff = (a_metrics["off_rtg"] + h_metrics["def_rtg"]) / 2.0

        # Home court advantage (~+1.5 pts)
        h_off_eff += 1.5
        # Fatigue adjustments on efficiency
        if matchup_intel["home_b2b"]:
            h_off_eff -= 2.0
        if matchup_intel["away_b2b"]:
            a_off_eff -= 3.2

        # Injury adjustments
        h_off_eff = max(95.0, h_off_eff - matchup_intel["home_off_impact"] + matchup_intel["away_rim_impact"])
        a_off_eff = max(95.0, a_off_eff - matchup_intel["away_off_impact"] + matchup_intel["home_rim_impact"])

        # 3. Expected Points
        home_projected = round(projected_pace * (h_off_eff / 100.0), 1)
        away_projected = round(projected_pace * (a_off_eff / 100.0), 1)
        projected_total = round(home_projected + away_projected, 1)

        # 4. 1st Half Projection (1st halves in modern NBA average ~50.5% of total points)
        projected_1st_half = round(projected_total * 0.505, 1)

        pace_tier = "FAST (High Tempo)" if projected_pace >= 101.5 else ("SLOW (Half-Court Grind)" if projected_pace < 98.5 else "BALANCED")

        # Tactical totals angle
        tactical_angle = "OVER CUSHION FAVORED" if projected_total >= 225.0 else ("UNDER CUSHION FAVORED" if projected_total <= 218.0 else "1ST HALF STABLE")

        return {
            "home_team": home_team,
            "away_team": away_team,
            "projected_pace": projected_pace,
            "pace_tier": pace_tier,
            "home_projected_pts": home_projected,
            "away_projected_pts": away_projected,
            "projected_total_pts": projected_total,
            "projected_1st_half_pts": projected_1st_half,
            "tactical_angle": tactical_angle,
            "star_absence_notes": matchup_intel["star_absence_notes"],
            "fatigue_notes": (
                f"{home_team} {matchup_intel['home_rest']}, {away_team} {matchup_intel['away_rest']}"
            ),
        }

    def evaluate_line_edge(
        self,
        fixture: str,
        market: str,
        selection: str,
        odds: float,
    ) -> Dict[str, Any]:
        """Evaluates mathematical edge & safety cushion of a specific totals line against advanced projections."""
        parts = fixture.split(" vs ")
        home = parts[0].strip() if len(parts) > 1 else fixture
        away = parts[1].strip() if len(parts) > 1 else ""

        proj = self.calculate_matchup_projections(home, away)
        target_text = f"{market} {selection}".lower()

        num_match = re.search(r"(\d+(?:\.\d+)?)", target_text)
        line_num = float(num_match.group(1)) if num_match else 0.0

        is_1st_half = any(k in target_text for k in ["1st half", "first half", "ht"])
        is_over = bool(re.search(r"\bover\b", target_text))
        is_under = bool(re.search(r"\bunder\b", target_text))

        expected_pts = proj["projected_1st_half_pts"] if is_1st_half else proj["projected_total_pts"]

        cushion = 0.0
        if is_over and line_num > 0:
            cushion = round(expected_pts - line_num, 1)
        elif is_under and line_num > 0:
            cushion = round(line_num - expected_pts, 1)

        # Win probability estimation based on cushion margin
        if cushion >= 14.0:
            win_prob = 99.2
        elif cushion >= 11.0:
            win_prob = 98.4
        elif cushion >= 8.0:
            win_prob = 96.5
        elif cushion >= 5.0:
            win_prob = 93.0
        else:
            win_prob = max(80.0, 88.0 + cushion)

        is_solo_candidate = (1.500 <= odds <= 1.600) and (cushion >= 11.0 or win_prob >= 98.0)

        return {
            "projected_pts": expected_pts,
            "market_line": line_num,
            "cushion_pts": cushion,
            "win_probability_pct": win_prob,
            "is_solo_candidate": is_solo_candidate,
            "pace_tier": proj["pace_tier"],
            "projected_pace": proj["projected_pace"],
            "star_notes": proj["star_absence_notes"],
        }
