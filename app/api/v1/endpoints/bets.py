"""Bet endpoints.

ROUTING ORDER IS CRITICAL:
  Static routes (/open, /my) must be registered BEFORE the dynamic route
  (/{bet_id}) to prevent FastAPI from treating 'open' or 'my' as UUIDs.

GET  /bets/open          — paginated public feed of OPEN bets (auth required)
GET  /bets/my            — current user's bet history, optionally filtered by status
GET  /bets/{id}          — single bet detail with nested match
POST /bets               — create a new bet
POST /bets/{id}/accept   — accept an OPEN bet as User B
POST /bets/{id}/cancel   — cancel an OPEN bet (creator only)
"""

from __future__ import annotations

import uuid
from typing import Optional

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user, get_db
from app.models.enums import BetStatus
from app.models.user import User
from app.schemas.bet import AcceptBetRequest, BetListResponse, BetResponse, CreateBetRequest
from app.schemas.common import PageParams
from app.services.bet_service import BetService

router = APIRouter()


# ---------------------------------------------------------------------------
# Static routes — MUST appear before /{bet_id}
# ---------------------------------------------------------------------------

@router.get(
    "/open",
    response_model=BetListResponse,
    status_code=status.HTTP_200_OK,
    summary="List open bets (public feed)",
    description=(
        "Returns a paginated feed of OPEN bets that have not yet expired, "
        "newest first. Authentication is required. "
        "Each bet includes the associated match details."
    ),
)
async def get_open_bets(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> BetListResponse:
    service = BetService(db)
    params = PageParams(page=page, page_size=page_size)
    return await service.get_open_bets(params)


@router.get(
    "/my",
    response_model=BetListResponse,
    status_code=status.HTTP_200_OK,
    summary="Get current user's bet history",
    description=(
        "Returns all bets for the authenticated user (as creator or opponent), "
        "newest first. Use the optional `status` filter to show a single status "
        "tab (e.g. OPEN, MATCHED, SETTLED). "
        "Each bet includes the associated match details."
    ),
)
async def get_my_bets(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    status_filter: Optional[BetStatus] = Query(
        default=None,
        alias="status",
        description=(
            "Filter by bet status. "
            "Valid values: OPEN | MATCHED | PENDING_SETTLEMENT | SETTLED | "
            "CANCELLED | VOIDED | UNDER_REVIEW. Omit to return all statuses."
        ),
    ),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> BetListResponse:
    service = BetService(db)
    params = PageParams(page=page, page_size=page_size)
    return await service.get_user_bets(current_user.id, params, status=status_filter)


# ---------------------------------------------------------------------------
# Dynamic routes
# ---------------------------------------------------------------------------

@router.post(
    "",
    response_model=BetResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new bet",
    description=(
        "Creates a new OPEN bet and locks the creator's stake immediately. "
        "The match must be in 'scheduled' status and the kickoff cutoff must "
        "not have passed."
    ),
)
async def create_bet(
    body: CreateBetRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> BetResponse:
    service = BetService(db)
    return await service.create_bet(current_user, body)


@router.get(
    "/{bet_id}",
    response_model=BetResponse,
    status_code=status.HTTP_200_OK,
    summary="Get single bet detail",
    description=(
        "Returns full detail for a single bet by its ID, including the "
        "associated match, predictions, stake, settlement outcome, and all "
        "timestamps. Any authenticated user can retrieve any bet."
    ),
)
async def get_bet(
    bet_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> BetResponse:
    service = BetService(db)
    return await service.get_bet_by_id(bet_id)


@router.post(
    "/{bet_id}/accept",
    response_model=BetResponse,
    status_code=status.HTTP_200_OK,
    summary="Accept an open bet",
    description=(
        "Accepts an OPEN bet as User B. The opponent's prediction must differ "
        "from the creator's. Locks User B's stake. Uses SELECT FOR UPDATE to "
        "prevent race conditions."
    ),
)
async def accept_bet(
    bet_id: uuid.UUID,
    body: AcceptBetRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> BetResponse:
    service = BetService(db)
    return await service.accept_bet(current_user, bet_id, body)


@router.post(
    "/{bet_id}/cancel",
    response_model=BetResponse,
    status_code=status.HTTP_200_OK,
    summary="Cancel an open bet",
    description=(
        "Cancels an OPEN bet. Only the creator (User A) may cancel. "
        "Unlocks the creator's stake back to available_balance."
    ),
)
async def cancel_bet(
    bet_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> BetResponse:
    service = BetService(db)
    return await service.cancel_bet(current_user, bet_id)
