"""SportyBet Nigeria Booking Code & Betslip Integration Service.

Interacts directly with SportyBet NG's API to fetch official upcoming fixtures,
map AI prediction selections to SportyBet market IDs, and generate live 
shareable booking codes (e.g. 'XKMN3K') and 1-click betslip URLs.
"""

import logging
import re
import time
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any, Optional, Tuple
import httpx

from core.models import AIPrediction, MatchSelection

logger = logging.getLogger(__name__)


_SPORTY_EVENTS_CACHE: Dict[str, Tuple[float, List[Dict[str, Any]]]] = {}
_SPORTY_CACHE_TTL: float = 300.0  # 5 minutes cache


class SportyBetService:
    BASE_URL = "https://www.sportybet.com/api/ng"
    HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json, text/plain, */*",
        "Content-Type": "application/json;charset=UTF-8",
        "Origin": "https://www.sportybet.com",
        "Referer": "https://www.sportybet.com/ng/",
    }

    def __init__(self, timeout: float = 4.5):
        self.timeout = timeout

    def get_upcoming_events(self, sport_id: str = "sr:sport:1", page_size: int = 50) -> List[Dict[str, Any]]:
        """Pulls strictly TODAY's upcoming fixtures and rich market odds from SportyBet NG (cached 5m)."""
        now = time.time()
        if sport_id in _SPORTY_EVENTS_CACHE:
            ts, cached_events = _SPORTY_EVENTS_CACHE[sport_id]
            if now - ts < _SPORTY_CACHE_TTL and cached_events:
                return cached_events

        url = f"{self.BASE_URL}/factsCenter/pcUpcomingEvents"
        safe_page_size = min(page_size, 50)
        market_ids = "1,18,219,220,60100" if "sport:2" in sport_id else "1,10,11,14,16,18,19,20,29,60,60100,60110"
        params = {
            "sportId": sport_id,
            "marketId": market_ids,
            "pageSize": str(safe_page_size),
            "pageNum": "1",
            "todayGames": "true",
            "timeline": "24",
        }
        try:
            with httpx.Client(timeout=self.timeout, headers=self.HEADERS) as client:
                r = client.get(url, params=params)
                if r.status_code == 200:
                    data = r.json()
                    tournaments = data.get("data", {}).get("tournaments", [])
                    now_ms = time.time() * 1000
                    # Strict window: from 15 minutes ago (recent kickoffs) up to 26 hours ahead (today's fixtures)
                    min_past_ms = now_ms - (15 * 60 * 1000)
                    max_future_ms = now_ms + (26 * 3600 * 1000)

                    events = []
                    for t in tournaments:
                        t_name = t.get("name")
                        for e in t.get("events", []):
                            st = e.get("estimateStartTime")
                            # Strictly filter out games on future dates
                            if st and (min_past_ms <= st <= max_future_ms):
                                e["tournamentName"] = t_name
                                events.append(e)

                    logger.info(f"SportyBet fetched {len(events)} events strictly scheduled for TODAY.")
                    _SPORTY_EVENTS_CACHE[sport_id] = (time.time(), events)
                    return events
        except Exception as e:
            logger.warning(f"SportyBet get_upcoming_events error: {e}")
        return []

    def match_selection(
        self,
        fixture: str,
        market: str,
        selection: str,
        events: List[Dict[str, Any]],
    ) -> Optional[Dict[str, Any]]:
        """Maps fixture, market, and selection strings to SportyBet internal IDs across 10+ markets."""
        fix_lower = fixture.lower().replace(" vs ", " ").replace(" v ", " ").replace(" - ", " ")
        fix_tokens = [t for t in fix_lower.split() if len(t) > 2]

        matched_event = None
        for e in events:
            home = e.get("homeTeamName", "").lower()
            away = e.get("awayTeamName", "").lower()
            e_text = f"{home} {away}"
            matches = sum(1 for t in fix_tokens if t in e_text)
            if matches >= 2 or (len(fix_tokens) == 1 and matches == 1):
                matched_event = e
                break

        if not matched_event:
            return None

        event_id = matched_event.get("eventId")
        markets = matched_event.get("markets", [])

        target_m_desc = market.lower()
        target_s_desc = selection.lower()

        home_team = matched_event.get("homeTeamName", "").lower()
        away_team = matched_event.get("awayTeamName", "").lower()

        is_home = (
            "home" in target_s_desc
            or target_s_desc.startswith("1")
            or " 1" in target_s_desc
            or any(w in target_s_desc for w in home_team.split() if len(w) > 3)
        )
        is_away = (
            "away" in target_s_desc
            or target_s_desc.startswith("2")
            or " 2" in target_s_desc
            or any(w in target_s_desc for w in away_team.split() if len(w) > 3)
        )
        is_draw = "draw" in target_s_desc or " x" in f" {target_s_desc} " or target_s_desc.endswith("x") or target_s_desc.startswith("x")

        # 1. Both Teams to Score (GG / NG) [Market 29]
        if any(k in target_m_desc for k in ["both teams to score", "btts", "gg/ng", "gg"]) or target_s_desc in ["yes", "no", "gg", "ng"]:
            m_btts = next((m for m in markets if str(m.get("id")) == "29"), None)
            if m_btts:
                is_no = "no" in target_s_desc or "ng" in target_s_desc
                outcome_id = "76" if is_no else "74"
                return {"eventId": event_id, "marketId": "29", "outcomeId": outcome_id, "specifier": None}

        # 2. 1-Up Early Payout Double Chance [Market 60110]
        if ("1up" in target_m_desc or "1-up" in target_m_desc) and ("double" in target_m_desc or "dc" in target_m_desc):
            m_1up = next((m for m in markets if str(m.get("id")) == "60110"), None)
            if m_1up:
                if (is_home and is_draw) or "1x" in target_s_desc:
                    return {"eventId": event_id, "marketId": "60110", "outcomeId": "9", "specifier": None}
                elif (is_away and is_draw) or "x2" in target_s_desc:
                    return {"eventId": event_id, "marketId": "60110", "outcomeId": "11", "specifier": None}
                elif (is_home and is_away) or "12" in target_s_desc:
                    return {"eventId": event_id, "marketId": "60110", "outcomeId": "10", "specifier": None}
                return {"eventId": event_id, "marketId": "60110", "outcomeId": ("11" if is_away else "9"), "specifier": None}

        # 3. 2-Up Early Payout Match Winner [Market 60100]
        if "2up" in target_m_desc or "2-up" in target_m_desc or "2up" in target_s_desc or "2-up" in target_s_desc:
            m_2up = next((m for m in markets if str(m.get("id")) == "60100"), None)
            if m_2up:
                outcome_id = "1" if is_home else ("3" if is_away else "2")
                return {"eventId": event_id, "marketId": "60100", "outcomeId": outcome_id, "specifier": None}

        # 4. Double Chance (1X, 12, X2) [Market 10]
        if "double" in target_m_desc or "dc" in target_m_desc or target_s_desc in ["1x", "x2", "12"]:
            m_dc = next((m for m in markets if str(m.get("id")) == "10"), None)
            if m_dc:
                if (is_home and is_draw) or "1x" in target_s_desc:
                    return {"eventId": event_id, "marketId": "10", "outcomeId": "9", "specifier": None}
                elif (is_away and is_draw) or "x2" in target_s_desc:
                    return {"eventId": event_id, "marketId": "10", "outcomeId": "11", "specifier": None}
                elif (is_home and is_away) or "12" in target_s_desc:
                    return {"eventId": event_id, "marketId": "10", "outcomeId": "10", "specifier": None}
                return {"eventId": event_id, "marketId": "10", "outcomeId": ("11" if is_away else "9"), "specifier": None}

        # 5. Draw No Bet (DNB) [Market 11]
        if "draw no bet" in target_m_desc or "dnb" in target_m_desc or "dnb" in target_s_desc:
            m_dnb = next((m for m in markets if str(m.get("id")) == "11"), None)
            if m_dnb:
                outcome_id = "4" if is_home else "5"
                return {"eventId": event_id, "marketId": "11", "outcomeId": outcome_id, "specifier": None}

        # 6. Home Team Total Goals Over/Under [Market 19]
        if ("home" in target_m_desc or any(w in target_m_desc for w in home_team.split() if len(w) > 3)) and ("total" in target_m_desc or "over" in target_m_desc or "under" in target_m_desc):
            line = "0.5"
            for candidate in ["0.5", "1.5", "2.5", "3.5"]:
                if candidate in target_m_desc or candidate in target_s_desc:
                    line = candidate
                    break
            m_ht = next((m for m in markets if str(m.get("id")) == "19" and m.get("specifier") == f"total={line}"), None)
            if m_ht:
                outcome_id = "12" if ("over" in target_s_desc or "over" in target_m_desc) else "13"
                return {"eventId": event_id, "marketId": "19", "outcomeId": outcome_id, "specifier": f"total={line}"}

        # 7. Away Team Total Goals Over/Under [Market 20]
        if ("away" in target_m_desc or any(w in target_m_desc for w in away_team.split() if len(w) > 3)) and ("total" in target_m_desc or "over" in target_m_desc or "under" in target_m_desc):
            line = "0.5"
            for candidate in ["0.5", "1.5", "2.5", "3.5"]:
                if candidate in target_m_desc or candidate in target_s_desc:
                    line = candidate
                    break
            m_at = next((m for m in markets if str(m.get("id")) == "20" and m.get("specifier") == f"total={line}"), None)
            if m_at:
                outcome_id = "12" if ("over" in target_s_desc or "over" in target_m_desc) else "13"
                return {"eventId": event_id, "marketId": "20", "outcomeId": outcome_id, "specifier": f"total={line}"}

        # 8. 1st Half 1X2 (HT Result) [Market 60]
        if any(k in target_m_desc for k in ["1st half", "first half", "ht 1x2", "half time"]):
            m_ht1x2 = next((m for m in markets if str(m.get("id")) == "60"), None)
            if m_ht1x2:
                outcome_id = "1" if is_home else ("3" if is_away else "2")
                return {"eventId": event_id, "marketId": "60", "outcomeId": outcome_id, "specifier": None}

        # 9. Over/Under Total Goals or Points [Market 18]
        if "over" in target_m_desc or "under" in target_m_desc or "over" in target_s_desc or "under" in target_s_desc:
            target_text = f"{target_m_desc} {target_s_desc}"
            num_match = re.search(r"(\d+(?:\.\d+)?)", target_text)
            spec_line = num_match.group(1) if num_match else None

            m_ou = None
            if spec_line:
                m_ou = next((m for m in markets if str(m.get("id")) == "18" and m.get("specifier") == f"total={spec_line}"), None)
            if not m_ou:
                # Default to first available market 18 (e.g. primary line)
                m_ou = next((m for m in markets if str(m.get("id")) == "18"), None)

            if m_ou:
                outcome_id = "12" if "over" in target_s_desc else "13"
                return {"eventId": event_id, "marketId": "18", "outcomeId": outcome_id, "specifier": m_ou.get("specifier")}

        # 10. Basketball Winner (incl. overtime) [Market 219]
        m_win = next((m for m in markets if str(m.get("id")) == "219"), None)
        if m_win and (
            any(k in target_m_desc for k in ["winner", "moneyline", "ml", "win", "match"])
            or not any(k in target_m_desc for k in ["1x2", "draw", "regulation"])
        ):
            outcome_id = "4" if is_home else "5"
            return {"eventId": event_id, "marketId": "219", "outcomeId": outcome_id, "specifier": None}

        # 11. Standard 1X2 Match Winner [Market 1]
        m_1x2 = next((m for m in markets if str(m.get("id")) == "1"), None)
        if m_1x2:
            if is_draw and not (is_home or is_away):
                outcome_id = "2"
            elif is_away and not is_home:
                outcome_id = "3"
            else:
                outcome_id = "1"
            return {"eventId": event_id, "marketId": "1", "outcomeId": outcome_id, "specifier": None}

        return None

    def get_event_score(self, event_id: str) -> Optional[Dict[str, Any]]:
        """Retrieves live or ended match status and score from SportyBet."""
        url = f"{self.BASE_URL}/factsCenter/event"
        params = {"eventId": event_id}
        try:
            with httpx.Client(timeout=self.timeout, headers=self.HEADERS) as client:
                r = client.get(url, params=params)
                if r.status_code == 200:
                    d = r.json().get("data", {})
                    if d:
                        m_status = d.get("matchStatus", "")
                        set_score = d.get("setScore", "")
                        is_ended = any(w in m_status.lower() for w in ["ended", "finished", "ft", "after regular time"])
                        home_score, away_score = None, None
                        if set_score and ":" in set_score:
                            parts = set_score.split(":")
                            try:
                                home_score, away_score = int(parts[0].strip()), int(parts[1].strip())
                            except ValueError:
                                pass
                        return {
                            "eventId": event_id,
                            "matchStatus": m_status,
                            "setScore": set_score,
                            "is_ended": is_ended,
                            "home_score": home_score,
                            "away_score": away_score,
                        }
        except Exception as e:
            logger.warning(f"Error fetching event score for {event_id}: {e}")
        return None

    def get_share_order_details(self, share_code: str) -> Optional[Dict[str, Any]]:
        """Retrieves live match statuses and details for an existing booking code from SportyBet."""
        url = f"{self.BASE_URL}/orders/share/{share_code}"
        try:
            with httpx.Client(timeout=self.timeout, headers=self.HEADERS) as client:
                r = client.get(url)
                if r.status_code == 200:
                    return r.json().get("data", {})
        except Exception as e:
            logger.warning(f"Error fetching share order details for {share_code}: {e}")
        return None

    def create_booking_code(self, selections: List[Dict[str, Any]]) -> Tuple[Optional[str], Optional[str]]:
        """Calls SportyBet /orders/share to generate an official booking code."""
        if not selections:
            return None, None
        url = f"{self.BASE_URL}/orders/share"
        try:
            with httpx.Client(timeout=self.timeout, headers=self.HEADERS) as client:
                r = client.post(url, json={"selections": selections})
                if r.status_code == 200:
                    data = r.json()
                    if data.get("bizCode") == 10000:
                        d = data.get("data", {})
                        code = d.get("shareCode")
                        url_out = d.get("shareURL") or f"https://www.sportybet.com/ng/?shareCode={code}"
                        if url_out.startswith("http://"):
                            url_out = "https://" + url_out[7:]
                        return code, url_out
        except Exception as e:
            logger.warning(f"SportyBet create_booking_code error: {e}")
        return None, None

    def book_prediction(self, prediction: AIPrediction) -> AIPrediction:
        """Enriches an AIPrediction with a live SportyBet booking code if matches are found."""
        if prediction.recommended_action == "SKIP" or not prediction.selections:
            return prediction

        events = self.get_upcoming_events()
        if not events:
            return prediction

        sporty_selections = []
        for s in prediction.selections:
            matched = self.match_selection(s.fixture, s.market, s.selection, events)
            if matched:
                sporty_selections.append(matched)

        if len(sporty_selections) == len(prediction.selections):
            code, share_url = self.create_booking_code(sporty_selections)
            if code:
                prediction.booking_code = code
                prediction.booking_url = share_url
                logger.info(f"Generated SportyBet booking code: {code} -> {share_url}")

        return prediction
