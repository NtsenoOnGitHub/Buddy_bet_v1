"""User-facing deposit endpoints.

POST /wallet/deposits/initiate     — initiate a PayFast deposit (returns checkout URL)
POST /wallet/deposits              — create a manual deposit request (admin-completed)
GET  /wallet/deposits              — list the current user's deposits
GET  /wallet/deposits/{deposit_id} — get a single deposit
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user, get_db
from app.models.user import User
from app.schemas.common import PageParams, PaginatedResponse
from app.schemas.funding import (
    CreateDepositRequest,
    DepositResponse,
    InitiateDepositRequest,
    InitiateDepositResponse,
)
from app.services.deposit_service import DepositService

router = APIRouter()


@router.post(
    "/deposits/initiate",
    response_model=InitiateDepositResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Initiate a PayFast deposit",
    description=(
        "Creates a pending deposit, builds a signed PayFast checkout URL, and "
        "returns the URL for the frontend to redirect the user. "
        "Wallet is NOT credited at this point — credit happens only after the "
        "payment provider posts a verified ITN webhook. "
        "Requires authentication."
    ),
)
async def initiate_deposit(
    body: InitiateDepositRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> InitiateDepositResponse:
    svc = DepositService(db)
    deposit = await svc.initiate_payfast_deposit(
        user_id=current_user.id,
        amount=body.amount,
        email_address=body.email_address,
        name_first=body.name_first,
        name_last=body.name_last,
    )
    return InitiateDepositResponse(
        deposit_id=deposit.id,
        checkout_url=deposit.checkout_url or "",
        status=deposit.status,
    )


@router.post(
    "/deposits",
    response_model=DepositResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a deposit request",
    description=(
        "Creates a pending deposit request. Wallet balance is NOT credited yet — "
        "an admin must complete the deposit (or a future payment webhook will). "
        "Requires authentication."
    ),
)
async def create_deposit(
    body: CreateDepositRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> DepositResponse:
    svc = DepositService(db)
    deposit = await svc.create_deposit(
        user_id=current_user.id,
        amount=body.amount,
        currency=body.currency,
        payment_provider=body.payment_provider,
        client_reference=body.client_reference,
        notes=body.notes,
    )
    return DepositResponse.model_validate(deposit)


@router.get(
    "/deposits",
    response_model=PaginatedResponse[DepositResponse],
    status_code=status.HTTP_200_OK,
    summary="List my deposits",
    description="Returns the current user's deposit requests, newest first.",
)
async def list_deposits(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> PaginatedResponse[DepositResponse]:
    svc = DepositService(db)
    params = PageParams(page=page, page_size=page_size)
    items, total = await svc.list_deposits(current_user.id, params)
    return PaginatedResponse[DepositResponse].create(
        items=[DepositResponse.model_validate(d) for d in items],
        total=total,
        page=params.page,
        page_size=params.page_size,
    )


@router.get(
    "/deposits/{deposit_id}",
    response_model=DepositResponse,
    status_code=status.HTTP_200_OK,
    summary="Get a deposit",
    description="Returns a single deposit. Users may only access their own deposits.",
)
async def get_deposit(
    deposit_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> DepositResponse:
    svc = DepositService(db)
    deposit = await svc.get_deposit(deposit_id, requesting_user_id=current_user.id)
    return DepositResponse.model_validate(deposit)
