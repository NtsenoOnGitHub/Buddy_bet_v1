"""Bet schemas — create, accept, and response types.

All monetary values serialise as decimal strings (DecimalStr).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.enums import BetStatus, FootballOutcome, SettlementOutcome
from app.schemas.common import DecimalStr, PaginatedResponse
from app.schemas.match import MatchResponse


class CreateBetRequest(BaseModel):
    """Request body for POST /bets — create a new bet."""

    model_config = ConfigDict(str_strip_whitespace=True)

    match_id: uuid.UUID = Field(..., description="ID of the match to bet on.")
    creator_prediction: FootballOutcome = Field(
        ..., description="Creator's predicted outcome: home_win | away_win | draw."
    )
    stake_amount: DecimalStr = Field(
        ..., description="Stake amount in platform currency. Must be > 0."
    )

    @field_validator("stake_amount", mode="before")
    @classmethod
    def stake_must_be_positive(cls, v: object) -> object:
        try:
            amount = Decimal(str(v))
        except Exception:
            raise ValueError("stake_amount must be a valid decimal number.")
        if amount <= Decimal("0"):
            raise ValueError("stake_amount must be greater than zero.")
        return amount


class AcceptBetRequest(BaseModel):
    """Request body for POST /bets/{id}/accept — accept an existing OPEN bet."""

    model_config = ConfigDict(str_strip_whitespace=True)

    opponent_prediction: FootballOutcome = Field(
        ...,
        description=(
            "Opponent's predicted outcome. Must differ from the creator's prediction."
        ),
    )


class BetResponse(BaseModel):
    """Full bet detail response."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    match_id: uuid.UUID
    creator_id: uuid.UUID
    opponent_id: Optional[uuid.UUID] = None
    creator_prediction: FootballOutcome
    opponent_prediction: Optional[FootballOutcome] = None
    stake_amount: DecimalStr
    currency: str
    status: BetStatus
    settlement_outcome: Optional[SettlementOutcome] = None
    winner_id: Optional[uuid.UUID] = None
    platform_fee: Optional[DecimalStr] = None
    payout_amount: Optional[DecimalStr] = None
    applied_winner_fee_rate: Optional[DecimalStr] = None
    applied_no_winner_fee_rate: Optional[DecimalStr] = None
    expires_at: datetime
    settled_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    # Optional nested match — included when loaded via joined query
    match: Optional[MatchResponse] = None


class BetListResponse(PaginatedResponse[BetResponse]):
    """Paginated list of bets."""
    pass
