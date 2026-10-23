"""Automated Win/Loss Settlement Engine for SportyBet & Multi-Sport Bets.

Tracks PENDING bets in SQLite ledger, queries official match scores from
SportyBet API and ESPN live scoreboards, evaluates bet outcomes across
all markets (1X2, DC, DNB, Over/Under, GG, Team Totals, Basketball),
and automatically updates user bankrolls and dispatches Telegram notifications.
"""

import logging
import re
from typing import Dict, Any, List, Optional, Tuple
import httpx

from core.ledger import SQLiteLedger
from core.models import BetRecord
from intelligence.sportybet_service import SportyBetService
import config

logger = logging.getLogger(__name__)


import time

_ESPN_SCORES_CACHE: Dict[str, Dict[str, Any]] = {}
_ESPN_SCORES_CACHE_TS: float = 0.0


class AutoSettler:
    ESPN_NBA_URL = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard"

    def __init__(self, ledger: Optional[SQLiteLedger] = None, sporty: Optional[SportyBetService] = None):
        self.ledger = ledger or SQLiteLedger()
        self.sporty = sporty or SportyBetService()

    def fetch_espn_scores(self) -> Dict[str, Dict[str, Any]]:
        """Pulls live and concluded NBA scoreboards from ESPN public API (cached for 120s)."""
        global _ESPN_SCORES_CACHE, _ESPN_SCORES_CACHE_TS
        now_ts = time.time()
        if _ESPN_SCORES_CACHE and (now_ts - _ESPN_SCORES_CACHE_TS < 120.0):
            return _ESPN_SCORES_CACHE

        scores_by_fixture: Dict[str, Dict[str, Any]] = {}
        for url in [self.ESPN_NBA_URL]:
            try:
                r = httpx.get(url, timeout=3.5)
                if r.status_code == 200:
                    events = r.json().get("events", [])
                    for ev in events:
                        comps = ev.get("competitions", [])
                        if not comps:
                            continue
                        c = comps[0]
                        competitors = c.get("competitors", [])
                        if len(competitors) < 2:
                            continue

                        home_c = next((x for x in competitors if x.get("homeAway") == "home"), competitors[0])
                        away_c = next((x for x in competitors if x.get("homeAway") == "away"), competitors[1])

                        home_name = home_c.get("team", {}).get("displayName", "")
                        away_name = away_c.get("team", {}).get("displayName", "")

                        status_type = ev.get("status", {}).get("type", {})
                        is_completed = bool(status_type.get("completed", False))
                        status_desc = status_type.get("description", "")

                        try:
                            home_score = int(home_c.get("score") or 0)
                            away_score = int(away_c.get("score") or 0)
                        except (ValueError, TypeError):
                            home_score, away_score = 0, 0

                        home_lines = home_c.get("linescores", [])
                        away_lines = away_c.get("linescores", [])
                        home_ht = None
                        away_ht = None
                        if len(home_lines) >= 2 and len(away_lines) >= 2:
                            try:
                                home_ht = int(float(home_lines[0].get("value", 0)) + float(home_lines[1].get("value", 0)))
                                away_ht = int(float(away_lines[0].get("value", 0)) + float(away_lines[1].get("value", 0)))
                            except (ValueError, TypeError):
                                pass

                        period = int(ev.get("status", {}).get("period") or 0)
                        ht_completed = (period >= 3 or is_completed)

                        key = f"{home_name.lower()} vs {away_name.lower()}"
                        scores_by_fixture[key] = {
                            "home_name": home_name,
                            "away_name": away_name,
                            "home_score": home_score,
                            "away_score": away_score,
                            "home_ht_score": home_ht,
                            "away_ht_score": away_ht,
                            "ht_completed": ht_completed,
                            "is_completed": is_completed,
                            "status": status_desc,
                        }
            except Exception as e:
                logger.warning(f"Error fetching ESPN scoreboard ({url}): {e}")
        return scores_by_fixture

    def get_match_score(
        self,
        home_team: str,
        away_team: str,
        event_id: Optional[str] = None,
        espn_cache: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> Optional[Dict[str, Any]]:
        """Attempts to resolve match score and status from SportyBet API or ESPN fallback."""
        # 1. Try SportyBet direct event endpoint
        if event_id:
            sporty_score = self.sporty.get_event_score(event_id)
            if sporty_score and sporty_score.get("home_score") is not None:
                return {
                    "home_score": sporty_score["home_score"],
                    "away_score": sporty_score["away_score"],
                    "is_completed": sporty_score["is_ended"],
                    "status": sporty_score["matchStatus"],
                    "source": "SportyBet",
                }

        # 2. Try ESPN Scoreboard matching
        if not espn_cache:
            espn_cache = self.fetch_espn_scores()

        h_tokens = [t.lower() for t in home_team.split() if len(t) > 2]
        a_tokens = [t.lower() for t in away_team.split() if len(t) > 2]

        for k, data in espn_cache.items():
            k_lower = k.lower()
            h_match = any(t in k_lower for t in h_tokens) if h_tokens else False
            a_match = any(t in k_lower for t in a_tokens) if a_tokens else False
            if h_match and a_match:
                return {
                    "home_score": data.get("home_score", 0),
                    "away_score": data.get("away_score", 0),
                    "home_ht_score": data.get("home_ht_score"),
                    "away_ht_score": data.get("away_ht_score"),
                    "ht_completed": data.get("ht_completed", False),
                    "is_completed": data.get("is_completed", data.get("completed", False)),
                    "status": data.get("status", "Unknown"),
                    "source": "ESPN",
                }

        return None

    @staticmethod
    def evaluate_leg(
        market: str,
        selection: str,
        home_score: int,
        away_score: int,
        home_team: str = "",
        away_team: str = "",
    ) -> Optional[bool]:
        """Evaluates whether an individual match leg WON (True) or LOST (False).
        
        Returns None if condition cannot be determined.
        """
        m_desc = market.lower()
        s_desc = selection.lower()
        total_score = home_score + away_score

        # 1. Both Teams to Score (GG / NG)
        if any(k in m_desc for k in ["both teams to score", "btts", "gg/ng", "gg"]) or s_desc in ["yes", "no", "gg", "ng"]:
            if "no" in s_desc or "ng" in s_desc:
                return (home_score == 0 or away_score == 0)
            return (home_score > 0 and away_score > 0)

        # 2. Double Chance (1X, X2, 12)
        if "double" in m_desc or "dc" in m_desc or any(c in s_desc for c in ["1x", "x2", "12", "or draw", "or away"]):
            if "1x" in s_desc or ("home" in s_desc and "draw" in s_desc) or "or draw" in s_desc:
                return (home_score >= away_score)
            elif "x2" in s_desc or ("away" in s_desc and "draw" in s_desc):
                return (away_score >= home_score)
            elif "12" in s_desc or ("home" in s_desc and "away" in s_desc):
                return (home_score != away_score)

        # 3. Draw No Bet (DNB) - Returns True on win or push (draw)
        if "draw no bet" in m_desc or "dnb" in m_desc or "dnb" in s_desc:
            is_home_pick = "home" in s_desc or "1" in s_desc or (home_team and home_team.lower() in s_desc)
            if home_score == away_score:
                return True  # Push returned, stake protected
            if is_home_pick:
                return (home_score > away_score)
            else:
                return (away_score > home_score)

        # 4. Home / Away Team Total Goals (Must be evaluated BEFORE general match total goals)
        if "home" in m_desc and ("goal" in m_desc or "total" in m_desc or "over" in m_desc):
            line_match = re.search(r"(\d+\.?\d*)", f"{m_desc} {s_desc}")
            line = float(line_match.group(1)) if line_match else 0.5
            return (home_score > line) if ("over" in s_desc or "over" in m_desc) else (home_score < line)

        if "away" in m_desc and ("goal" in m_desc or "total" in m_desc or "over" in m_desc):
            line_match = re.search(r"(\d+\.?\d*)", f"{m_desc} {s_desc}")
            line = float(line_match.group(1)) if line_match else 0.5
            return (away_score > line) if ("over" in s_desc or "over" in m_desc) else (away_score < line)

        # 5. Over/Under Total Goals or Points (General match totals)
        is_ou = bool(re.search(r"\b(over|under)\b", f"{m_desc} {s_desc}")) or ("total" in m_desc and "winner" not in m_desc)
        if is_ou and "handicap" not in m_desc and "spread" not in m_desc:
            line_match = re.search(r"(\d+\.?\d*)", f"{m_desc} {s_desc}")
            if line_match:
                line = float(line_match.group(1))
                if bool(re.search(r"\bover\b", f"{m_desc} {s_desc}")):
                    return (total_score > line)
                elif bool(re.search(r"\bunder\b", f"{m_desc} {s_desc}")):
                    return (total_score < line)

        # 6. Basketball Point Spread / Handicap (e.g. "Boston Celtics +8.5", "Spread +6.5", "-4.5", "Handicap")
        if "spread" in m_desc or "handicap" in m_desc or "hcp" in m_desc or ("point" in m_desc and ("+" in s_desc or "-" in s_desc)):
            spread_match = re.search(r"([+-]?\d+(?:\.\d+)?)", s_desc)
            if not spread_match:
                spread_match = re.search(r"([+-]?\d+(?:\.\d+)?)", m_desc)
            if spread_match:
                spread_val = float(spread_match.group(1))
                is_home = (
                    "home" in s_desc
                    or "1" in s_desc.split()
                    or (home_team and any(t in s_desc for t in home_team.lower().split() if len(t) > 2))
                )
                is_away = (
                    "away" in s_desc
                    or "2" in s_desc.split()
                    or (away_team and any(t in s_desc for t in away_team.lower().split() if len(t) > 2))
                )
                if is_away and not is_home:
                    return (away_score + spread_val) > home_score
                else:
                    return (home_score + spread_val) > away_score

        # 7. Basketball Winner (incl. overtime)
        if "winner" in m_desc or "moneyline" in m_desc:
            if home_team and home_team.lower() in s_desc:
                return (home_score > away_score)
            elif away_team and away_team.lower() in s_desc:
                return (away_score > home_score)
            elif "away" in s_desc or " 2" in f" {s_desc}":
                return (away_score > home_score)
            elif "home" in s_desc or " 1" in f" {s_desc}":
                return (home_score > away_score)
            else:
                # Default assume pick is favorite/home if specified team won
                return (home_score > away_score)

        # 8. Standard 1X2 / 2-Up
        if "1x2" in m_desc or "2-up" in m_desc or "2up" in m_desc or "match winner" in m_desc:
            if "draw" in s_desc or s_desc == "x":
                return (home_score == away_score)
            elif "away" in s_desc or s_desc.startswith("2") or (away_team and away_team.lower() in s_desc):
                return (away_score > home_score)
            elif "home" in s_desc or s_desc.startswith("1") or (home_team and home_team.lower() in s_desc):
                return (home_score > away_score)

        return None

    @staticmethod
    def check_early_payout_lead(
        market: str,
        selection: str,
        home_score: int,
        away_score: int,
        home_team: str = "",
        away_team: str = "",
    ) -> bool:
        """Checks if an in-progress game has triggered SportyBet 15-Up (Basketball) or 2-Up (Soccer)."""
        m_desc = market.lower()
        s_desc = selection.lower()
        h_lower = home_team.lower()
        a_lower = away_team.lower()

        # In basketball, a 15+ point lead at any point triggers early payout
        is_basketball = any(k in m_desc for k in ["overtime", "spread", "15-up", "point", "winner"]) or ("goal" not in m_desc and "btts" not in m_desc and "1x2" not in m_desc)
        threshold = 15 if is_basketball else 2

        is_home_pick = (
            "home" in s_desc or s_desc.startswith("1")
            or (h_lower and any(tok in s_desc for tok in h_lower.split() if len(tok) > 2))
        )
        is_away_pick = (
            "away" in s_desc or s_desc.startswith("2")
            or (a_lower and any(tok in s_desc for tok in a_lower.split() if len(tok) > 2))
        )

        if is_home_pick and (home_score - away_score) >= threshold:
            return True
        if is_away_pick and (away_score - home_score) >= threshold:
            return True
        return False

    def check_and_settle_all(self, bot_app=None) -> List[Dict[str, Any]]:
        """Scans all PENDING bets in ledger, auto-grades concluded matches, and dispatches alerts."""
        pending = self.ledger.get_pending_bets()
        if not pending:
            return []

        logger.info(f"AutoSettler checking {len(pending)} pending bets...")
        espn_cache = self.fetch_espn_scores()
        settled_results = []

        for user_id, bet in pending:
            res = self.settle_single_bet(user_id, bet, espn_cache)
            if res:
                settled_results.append(res)
                if bot_app:
                    self._dispatch_telegram_alert(bot_app, user_id, res)

        return settled_results

    def settle_single_bet(
        self,
        user_id: int,
        bet: BetRecord,
        espn_cache: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> Optional[Dict[str, Any]]:
        """Evaluates a single BetRecord. If all fixtures completed, records WON/LOST in ledger."""
        if bet.outcome not in ("PLACED", "PENDING"):
            return None

        # Decompose multi-leg fixtures and markets
        raw_fixtures = [f.strip() for f in bet.event_name.split("+")]
        raw_markets = [m.strip() for m in bet.market.split("+")]
        raw_selections = [s.strip() for s in bet.selection.split("+")]

        num_legs = len(raw_fixtures)
        if len(raw_markets) < num_legs or len(raw_selections) < num_legs:
            # Replicate if single descriptor
            raw_markets = (raw_markets * num_legs)[:num_legs]
            raw_selections = (raw_selections * num_legs)[:num_legs]

        # Check SportyBet ticket details if booking code available
        share_outcomes = []
        if bet.booking_code:
            share_data = self.sporty.get_share_order_details(bet.booking_code)
            if share_data:
                share_outcomes = share_data.get("outcomes", [])

        leg_results = []
        leg_scores = []
        all_completed = True

        for idx, fix in enumerate(raw_fixtures):
            mkt = raw_markets[idx]
            sel = raw_selections[idx]

            parts = fix.split(" vs ")
            h_name = parts[0].strip() if len(parts) > 0 else fix
            a_name = parts[1].strip() if len(parts) > 1 else ""

            # Find matching event_id if available from SportyBet share data
            event_id = None
            for so in share_outcomes:
                so_home = so.get("homeTeamName", "").lower()
                so_away = so.get("awayTeamName", "").lower()
                if h_name.lower() in so_home or so_home in h_name.lower():
                    event_id = so.get("eventId")
                    break

            match_data = self.get_match_score(h_name, a_name, event_id=event_id, espn_cache=espn_cache)
            if not match_data:
                all_completed = False
                break

            h_score = match_data["home_score"]
            a_score = match_data["away_score"]

            is_1st_half = any(k in mkt.lower() or k in sel.lower() for k in ["1st half", "first half", "ht"])

            if not match_data["is_completed"]:
                # 1. 1st Half Over/Under evaluation at halftime
                if is_1st_half and match_data.get("ht_completed") and match_data.get("home_ht_score") is not None:
                    h_ht = match_data["home_ht_score"]
                    a_ht = match_data["away_ht_score"]
                    leg_won = self.evaluate_leg(mkt, sel, h_ht, a_ht, home_team=h_name, away_team=a_name)
                    if leg_won is not None:
                        score_str = f"{h_name} {h_ht} - {a_ht} {a_name} (1st Half Final)"
                        leg_scores.append(score_str)
                        leg_results.append(leg_won)
                        continue

                # 2. Over Points Cleared Early (points only accumulate, so Over bet cannot lose once line exceeded)
                is_over = bool(re.search(r"\bover\b", f"{mkt} {sel}", re.I))
                line_match = re.search(r"(\d+\.?\d*)", f"{mkt} {sel}")
                if is_over and line_match and not is_1st_half and (h_score + a_score) > float(line_match.group(1)):
                    score_str = f"{h_name} {h_score} - {a_score} {a_name} (⚡ Over Points Cleared Early)"
                    leg_scores.append(score_str)
                    leg_results.append(True)
                    continue

                # 3. Check for Early Payout trigger while game is in progress (15-Up in Basketball, 2-Up in Soccer)
                if self.check_early_payout_lead(mkt, sel, h_score, a_score, home_team=h_name, away_team=a_name):
                    score_str = f"{h_name} {h_score} - {a_score} {a_name} (⚡ 15-Up Early Lead Payout)"
                    leg_scores.append(score_str)
                    leg_results.append(True)
                    continue
                else:
                    all_completed = False
                    break

            if is_1st_half and match_data.get("home_ht_score") is not None:
                h_eval = match_data["home_ht_score"]
                a_eval = match_data["away_ht_score"]
                score_str = f"{h_name} {h_eval} - {a_eval} {a_name} (1st Half)"
            else:
                h_eval = h_score
                a_eval = a_score
                score_str = f"{h_name} {h_score} - {a_score} {a_name}"
            leg_scores.append(score_str)

            leg_won = self.evaluate_leg(mkt, sel, h_eval, a_eval, home_team=h_name, away_team=a_name)
            if leg_won is None:
                # Unable to safely determine outcome
                all_completed = False
                break

            leg_results.append(leg_won)

        if not all_completed or len(leg_results) != num_legs:
            return None

        # Determine overall ticket outcome
        overall_won = all(leg_results)

        # Log into SQLite ledger
        payout = bet.potential_return if overall_won else 0.0
        transition = self.ledger.log_bet_outcome(
            user_id=user_id,
            won=overall_won,
            bet_id=bet.id,
            actual_odds=bet.odds,
            actual_payout=payout,
        )

        logger.info(
            f"AutoSettler: Bet #{bet.id} for User {user_id} automatically graded as "
            f"{'WON' if overall_won else 'LOST'} ({' + '.join(leg_scores)})"
        )

        return {
            "bet_id": bet.id,
            "user_id": user_id,
            "won": overall_won,
            "bet": bet,
            "transition": transition,
            "leg_scores": leg_scores,
        }

    def _dispatch_telegram_alert(self, bot_app, user_id: int, result: Dict[str, Any]):
        """Dispatches an asynchronous Telegram notification celebrating win or auditing loss."""
        import asyncio
        bet: BetRecord = result["bet"]
        won = result["won"]
        trans = result["transition"]
        scores_text = "\n".join([f"   • {s}" for s in result["leg_scores"]])

        code_line = f"🎟 *Booking Code:* `{bet.booking_code}`\n" if getattr(bet, "booking_code", None) else ""
        is_soccer = any(k in f"{bet.event_name} {bet.market}".lower() for k in ["goal", "btts", "1x2", "double chance", "dnb", "draw no bet"])
        sport_emoji = "⚽" if is_soccer else "🏀"

        if won:
            profit = round(bet.potential_return - bet.stake, 2)
            withdrawal_text = ""
            if trans.get("is_withdrawal_day") and trans.get("withdrawal_amount", 0) > 0:
                withdrawal_text = (
                    f"\n🚨 *5-DAY PROFIT LOCK TRIGGERED!*\n"
                    f"• Withdrawing 50%: *{trans['withdrawal_amount']:,.2f} {config.DEFAULT_CURRENCY}* to your bank!\n"
                    f"• Compounding Remaining 50%: *{trans['new_balance']:,.2f} {config.DEFAULT_CURRENCY}*\n"
                )

            msg = (
                f"🎉 *CONGRATULATIONS! BET WON!* 🏆\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"Your Day {bet.day_number} placed bet has officially WON!\n\n"
                f"{code_line}"
                f"{sport_emoji} *Match:* `{bet.event_name}`\n"
                f"🎯 *Pick:* `{bet.selection}` @ `{bet.odds:.2f}`\n\n"
                f"📊 *Final Match Scores:*\n{scores_text}\n\n"
                f"💵 *Stake:* `{bet.stake:,.2f} {config.DEFAULT_CURRENCY}`\n"
                f"💰 *Payout Credited:* `+{bet.potential_return:,.2f} {config.DEFAULT_CURRENCY}` (+{profit:,.2f} Profit)\n"
                f"📈 *New Bankroll:* *{trans['new_balance']:,.2f} {config.DEFAULT_CURRENCY}*\n"
                f"🔥 *Winning Streak:* *{trans.get('streak', 1)} in a row!*\n"
                f"{withdrawal_text}\n"
                f"🎯 Tap *🎯 Today's Pick* or type `/today` to prepare your Day {trans['next_day']} pick!"
            )
        else:
            msg = (
                f"💔 *BET LOST — Match Concluded*\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"Your Day {bet.day_number} placed bet did not land.\n\n"
                f"{code_line}"
                f"{sport_emoji} *Match:* `{bet.event_name}`\n"
                f"❌ *Pick Missed:* `{bet.selection}`\n\n"
                f"📊 *Final Match Scores:*\n{scores_text}\n\n"
                f"🛡️ *Capital Preservation Reset:* Bankroll reset to initial stake ({config.DEFAULT_INITIAL_STAKE:,.2f} {config.DEFAULT_CURRENCY}).\n"
                f"🧠 Forensic postmortem has been logged to prevent similar loss vectors.\n\n"
                f"Tap *🎯 Today's Pick* or type `/today` when you're ready for the next setup."
            )

        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.create_task(bot_app.bot.send_message(chat_id=user_id, text=msg, parse_mode="Markdown"))
        except Exception as e:
            logger.warning(f"Could not send Telegram auto-settlement alert to {user_id}: {e}")
