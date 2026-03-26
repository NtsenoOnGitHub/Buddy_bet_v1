"""User-facing withdrawal endpoints.

POST /wallet/withdrawals                  — create a withdrawal request
GET  /wallet/withdrawals                  — list the current user's withdrawals
GET  /wallet/withdrawals/{withdrawal_id}  — get a single withdrawal
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user, get_db
from app.models.user import User
from app.schemas.common import PageParams, PaginatedResponse
from app.schemas.funding import CreateWithdrawalRequest, WithdrawalResponse
from app.services.withdrawal_service import WithdrawalService

router = APIRouter()


@router.post(
    "/withdrawals",
    response_model=WithdrawalResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a withdrawal request",
    description=(
        "Submits a withdrawal request. If successful, the requested amount is "
        "immediately moved from available_balance to locked_balance — it is "
        "reserved and not usable until the withdrawal is rejected (released) "
        "or completed (debited). Requires authentication."
    ),
)
async def create_withdrawal(
    body: CreateWithdrawalRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> WithdrawalResponse:
    svc = WithdrawalService(db)
    withdrawal = await svc.create_withdrawal(
        user_id=current_user.id,
        amount=body.amount,
        destination_account=body.destination_account,
        currency=body.currency,
        destination_type=body.destination_type,
    )
    return WithdrawalResponse.model_validate(withdrawal)


@router.get(
    "/withdrawals",
    response_model=PaginatedResponse[WithdrawalResponse],
    status_code=status.HTTP_200_OK,
    summary="List my withdrawals",
    description="Returns the current user's withdrawal requests, newest first.",
)
async def list_withdrawals(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> PaginatedResponse[WithdrawalResponse]:
    svc = WithdrawalService(db)
    params = PageParams(page=page, page_size=page_size)
    items, total = await svc.list_withdrawals(current_user.id, params)
    return PaginatedResponse[WithdrawalResponse].create(
        items=[WithdrawalResponse.model_validate(w) for w in items],
        total=total,
        page=params.page,
        page_size=params.page_size,
    )


@router.get(
    "/withdrawals/{withdrawal_id}",
    response_model=WithdrawalResponse,
    status_code=status.HTTP_200_OK,
    summary="Get a withdrawal",
    description="Returns a single withdrawal. Users may only access their own withdrawals.",
)
async def get_withdrawal(
    withdrawal_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> WithdrawalResponse:
    svc = WithdrawalService(db)
    withdrawal = await svc.get_withdrawal(
        withdrawal_id, requesting_user_id=current_user.id
    )
    return WithdrawalResponse.model_validate(withdrawal)
