"""Admin funding management endpoints.

Deposit admin actions:
    GET  /admin/deposits                       — list all deposits (with status filter)
    POST /admin/deposits/{id}/complete         — complete deposit (credits wallet)
    POST /admin/deposits/{id}/fail             — fail deposit (no wallet change)
    POST /admin/deposits/{id}/verify           — reconcile: manually complete with known pf_payment_id

Withdrawal admin actions:
    GET  /admin/withdrawals                    — list all withdrawals (with status filter)
    POST /admin/withdrawals/{id}/approve       — approve pending withdrawal
    POST /admin/withdrawals/{id}/reject        — reject withdrawal (releases funds)
    POST /admin/withdrawals/{id}/complete      — complete withdrawal (debits locked)
    POST /admin/withdrawals/{id}/fail          — fail withdrawal (releases funds)

All routes require admin role.
"""

from __future__ import annotations

import uuid
from typing import Optional

from fastapi import APIRouter, Body, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_admin, get_db
from app.models.enums import DepositStatus, WithdrawalStatus
from app.models.user import User
from app.schemas.common import PageParams, PaginatedResponse
from app.schemas.funding import (
    AdminCompleteDepositRequest,
    AdminFailDepositRequest,
    AdminFailWithdrawalRequest,
    AdminRejectWithdrawalRequest,
    DepositResponse,
    WithdrawalResponse,
)
from app.services.deposit_service import DepositService
from app.services.withdrawal_service import WithdrawalService

router = APIRouter()


# ===========================================================================
# Deposits — admin
# ===========================================================================


@router.get(
    "/deposits",
    response_model=PaginatedResponse[DepositResponse],
    status_code=status.HTTP_200_OK,
    summary="List all deposits (admin)",
    description=(
        "Returns all deposit requests across all users. "
        "Optionally filter by status. Requires admin role."
    ),
)
async def admin_list_deposits(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    filter_status: Optional[DepositStatus] = Query(
        default=None, alias="status", description="Filter by deposit status."
    ),
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(get_current_admin),
) -> PaginatedResponse[DepositResponse]:
    svc = DepositService(db)
    params = PageParams(page=page, page_size=page_size)
    items, total = await svc.list_all_deposits(params, status=filter_status)
    return PaginatedResponse[DepositResponse].create(
        items=[DepositResponse.model_validate(d) for d in items],
        total=total,
        page=params.page,
        page_size=params.page_size,
    )


@router.post(
    "/deposits/{deposit_id}/complete",
    response_model=DepositResponse,
    status_code=status.HTTP_200_OK,
    summary="Complete a deposit (admin)",
    description=(
        "Marks a pending/processing deposit as completed and credits the user's "
        "available_balance. Idempotency: re-calling on a completed deposit "
        "raises 409. Requires admin role."
    ),
)
async def admin_complete_deposit(
    deposit_id: uuid.UUID,
    body: AdminCompleteDepositRequest,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(get_current_admin),
) -> DepositResponse:
    svc = DepositService(db)
    deposit = await svc.complete_deposit(
        deposit_id=deposit_id,
        provider_reference=body.provider_reference,
        notes=body.notes,
    )
    return DepositResponse.model_validate(deposit)


@router.post(
    "/deposits/{deposit_id}/fail",
    response_model=DepositResponse,
    status_code=status.HTTP_200_OK,
    summary="Fail a deposit (admin)",
    description=(
        "Marks a pending/processing deposit as failed. "
        "Wallet balance is not affected. Requires admin role."
    ),
)
async def admin_fail_deposit(
    deposit_id: uuid.UUID,
    body: AdminFailDepositRequest,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(get_current_admin),
) -> DepositResponse:
    svc = DepositService(db)
    deposit = await svc.fail_deposit(deposit_id=deposit_id, reason=body.reason)
    return DepositResponse.model_validate(deposit)


@router.post(
    "/deposits/{deposit_id}/verify",
    response_model=DepositResponse,
    status_code=status.HTTP_200_OK,
    summary="Reconcile deposit with PayFast reference (admin)",
    description=(
        "Reconciliation helper: manually completes a deposit using a known "
        "pf_payment_id from the PayFast dashboard. Use when the ITN was missed "
        "or disputed. Follows the same complete_deposit() path as webhooks — "
        "wallet is credited, ledger entry written, status becomes completed. "
        "Requires admin role."
    ),
)
async def admin_verify_deposit(
    deposit_id: uuid.UUID,
    pf_payment_id: str = Body(..., embed=True, description="pf_payment_id from PayFast dashboard"),
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(get_current_admin),
) -> DepositResponse:
    svc = DepositService(db)
    deposit = await svc.complete_deposit(
        deposit_id=deposit_id,
        provider_reference=pf_payment_id,
        notes="Admin reconciliation — manual verify",
    )
    return DepositResponse.model_validate(deposit)


# ===========================================================================
# Withdrawals — admin
# ===========================================================================


@router.get(
    "/withdrawals",
    response_model=PaginatedResponse[WithdrawalResponse],
    status_code=status.HTTP_200_OK,
    summary="List all withdrawals (admin)",
    description=(
        "Returns all withdrawal requests across all users. "
        "Optionally filter by status. Requires admin role."
    ),
)
async def admin_list_withdrawals(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    filter_status: Optional[WithdrawalStatus] = Query(
        default=None, alias="status", description="Filter by withdrawal status."
    ),
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(get_current_admin),
) -> PaginatedResponse[WithdrawalResponse]:
    svc = WithdrawalService(db)
    params = PageParams(page=page, page_size=page_size)
    items, total = await svc.list_all_withdrawals(params, status=filter_status)
    return PaginatedResponse[WithdrawalResponse].create(
        items=[WithdrawalResponse.model_validate(w) for w in items],
        total=total,
        page=params.page,
        page_size=params.page_size,
    )


@router.post(
    "/withdrawals/{withdrawal_id}/approve",
    response_model=WithdrawalResponse,
    status_code=status.HTTP_200_OK,
    summary="Approve a withdrawal (admin)",
    description=(
        "Transitions a pending withdrawal to approved. "
        "No balance movement at this step — funds remain held. "
        "Requires admin role."
    ),
)
async def admin_approve_withdrawal(
    withdrawal_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(get_current_admin),
) -> WithdrawalResponse:
    svc = WithdrawalService(db)
    withdrawal = await svc.approve_withdrawal(withdrawal_id)
    return WithdrawalResponse.model_validate(withdrawal)


@router.post(
    "/withdrawals/{withdrawal_id}/reject",
    response_model=WithdrawalResponse,
    status_code=status.HTTP_200_OK,
    summary="Reject a withdrawal (admin)",
    description=(
        "Rejects a pending or approved withdrawal. "
        "Releases held funds back to the user's available_balance. "
        "Requires admin role."
    ),
)
async def admin_reject_withdrawal(
    withdrawal_id: uuid.UUID,
    body: AdminRejectWithdrawalRequest,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(get_current_admin),
) -> WithdrawalResponse:
    svc = WithdrawalService(db)
    withdrawal = await svc.reject_withdrawal(withdrawal_id, reason=body.reason)
    return WithdrawalResponse.model_validate(withdrawal)


@router.post(
    "/withdrawals/{withdrawal_id}/complete",
    response_model=WithdrawalResponse,
    status_code=status.HTTP_200_OK,
    summary="Complete a withdrawal (admin)",
    description=(
        "Finalises an approved/processing withdrawal — debits the held amount "
        "from locked_balance permanently. Requires admin role."
    ),
)
async def admin_complete_withdrawal(
    withdrawal_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(get_current_admin),
) -> WithdrawalResponse:
    svc = WithdrawalService(db)
    withdrawal = await svc.complete_withdrawal(withdrawal_id)
    return WithdrawalResponse.model_validate(withdrawal)


@router.post(
    "/withdrawals/{withdrawal_id}/fail",
    response_model=WithdrawalResponse,
    status_code=status.HTTP_200_OK,
    summary="Fail a withdrawal (admin)",
    description=(
        "Marks a withdrawal as failed and releases held funds back to "
        "available_balance. Requires admin role."
    ),
)
async def admin_fail_withdrawal(
    withdrawal_id: uuid.UUID,
    body: AdminFailWithdrawalRequest,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(get_current_admin),
) -> WithdrawalResponse:
    svc = WithdrawalService(db)
    withdrawal = await svc.fail_withdrawal(withdrawal_id, reason=body.reason)
    return WithdrawalResponse.model_validate(withdrawal)
