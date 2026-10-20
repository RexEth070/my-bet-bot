"""Pydantic Models and Data Schemas."""

from typing import List, Optional
from datetime import datetime
from pydantic import BaseModel, Field


class MatchSelection(BaseModel):
    fixture: str = Field(default="Match")
    sport: str = "football"
    market: str = "Moneyline"
    selection: str = Field(default="Selection")
    odds: float = 1.25
    commence_time: Optional[str] = None
    is_2up_eligible: bool = False
    early_payout_rule: Optional[str] = None

    @classmethod
    def from_dict_flexible(cls, data: dict) -> "MatchSelection":
        """Flexible constructor accepting LLM naming variations."""
        fixture = data.get("fixture") or data.get("match") or data.get("event") or "Match"
        sport = data.get("sport") or "football"
        market = data.get("market") or data.get("bet_type") or "Match Winner"
        selection = data.get("selection") or data.get("pick") or data.get("bet") or "To Win"
        try:
            odds = float(data.get("odds") or 1.25)
        except (ValueError, TypeError):
            odds = 1.25
        commence = data.get("commence_time") or data.get("time") or "Upcoming"
        
        # Check early payout rule (1-Up, 2-Up, or Basketball Lead)
        early_payout = data.get("early_payout_rule") or data.get("early_payout")
        combined_text = f"{market} {selection} {data.get('is_2up_eligible', '')} {data.get('is_1up_eligible', '')}".lower()
        if not early_payout:
            if "1up" in combined_text or "1-up" in combined_text:
                early_payout = "1-Up"
            elif "2up" in combined_text or "2-up" in combined_text or bool(data.get("is_2up_eligible")):
                early_payout = "2-Up"
            elif "15up" in combined_text or "15-up" in combined_text:
                early_payout = "15-Up"

        is_2up = bool(early_payout == "2-Up" or data.get("is_2up_eligible"))

        return cls(
            fixture=fixture,
            sport=sport,
            market=market,
            selection=selection,
            odds=odds,
            commence_time=commence,
            is_2up_eligible=is_2up,
            early_payout_rule=early_payout,
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
    def from_dict_flexible(cls, data: dict, current_balance: float = 500.0) -> "AIPrediction":
        """Robust parser handling LLM deviations and scoring ranges."""
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

        # Hard Programmatic Odds Boundary Enforcement:
        # 1. Individual leg odds: strictly between 1.200 and 1.590
        # 2. Combined ticket odds: strictly between 1.500 and 1.800
        if action == "BET" and parsed_selections:
            for s in parsed_selections:
                if s.odds < 1.20:
                    action = "SKIP"
                    title = f"SKIP — Selection '{s.selection}' ({s.odds:.2f}) below 1.200 minimum threshold"
                    factors.append(f"Odds Filter Guard: Individual selection odds ({s.odds:.2f}) is below the strict 1.200 minimum.")
                    conf = 0
                    break
                elif s.odds > 1.59:
                    action = "SKIP"
                    title = f"SKIP — Selection '{s.selection}' ({s.odds:.2f}) exceeds 1.590 individual maximum threshold"
                    factors.append(f"Odds Filter Guard: Individual selection odds ({s.odds:.2f}) exceeds the strict 1.590 leg maximum.")
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
