"""Request and response schemas for admin endpoints."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Dict, List, Optional

from pydantic import BaseModel, Field

from app.models.enums import FootballOutcome


class ConfirmMatchResultRequest(BaseModel):
    """Body for POST /admin/matches/{match_id}/confirm-result."""

    outcome: FootballOutcome = Field(
        ...,
        description="Confirmed match outcome (home_win | away_win | draw).",
    )
    home_score: int = Field(..., ge=0, description="Final home team score.")
    away_score: int = Field(..., ge=0, description="Final away team score.")


class SettlementSummaryResponse(BaseModel):
    """Response for POST /admin/matches/{match_id}/confirm-result."""

    match_id: uuid.UUID
    outcome: str
    bets_found: int
    bets_settled: int
    bets_already_settled: int
    bets_failed: int
    failed_bet_ids: List[uuid.UUID]
    failure_reasons: Dict[str, str] = Field(
        default_factory=dict,
        description="Maps bet_id (string UUID) to the error message for each failed settlement.",
    )


class ManualSettleBetResponse(BaseModel):
    """Response for POST /admin/bets/{bet_id}/settle."""

    bet_id: uuid.UUID
    message: str
    settlement_outcome: Optional[str] = None
    winner_id: Optional[uuid.UUID] = None
    payout_amount: Optional[str] = None
    platform_fee: Optional[str] = None


class VoidBetRequest(BaseModel):
    """Body for POST /admin/bets/{bet_id}/void."""

    reason: str = Field(
        ...,
        min_length=1,
        max_length=500,
        description="Required admin reason. Recorded verbatim in the audit trail.",
    )


class VoidBetResponse(BaseModel):
    """Response for POST /admin/bets/{bet_id}/void."""

    bet_id: uuid.UUID
    refunded_user_ids: List[uuid.UUID]
    message: str


class PendingSettlementItem(BaseModel):
    """Summary of a single bet stuck in PENDING_SETTLEMENT status."""

    id: uuid.UUID
    match_id: uuid.UUID
    creator_id: uuid.UUID
    opponent_id: Optional[uuid.UUID] = None
    stake_amount: str
    currency: str
    updated_at: Optional[datetime] = None


class PendingSettlementListResponse(BaseModel):
    """Response for GET /admin/bets/pending."""

    items: List[PendingSettlementItem]
    total: int
