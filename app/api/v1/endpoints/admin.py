"""Admin endpoints — match result confirmation, manual settlement, bet voiding.

All routes require admin role (get_current_admin dependency).

POST /admin/matches/{match_id}/confirm-result
    Confirms the match result, transitions MATCHED bets to PENDING_SETTLEMENT,
    and runs SettlementService.settle_bet() for each — one transaction per bet.

POST /admin/bets/{bet_id}/settle
    Manually triggers settlement for a single PENDING_SETTLEMENT bet.

POST /admin/bets/{bet_id}/void
    Voids a bet (OPEN or MATCHED) and refunds all locked stakes.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_admin, get_db
from app.core.exceptions import SettlementIdempotencyError
from app.models.user import User
from app.schemas.admin import (
    ConfirmMatchResultRequest,
    ManualSettleBetResponse,
    SettlementSummaryResponse,
    VoidBetRequest,
    VoidBetResponse,
)
from app.services.admin_service import AdminService
from app.services.match_settlement_service import MatchSettlementService

router = APIRouter()


# ---------------------------------------------------------------------------
# Confirm match result + auto-settle
# ---------------------------------------------------------------------------

@router.post(
    "/matches/{match_id}/confirm-result",
    response_model=SettlementSummaryResponse,
    status_code=status.HTTP_200_OK,
    summary="Confirm match result and settle all associated bets",
    description=(
        "Sets the match outcome and scores, transitions all MATCHED bets for this "
        "match to PENDING_SETTLEMENT, then calls SettlementService.settle_bet() for "
        "each eligible bet. Returns a summary of how many bets were settled, already "
        "settled, or failed. Requires admin role."
    ),
)
async def confirm_match_result(
    match_id: uuid.UUID,
    body: ConfirmMatchResultRequest,
    db: AsyncSession = Depends(get_db),
    current_admin: User = Depends(get_current_admin),
) -> SettlementSummaryResponse:
    svc = MatchSettlementService(db)
    result = await svc.confirm_and_settle(
        match_id=match_id,
        outcome=body.outcome,
        home_score=body.home_score,
        away_score=body.away_score,
        confirmed_by=current_admin.id,
    )
    return SettlementSummaryResponse(
        match_id=result.match_id,
        outcome=result.outcome,
        bets_found=result.bets_found,
        bets_settled=result.bets_settled,
        bets_already_settled=result.bets_already_settled,
        bets_failed=result.bets_failed,
        failed_bet_ids=result.failed_bet_ids,
    )


# ---------------------------------------------------------------------------
# Manual single-bet settlement
# ---------------------------------------------------------------------------

@router.post(
    "/bets/{bet_id}/settle",
    response_model=ManualSettleBetResponse,
    status_code=status.HTTP_200_OK,
    summary="Manually trigger settlement for a single bet",
    description=(
        "Manually triggers SettlementService.settle_bet() for a bet that is in "
        "PENDING_SETTLEMENT status. Useful for retrying failed settlements or for "
        "bets missed by the automatic flow. Requires admin role."
    ),
)
async def manually_settle_bet(
    bet_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_admin: User = Depends(get_current_admin),
) -> ManualSettleBetResponse:
    svc = MatchSettlementService(db)
    await svc.settle_single_bet(bet_id)
    return ManualSettleBetResponse(
        bet_id=bet_id,
        message=f"Bet {bet_id} settled successfully.",
    )


# ---------------------------------------------------------------------------
# Manual bet void
# ---------------------------------------------------------------------------

@router.post(
    "/bets/{bet_id}/void",
    response_model=VoidBetResponse,
    status_code=status.HTTP_200_OK,
    summary="Void a bet and refund all locked stakes",
    description=(
        "Voids a bet in OPEN or MATCHED status. Refunds the creator's locked stake "
        "for OPEN bets; refunds both users' stakes for MATCHED bets. "
        "Writes a VOIDED bet_event with the admin actor. Requires admin role."
    ),
)
async def void_bet(
    bet_id: uuid.UUID,
    body: VoidBetRequest,
    db: AsyncSession = Depends(get_db),
    current_admin: User = Depends(get_current_admin),
) -> VoidBetResponse:
    svc = AdminService(db)
    refunded = await svc.void_bet(
        bet_id=bet_id,
        admin_user_id=current_admin.id,
        reason=body.reason,
    )
    return VoidBetResponse(
        bet_id=bet_id,
        refunded_user_ids=refunded,
        message=f"Bet {bet_id} voided. {len(refunded)} user(s) refunded.",
    )
