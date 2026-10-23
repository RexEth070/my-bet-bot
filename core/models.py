"""Pydantic Models and Data Schemas."""

from typing import List, Optional
from datetime import datetime
from pydantic import BaseModel, Field


class MatchSelection(BaseModel):
    fixture: str = Field(default="Match")
    sport: str = "basketball"
    market: str = "Winner (incl. Overtime)"
    selection: str = Field(default="Selection")
    odds: float = 1.25
    commence_time: Optional[str] = None
    is_2up_eligible: bool = False
    early_payout_rule: Optional[str] = None
    why_picked_club: Optional[str] = None
    why_best_option: Optional[str] = None

    @classmethod
    def from_dict_flexible(cls, data: dict) -> "MatchSelection":
        """Flexible constructor accepting LLM naming variations."""
        fixture = data.get("fixture") or data.get("match") or data.get("event") or "Match"
        sport = data.get("sport") or "basketball"
        market = data.get("market") or data.get("bet_type") or "Winner (incl. Overtime)"
        selection = data.get("selection") or data.get("pick") or data.get("bet") or "To Win"
        try:
            odds = float(data.get("odds") or 1.25)
        except (ValueError, TypeError):
            odds = 1.25
        commence = data.get("commence_time") or data.get("time") or "Upcoming"
        
        # Check early payout rule (1-Up, 2-Up, or Basketball 15-Up Lead)
        early_payout = data.get("early_payout_rule") or data.get("early_payout")
        combined_text = f"{market} {selection} {data.get('is_2up_eligible', '')} {data.get('is_1up_eligible', '')}".lower()
        if not early_payout:
            if any(k in combined_text for k in ["15up", "15-up", "18up", "18-up", "early payout"]):
                early_payout = "15-Up"
            elif any(k in market.lower() for k in ["winner", "moneyline", "to win"]):
                early_payout = "15-Up"
            elif "1up" in combined_text or "1-up" in combined_text:
                early_payout = "1-Up"
            elif "2up" in combined_text or "2-up" in combined_text or bool(data.get("is_2up_eligible")):
                early_payout = "2-Up"

        is_2up = bool(early_payout in ("2-Up", "15-Up", "18-Up") or data.get("is_2up_eligible"))

        why_club = (
            data.get("why_picked_club")
            or data.get("club_reason")
            or data.get("team_reason")
            or data.get("why_picked")
            or data.get("reason_club")
        )
        why_option = (
            data.get("why_best_option")
            or data.get("market_reason")
            or data.get("option_reason")
            or data.get("why_best_bet_option")
            or data.get("bet_reason")
        )

        return cls(
            fixture=fixture,
            sport=sport,
            market=market,
            selection=selection,
            odds=odds,
            commence_time=commence,
            is_2up_eligible=is_2up,
            early_payout_rule=early_payout,
            why_picked_club=why_club,
            why_best_option=why_option,
        )


class AIPrediction(BaseModel):
    title: str = "AI Recommended Pick"
    selections: List[MatchSelection]
    combined_odds: float = 1.50
    confidence_score: int = Field(ge=0, le=10, default=9)
    risk_level: str = "LOW"
    key_factors: List[str] = Field(default_factory=list)
    suggested_stake: float = 500.0
    recommended_action: str = "BET"
    booking_code: Optional[str] = None
    booking_url: Optional[str] = None

    @classmethod
    def from_dict_flexible(
        cls,
        data: dict,
        current_balance: float = 500.0,
        require_nba_totals: bool = False,
    ) -> "AIPrediction":
        """Robust parser handling LLM deviations, strict 2-leg enforcement, max 1.60 odds, and optional NBA Over/Under market checks."""
        raw_selections = data.get("selections", [])
        parsed_selections = [
            MatchSelection.from_dict_flexible(s if isinstance(s, dict) else {})
            for s in raw_selections
        ]

        # Calculate or round combined odds
        combined_odds = data.get("combined_odds")
        if not combined_odds:
            combined_odds = 1.0
            for s in parsed_selections:
                combined_odds *= s.odds
        combined_odds = round(float(combined_odds), 2)

        # Scale confidence score if LLM provided 1-100 instead of 0-10
        raw_conf = data.get("confidence_score", 9)
        try:
            conf = int(raw_conf)
            if conf > 10:
                conf = min(10, max(0, round(conf / 10)))
            else:
                conf = max(0, min(10, conf))
        except (ValueError, TypeError):
            conf = 9

        factors = data.get("key_factors", [])
        if isinstance(factors, str):
            factors = [factors]

        risk = str(data.get("risk_level", "LOW")).upper()
        title = data.get("title", "AI Recommended Pick")
        action = data.get("recommended_action", "BET")

        # Hard Programmatic Odds & Ticket Boundary Enforcement:
        # 1. Ticket structure: strictly EXACTLY 2 legs
        # 2. Individual leg odds: strictly between 1.200 and 1.600 (non of each odds per match should exceed 1.60)
        # 3. Combined ticket odds: strictly between 1.500 and 1.800
        # 4. Optional NBA Totals check: strictly Over/Under (incl. Overtime) or First Half Over/Under
        if action == "BET":
            for s in parsed_selections:
                if s.odds < 1.20:
                    action = "SKIP"
                    title = f"SKIP — Selection '{s.selection}' ({s.odds:.2f}) below 1.200 minimum threshold"
                    factors.append(f"Odds Filter Guard: Individual selection odds ({s.odds:.2f}) is below the strict 1.200 minimum.")
                    conf = 0
                    break
                elif s.odds > 1.60:
                    action = "SKIP"
                    title = f"SKIP — Selection '{s.selection}' ({s.odds:.2f}) exceeds 1.600 individual maximum threshold"
                    factors.append(f"Odds Filter Guard: Individual selection odds ({s.odds:.2f}) exceeds the strict 1.600 leg maximum.")
                    conf = 0
                    break

            if action == "BET" and len(parsed_selections) not in (1, 2):
                action = "SKIP"
                title = f"SKIP — Ticket has {len(parsed_selections)} leg(s); strictly 1 or 2 legs allowed"
                factors.append(f"Ticket Structure Guard: Strictly 1 or 2 legs allowed, found {len(parsed_selections)}.")
                conf = 0

            # If 1-leg solo ticket, verify odds are between 1.500 and 1.600 to satisfy compound target safely
            if action == "BET" and len(parsed_selections) == 1:
                solo_leg = parsed_selections[0]
                if solo_leg.odds < 1.50:
                    action = "SKIP"
                    title = f"SKIP — 1-leg solo pick has {solo_leg.odds:.2f} odds; minimum 1.500 required for single-leg tickets"
                    factors.append(f"Solo Leg Guard: Single-leg ticket odds ({solo_leg.odds:.2f}) must be at least 1.500 to meet the daily compound target.")
                    conf = 0

            if action == "BET" and require_nba_totals:
                import re
                forbidden_mkts = [
                    "spread", "handicap", "1x2", "double chance",
                    "dnb", "draw no bet", "both teams to score", "btts", "goal", "corner", "card"
                ]
                for s in parsed_selections:
                    # Enforce basketball
                    s_sport = (s.sport or "").lower()
                    if any(fb in s_sport for fb in ["foot", "socc"]):
                        action = "SKIP"
                        title = "SKIP — Sport must be strictly NBA Basketball"
                        factors.append(f"Sport Guard: Football/soccer selection '{s.fixture}' rejected. NBA only.")
                        conf = 0
                        break

                    mkt_lower = (s.market or "").lower()
                    sel_lower = (s.selection or "").lower()
                    text = f"{mkt_lower} {sel_lower}"
                    if any(f in mkt_lower for f in forbidden_mkts):
                        action = "SKIP"
                        title = f"SKIP — Market '{s.market}' not allowed; strictly Over/Under (incl. Overtime), First Half Over/Under, or Winner (incl. Overtime) [15-Up Early Payout] required"
                        factors.append(f"Market Guard: Prohibited market '{s.market}'. Only Over/Under (incl. Overtime), First Half Over/Under, and Winner (incl. Overtime) are permitted.")
                        conf = 0
                        break

                    is_valid_ou = any(k in text for k in ["over", "under", "total", "o/u"])
                    is_valid_win = any(k in text for k in ["winner", "moneyline", "to win", "ml"])
                    if not (is_valid_ou or is_valid_win):
                        action = "SKIP"
                        title = f"SKIP — Market '{s.market}' not allowed; strictly Over/Under (incl. Overtime), First Half Over/Under, or Winner (incl. Overtime) [15-Up Early Payout] required"
                        factors.append("Market Guard: Only Over/Under (incl. Overtime), First Half Over/Under, and Winner (incl. Overtime) with 15-Up Early Payout are permitted.")
                        conf = 0
                        break

            if action == "BET":
                if combined_odds < 1.50:
                    action = "SKIP"
                    title = f"SKIP — Combined odds ({combined_odds:.2f}) below 1.500 minimum target"
                    factors.append(f"Odds Filter Guard: Combined daily odds ({combined_odds:.2f}) must be at least 1.500.")
                    conf = 0
                elif combined_odds > 1.80:
                    action = "SKIP"
                    title = f"SKIP — Combined odds ({combined_odds:.2f}) exceeds 1.800 maximum ceiling"
                    factors.append(f"Odds Filter Guard: Combined daily odds ({combined_odds:.2f}) exceeds the strict 1.800 maximum.")
                    conf = 0

        return cls(
            title=title,
            selections=parsed_selections,
            combined_odds=combined_odds,
            confidence_score=conf,
            risk_level=risk,
            key_factors=factors,
            suggested_stake=current_balance,
            recommended_action=action,
            booking_code=data.get("booking_code") or data.get("shareCode"),
            booking_url=data.get("booking_url") or data.get("shareURL"),
        )


class BetRecord(BaseModel):
    id: Optional[int] = None
    day_number: int
    event_name: str
    market: str
    selection: str
    odds: float
    stake: float
    potential_return: float
    outcome: str = "PENDING"  # PENDING, WON, LOST, VOID
    profit_loss: Optional[float] = 0.0
    booking_code: Optional[str] = None
    booking_url: Optional[str] = None
    created_at: Optional[str] = None


class LedgerState(BaseModel):
    user_id: int
    current_day: int = 1
    current_balance: float = 500.0
    initial_stake: float = 500.0
    total_withdrawn: float = 0.0
    total_won_bets: int = 0
    total_lost_bets: int = 0
    current_streak: int = 0
    highest_streak: int = 0
    status: str = "ACTIVE"  # ACTIVE, PAUSED, COMPLETED
    updated_at: Optional[str] = None
