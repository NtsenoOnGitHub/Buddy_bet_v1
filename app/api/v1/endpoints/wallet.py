"""Wallet endpoints.

GET /wallet              — current user's wallet balances (available, locked, total)
GET /wallet/transactions — paginated ledger history for the current user
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user, get_db
from app.models.user import User
from app.schemas.common import PageParams, PaginatedResponse
from app.schemas.wallet import LedgerEntryResponse, WalletResponse
from app.services.wallet_service import WalletService

router = APIRouter()


@router.get(
    "",
    response_model=WalletResponse,
    status_code=status.HTTP_200_OK,
    summary="Get wallet balances",
    description=(
        "Returns the authenticated user's wallet: available_balance, locked_balance, "
        "and the computed total_balance (= available + locked). Currency included."
    ),
)
async def get_wallet(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> WalletResponse:
    service = WalletService(db)
    return await service.get_wallet(current_user.id)


@router.get(
    "/transactions",
    response_model=PaginatedResponse[LedgerEntryResponse],
    status_code=status.HTTP_200_OK,
    summary="Get transaction history",
    description=(
        "Returns the authenticated user's paginated ledger history — "
        "every wallet balance change with amounts, directions, and balance snapshots."
    ),
)
async def get_transactions(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> PaginatedResponse[LedgerEntryResponse]:
    from app.repositories.ledger_repository import LedgerRepository
    repo = LedgerRepository(db)
    params = PageParams(page=page, page_size=page_size)
    items, total = await repo.get_user_history(current_user.id, params)
    return PaginatedResponse[LedgerEntryResponse].create(
        items=[LedgerEntryResponse.model_validate(e) for e in items],
        total=total,
        page=params.page,
        page_size=params.page_size,
    )
