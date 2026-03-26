"""Withdrawal service — manages the full withdrawal lifecycle.

State machine:
    pending ──► approved ──► completed   (admin approves → completes)
    pending ──────────────► rejected     (admin rejects from pending)
    approved ─────────────► rejected     (admin rejects after approval)
    pending / approved ───► failed       (admin marks failed)

Balance rules:
    Creation:   available -= amount, locked += amount  (WITHDRAWAL_HOLD)
    Completion: locked -= amount                        (WITHDRAWAL final debit)
    Rejection:  locked -= amount, available += amount  (WITHDRAWAL_RELEASE)
    Failure:    locked -= amount, available += amount  (WITHDRAWAL_RELEASE)

No balance leaves the DB without a corresponding terminal state on the
withdrawal request. Rejection/failure always releases the hold.

Transaction model:
    get_db (dependency) owns commit/rollback.
    This service only calls flush().
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import List, Tuple

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, ForbiddenError, ValidationError
from app.models.enums import WithdrawalStatus
from app.models.withdrawal import WithdrawalRequest
from app.repositories.wallet_repository import WalletRepository
from app.repositories.withdrawal_repository import WithdrawalRepository
from app.schemas.common import PageParams
from app.services.wallet_service import WalletService

logger = logging.getLogger(__name__)

# Valid source statuses for each transition
_APPROVABLE = {WithdrawalStatus.pending}
_COMPLETABLE = {WithdrawalStatus.approved, WithdrawalStatus.processing}
_REJECTABLE = {WithdrawalStatus.pending, WithdrawalStatus.approved}
_FAILABLE = {
    WithdrawalStatus.pending,
    WithdrawalStatus.approved,
    WithdrawalStatus.processing,
}
_TERMINAL = {
    WithdrawalStatus.completed,
    WithdrawalStatus.failed,
    WithdrawalStatus.rejected,
}
# States where a hold exists in locked_balance (must release on rejection/failure)
_HOLD_STATES = {
    WithdrawalStatus.pending,
    WithdrawalStatus.approved,
    WithdrawalStatus.processing,
}


class WithdrawalService:
    """Manages withdrawal request lifecycle and wallet interactions."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db
        self._withdrawal_repo = WithdrawalRepository(db)
        self._wallet_repo = WalletRepository(db)
        self._wallet_svc = WalletService(db)

    # -----------------------------------------------------------------------
    # Create
    # -----------------------------------------------------------------------

    async def create_withdrawal(
        self,
        user_id: uuid.UUID,
        amount: Decimal,
        destination_account: str,
        currency: str = "ZAR",
        destination_type: str | None = None,
    ) -> WithdrawalRequest:
        """Submit a withdrawal request.

        Validates sufficient available_balance, moves funds from available to
        locked (WITHDRAWAL_HOLD), and creates a pending withdrawal request.

        Args:
            user_id: The requesting user.
            amount: Positive Decimal to withdraw.
            destination_account: Bank account / mobile number for payout.
            currency: Currency code (default ZAR).
            destination_type: e.g. "bank_account", "mobile_money".

        Returns:
            Newly created WithdrawalRequest (pending, funds held).

        Raises:
            ValidationError: amount is not positive.
            InsufficientFundsError: available_balance < amount.
            NotFoundError: User has no wallet.
        """
        if amount <= Decimal("0"):
            raise ValidationError("Withdrawal amount must be positive.")

        wallet = await self._wallet_repo.get_by_user_id_or_404(user_id)

        # Create the request record first so we have its ID for the ledger.
        withdrawal = await self._withdrawal_repo.create(
            user_id=user_id,
            wallet_id=wallet.id,
            amount=amount,
            currency=currency,
            status=WithdrawalStatus.pending,
            destination_account=destination_account,
            destination_type=destination_type,
        )

        # Hold funds — raises InsufficientFundsError if balance insufficient.
        await self._wallet_svc.hold_withdrawal(
            user_id=user_id,
            amount=amount,
            withdrawal_id=withdrawal.id,
            notes=f"Withdrawal {withdrawal.id} hold on request creation",
        )

        logger.info(
            "withdrawal.created user=%s withdrawal=%s amount=%s",
            user_id,
            withdrawal.id,
            amount,
        )
        return withdrawal

    # -----------------------------------------------------------------------
    # Approve (admin)
    # -----------------------------------------------------------------------

    async def approve_withdrawal(self, withdrawal_id: uuid.UUID) -> WithdrawalRequest:
        """Approve a pending withdrawal — status changes to approved.

        No balance movement at this step. Funds remain held in locked.

        Raises:
            NotFoundError: Withdrawal does not exist.
            ConflictError: Withdrawal is not in pending status.
        """
        withdrawal = await self._withdrawal_repo.get_by_id_or_404(withdrawal_id)
        self._assert_transition(withdrawal, _APPROVABLE, "approve")

        withdrawal.status = WithdrawalStatus.approved
        withdrawal.approved_at = datetime.now(tz=timezone.utc)
        self._db.add(withdrawal)
        await self._db.flush()
        await self._db.refresh(withdrawal)

        logger.info("withdrawal.approved withdrawal=%s", withdrawal_id)
        return withdrawal

    # -----------------------------------------------------------------------
    # Complete (admin)
    # -----------------------------------------------------------------------

    async def complete_withdrawal(self, withdrawal_id: uuid.UUID) -> WithdrawalRequest:
        """Complete a withdrawal — debit locked balance, funds leave the platform.

        Raises:
            NotFoundError: Withdrawal does not exist.
            ConflictError: Withdrawal is not in approved/processing status.
        """
        withdrawal = await self._withdrawal_repo.get_by_id_or_404(withdrawal_id)
        self._assert_transition(withdrawal, _COMPLETABLE, "complete")

        # Final debit: locked -= amount
        await self._wallet_svc.finalize_withdrawal_debit(
            user_id=withdrawal.user_id,
            amount=withdrawal.amount,
            withdrawal_id=withdrawal.id,
            notes=f"Withdrawal {withdrawal_id} completed — funds debited",
        )

        withdrawal.status = WithdrawalStatus.completed
        withdrawal.completed_at = datetime.now(tz=timezone.utc)
        self._db.add(withdrawal)
        await self._db.flush()
        await self._db.refresh(withdrawal)

        logger.info("withdrawal.completed withdrawal=%s", withdrawal_id)
        return withdrawal

    # -----------------------------------------------------------------------
    # Reject (admin)
    # -----------------------------------------------------------------------

    async def reject_withdrawal(
        self,
        withdrawal_id: uuid.UUID,
        reason: str | None = None,
    ) -> WithdrawalRequest:
        """Reject a withdrawal — release held funds back to available.

        Valid from pending or approved.

        Raises:
            NotFoundError: Withdrawal does not exist.
            ConflictError: Withdrawal is not in a rejectable status.
        """
        withdrawal = await self._withdrawal_repo.get_by_id_or_404(withdrawal_id)
        self._assert_transition(withdrawal, _REJECTABLE, "reject")

        # Release held funds: locked → available
        await self._wallet_svc.release_withdrawal_hold(
            user_id=withdrawal.user_id,
            amount=withdrawal.amount,
            withdrawal_id=withdrawal.id,
            notes=f"Withdrawal {withdrawal_id} rejected — funds released",
        )

        withdrawal.status = WithdrawalStatus.rejected
        withdrawal.rejection_reason = reason
        self._db.add(withdrawal)
        await self._db.flush()
        await self._db.refresh(withdrawal)

        logger.info(
            "withdrawal.rejected withdrawal=%s reason=%s", withdrawal_id, reason
        )
        return withdrawal

    # -----------------------------------------------------------------------
    # Fail (admin)
    # -----------------------------------------------------------------------

    async def fail_withdrawal(
        self,
        withdrawal_id: uuid.UUID,
        reason: str | None = None,
    ) -> WithdrawalRequest:
        """Mark a withdrawal as failed — release held funds back to available.

        Valid from pending, approved, or processing.

        Raises:
            NotFoundError: Withdrawal does not exist.
            ConflictError: Withdrawal is already in a terminal state.
        """
        withdrawal = await self._withdrawal_repo.get_by_id_or_404(withdrawal_id)
        self._assert_transition(withdrawal, _FAILABLE, "fail")

        # Release held funds if they exist (all non-terminal states hold funds)
        if withdrawal.status in _HOLD_STATES:
            await self._wallet_svc.release_withdrawal_hold(
                user_id=withdrawal.user_id,
                amount=withdrawal.amount,
                withdrawal_id=withdrawal.id,
                notes=f"Withdrawal {withdrawal_id} failed — funds released",
            )

        withdrawal.status = WithdrawalStatus.failed
        withdrawal.failed_at = datetime.now(tz=timezone.utc)
        withdrawal.rejection_reason = reason
        self._db.add(withdrawal)
        await self._db.flush()
        await self._db.refresh(withdrawal)

        logger.info(
            "withdrawal.failed withdrawal=%s reason=%s", withdrawal_id, reason
        )
        return withdrawal

    # -----------------------------------------------------------------------
    # Read
    # -----------------------------------------------------------------------

    async def get_withdrawal(
        self,
        withdrawal_id: uuid.UUID,
        requesting_user_id: uuid.UUID | None = None,
    ) -> WithdrawalRequest:
        """Return a single withdrawal.

        If requesting_user_id is provided, enforces ownership (ForbiddenError).
        """
        withdrawal = await self._withdrawal_repo.get_by_id_or_404(withdrawal_id)
        if (
            requesting_user_id is not None
            and withdrawal.user_id != requesting_user_id
        ):
            raise ForbiddenError(
                "You do not have permission to view this withdrawal."
            )
        return withdrawal

    async def list_withdrawals(
        self,
        user_id: uuid.UUID,
        params: PageParams,
    ) -> Tuple[List[WithdrawalRequest], int]:
        """Return paginated withdrawals for a user."""
        return await self._withdrawal_repo.get_by_user(user_id, params)

    async def list_all_withdrawals(
        self,
        params: PageParams,
        status: WithdrawalStatus | None = None,
    ) -> Tuple[List[WithdrawalRequest], int]:
        """Return paginated withdrawals across all users (admin only)."""
        return await self._withdrawal_repo.list_all(params, status=status)

    # -----------------------------------------------------------------------
    # Internal helpers
    # -----------------------------------------------------------------------

    @staticmethod
    def _assert_transition(
        withdrawal: WithdrawalRequest,
        valid_from: set,
        action: str,
    ) -> None:
        """Raise ConflictError if the withdrawal is not in a valid source state."""
        if withdrawal.status in _TERMINAL:
            raise ConflictError(
                f"Withdrawal {withdrawal.id} is already in terminal state "
                f"'{withdrawal.status.value}'. Cannot {action}."
            )
        if withdrawal.status not in valid_from:
            valid_labels = ", ".join(s.value for s in valid_from)
            raise ConflictError(
                f"Cannot {action} withdrawal {withdrawal.id} from status "
                f"'{withdrawal.status.value}'. Valid source statuses: {valid_labels}."
            )
