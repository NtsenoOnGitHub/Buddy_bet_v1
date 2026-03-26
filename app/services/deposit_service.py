"""Deposit service — manages the full deposit lifecycle.

State machine:
    pending ─────────────────┬─► completed  (admin completes — wallet credited)
    pending → processing ────┘
    pending / processing ────────► failed     (admin fails — no wallet change)
    pending ─────────────────────► cancelled  (reserved for future user-cancel)

Balance rule:
    Wallet available_balance is credited ONLY on transition to completed.
    All other transitions leave the wallet untouched.

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

from app.core.config import get_settings
from app.core.exceptions import ConflictError, ForbiddenError, NotFoundError, ValidationError
from app.models.deposit import DepositRequest
from app.models.enums import DepositStatus
from app.payments.payfast import build_checkout_params, build_checkout_url
from app.repositories.deposit_repository import DepositRepository
from app.repositories.wallet_repository import WalletRepository
from app.schemas.common import PageParams
from app.services.wallet_service import WalletService

logger = logging.getLogger(__name__)

# States from which a deposit can be completed or failed.
_COMPLETABLE = {DepositStatus.pending, DepositStatus.processing}
_FAILABLE = {DepositStatus.pending, DepositStatus.processing}
# Terminal states — no further transitions allowed.
_TERMINAL = {DepositStatus.completed, DepositStatus.failed, DepositStatus.cancelled}


class DepositService:
    """Manages deposit request lifecycle and wallet interactions."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db
        self._deposit_repo = DepositRepository(db)
        self._wallet_repo = WalletRepository(db)
        self._wallet_svc = WalletService(db)

    # -----------------------------------------------------------------------
    # Create
    # -----------------------------------------------------------------------

    async def create_deposit(
        self,
        user_id: uuid.UUID,
        amount: Decimal,
        currency: str = "ZAR",
        payment_provider: str | None = None,
        client_reference: str | None = None,
        notes: str | None = None,
    ) -> DepositRequest:
        """Create a new pending deposit request.

        The request enters pending status. Wallet is NOT credited yet.
        An admin (or future payment webhook) must call complete_deposit()
        to credit the funds.

        Args:
            user_id: The requesting user.
            amount: Positive Decimal amount.
            currency: ISO 4217 currency code (default ZAR).
            payment_provider: Optional provider name for future webhook routing.
            client_reference: Optional unique client idempotency key.
            notes: Optional admin/user note.

        Returns:
            The newly created DepositRequest (pending).

        Raises:
            ValidationError: amount is not positive.
            NotFoundError: User has no wallet.
            ConflictError: client_reference already in use.
        """
        if amount <= Decimal("0"):
            raise ValidationError("Deposit amount must be positive.")

        wallet = await self._wallet_repo.get_by_user_id_or_404(user_id)

        deposit = await self._deposit_repo.create(
            user_id=user_id,
            wallet_id=wallet.id,
            amount=amount,
            currency=currency,
            status=DepositStatus.pending,
            payment_provider=payment_provider,
            client_reference=client_reference,
            notes=notes,
        )

        logger.info(
            "deposit.created user=%s deposit=%s amount=%s",
            user_id,
            deposit.id,
            amount,
        )
        return deposit

    # -----------------------------------------------------------------------
    # Initiate via PayFast
    # -----------------------------------------------------------------------

    async def initiate_payfast_deposit(
        self,
        user_id: uuid.UUID,
        amount: Decimal,
        *,
        email_address: str | None = None,
        name_first: str | None = None,
        name_last: str | None = None,
    ) -> DepositRequest:
        """Create a pending deposit and build a signed PayFast checkout URL.

        Stores the checkout URL on the DepositRequest row so the frontend can
        retrieve it. The deposit status advances to processing after the user
        is redirected; wallet is credited only on ITN completion.

        Args:
            user_id: The requesting user.
            amount: Positive ZAR amount.
            email_address: Pre-fill buyer email on PayFast checkout.
            name_first: Pre-fill buyer first name.
            name_last: Pre-fill buyer last name.

        Returns:
            DepositRequest with checkout_url populated (status=pending).

        Raises:
            ValidationError: amount is out of configured bounds or PayFast is disabled.
            NotFoundError: User has no wallet.
        """
        settings = get_settings()
        if not settings.payfast_enabled:
            raise ValidationError("PayFast deposits are not enabled on this server.")
        if amount < settings.min_stake_amount:
            raise ValidationError(
                f"Minimum deposit amount is {settings.min_stake_amount} {settings.platform_currency}."
            )
        if amount > settings.max_stake_amount:
            raise ValidationError(
                f"Maximum deposit amount is {settings.max_stake_amount} {settings.platform_currency}."
            )

        # Create the pending record first so we have a deposit_id for the URL
        deposit = await self.create_deposit(
            user_id=user_id,
            amount=amount,
            currency=settings.platform_currency,
            payment_provider="payfast",
        )

        # Build signed PayFast checkout URL and store on the record
        params = build_checkout_params(
            deposit_id=str(deposit.id),
            amount=amount,
            email_address=email_address,
            name_first=name_first,
            name_last=name_last,
        )
        deposit.checkout_url = build_checkout_url(params)
        # Advance to processing — user is being redirected to PayFast
        deposit.status = DepositStatus.processing
        self._db.add(deposit)
        await self._db.flush()
        await self._db.refresh(deposit)

        logger.info(
            "deposit.payfast_initiated user=%s deposit=%s amount=%s",
            user_id,
            deposit.id,
            amount,
        )
        return deposit

    # -----------------------------------------------------------------------
    # Complete (admin / webhook)
    # -----------------------------------------------------------------------

    async def complete_deposit(
        self,
        deposit_id: uuid.UUID,
        provider_reference: str | None = None,
        notes: str | None = None,
    ) -> DepositRequest:
        """Complete a deposit — credit the wallet and mark status=completed.

        Safe to call by both the admin endpoint and a future payment webhook.
        Guards against double-processing via:
        - Status check (only pending/processing may be completed)
        - provider_reference uniqueness (DB constraint prevents duplicate
          webhook delivery from crediting twice)

        Args:
            deposit_id: The deposit to complete.
            provider_reference: External reference from the payment provider.
            notes: Optional completion note.

        Returns:
            Updated DepositRequest (completed).

        Raises:
            NotFoundError: Deposit does not exist.
            ConflictError: Deposit is already in a terminal state.
        """
        deposit = await self._deposit_repo.get_by_id_or_404(deposit_id)

        if deposit.status in _TERMINAL:
            raise ConflictError(
                f"Deposit {deposit_id} is already in terminal state "
                f"'{deposit.status.value}'. Cannot complete."
            )
        if deposit.status not in _COMPLETABLE:
            raise ConflictError(
                f"Deposit {deposit_id} cannot be completed from status "
                f"'{deposit.status.value}'."
            )

        # Credit the wallet first (SELECT FOR UPDATE inside wallet service)
        await self._wallet_svc.credit_deposit(
            user_id=deposit.user_id,
            amount=deposit.amount,
            deposit_id=deposit.id,
            notes=notes or f"Deposit {deposit_id} completed",
        )

        # Persist state change
        deposit.status = DepositStatus.completed
        deposit.completed_at = datetime.now(tz=timezone.utc)
        if provider_reference is not None:
            deposit.provider_reference = provider_reference
        if notes is not None:
            deposit.notes = notes
        self._db.add(deposit)
        await self._db.flush()
        await self._db.refresh(deposit)

        logger.info(
            "deposit.completed user=%s deposit=%s amount=%s",
            deposit.user_id,
            deposit_id,
            deposit.amount,
        )
        return deposit

    # -----------------------------------------------------------------------
    # Fail (admin / webhook)
    # -----------------------------------------------------------------------

    async def fail_deposit(
        self,
        deposit_id: uuid.UUID,
        reason: str | None = None,
    ) -> DepositRequest:
        """Mark a deposit as failed — wallet is NOT affected.

        Args:
            deposit_id: The deposit to fail.
            reason: Optional failure reason stored in notes.

        Returns:
            Updated DepositRequest (failed).

        Raises:
            NotFoundError: Deposit does not exist.
            ConflictError: Deposit is already in a terminal state.
        """
        deposit = await self._deposit_repo.get_by_id_or_404(deposit_id)

        if deposit.status in _TERMINAL:
            raise ConflictError(
                f"Deposit {deposit_id} is already in terminal state "
                f"'{deposit.status.value}'. Cannot fail."
            )

        deposit.status = DepositStatus.failed
        deposit.failed_at = datetime.now(tz=timezone.utc)
        if reason:
            deposit.notes = reason
        self._db.add(deposit)
        await self._db.flush()
        await self._db.refresh(deposit)

        logger.info(
            "deposit.failed user=%s deposit=%s reason=%s",
            deposit.user_id,
            deposit_id,
            reason,
        )
        return deposit

    # -----------------------------------------------------------------------
    # Read
    # -----------------------------------------------------------------------

    async def get_deposit(
        self,
        deposit_id: uuid.UUID,
        requesting_user_id: uuid.UUID | None = None,
    ) -> DepositRequest:
        """Return a single deposit.

        If requesting_user_id is provided, enforces that the deposit belongs
        to that user (raises ForbiddenError otherwise).
        """
        deposit = await self._deposit_repo.get_by_id_or_404(deposit_id)
        if requesting_user_id is not None and deposit.user_id != requesting_user_id:
            raise ForbiddenError(
                "You do not have permission to view this deposit."
            )
        return deposit

    async def list_deposits(
        self,
        user_id: uuid.UUID,
        params: PageParams,
    ) -> Tuple[List[DepositRequest], int]:
        """Return paginated deposits for a user."""
        return await self._deposit_repo.get_by_user(user_id, params)

    async def list_all_deposits(
        self,
        params: PageParams,
        status: DepositStatus | None = None,
    ) -> Tuple[List[DepositRequest], int]:
        """Return paginated deposits across all users (admin only)."""
        return await self._deposit_repo.list_all(params, status=status)
