"""Request and response schemas for admin endpoints."""

from __future__ import annotations

import uuid
from typing import List, Optional

from pydantic import BaseModel, Field

from app.models.enums import FootballOutcome


class ConfirmMatchResultRequest(BaseModel):
    """Body for POST /admin/matches/{match_id}/confirm-result."""

    outcome: FootballOutcome = Field(
        ...,
        description="Confirmed match outcome (home_win | away_win | draw).",
    )
    home_score: int = Field(
        ...,
        ge=0,
        description="Final home team score.",
    )
    away_score: int = Field(
        ...,
        ge=0,
        description="Final away team score.",
    )


class SettlementSummaryResponse(BaseModel):
    """Response for POST /admin/matches/{match_id}/confirm-result."""

    match_id: uuid.UUID
    outcome: str
    bets_found: int
    bets_settled: int
    bets_already_settled: int
    bets_failed: int
    failed_bet_ids: List[uuid.UUID]


class ManualSettleBetResponse(BaseModel):
    """Response for POST /admin/bets/{bet_id}/settle."""

    bet_id: uuid.UUID
    message: str


class VoidBetRequest(BaseModel):
    """Body for POST /admin/bets/{bet_id}/void."""

    reason: Optional[str] = Field(
        default=None,
        max_length=500,
        description="Optional admin note recorded in the audit trail.",
    )


class VoidBetResponse(BaseModel):
    """Response for POST /admin/bets/{bet_id}/void."""

    bet_id: uuid.UUID
    refunded_user_ids: List[uuid.UUID]
    message: str
