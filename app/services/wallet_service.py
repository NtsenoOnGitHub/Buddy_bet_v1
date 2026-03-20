"""Wallet service — atomic balance mutation operations.

Every method:
1. Acquires a SELECT FOR UPDATE lock on the wallet row.
2. Validates the operation (e.g. sufficient funds).
3. Computes the new balance values using Decimal arithmetic (never float).
4. Calls wallet_repository.update_balances() to persist and increment version.
5. Calls ledger_service.write_*() to write the paired immutable ledger entries.

All steps execute in the SAME database transaction. Callers own the transaction
— this service does NOT commit or rollback.

The API layer must NEVER call this service directly. Only BetService and
SettlementService should call WalletService.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import InsufficientFundsError, NotFoundError
from app.models.wallet import Wallet
from app.repositories.wallet_repository import WalletRepository
from app.schemas.wallet import WalletResponse
from app.services.ledger_service import LedgerService
from app.utils.decimal_utils import safe_add, safe_subtract, verify_non_negative


class WalletService:
    """Atomic wallet balance mutations with paired ledger entries."""

    def __init__(self, db: AsyncSession) -> None:
        self._wallet_repo = WalletRepository(db)
        self._ledger = LedgerService(db)

    # -----------------------------------------------------------------------
    # Read
    # -----------------------------------------------------------------------

    async def get_wallet(self, user_id: uuid.UUID) -> WalletResponse:
        """Return the wallet for a user (read-only, no lock).

        Raises NotFoundError if the wallet does not exist.
        """
        wallet = await self._wallet_repo.get_by_user_id(user_id)
        if wallet is None:
            raise NotFoundError(f"Wallet not found for user_id={user_id}.")
        return WalletResponse.model_validate(wallet)

    # -----------------------------------------------------------------------
    # Stake Lock — available → locked (bet creation / acceptance)
    # -----------------------------------------------------------------------

    async def lock_stake(
        self,
        user_id: uuid.UUID,
        amount: Decimal,
        bet_id: uuid.UUID,
        notes: str | None = None,
    ) -> Wallet:
        """Move `amount` from available_balance to locked_balance.

        Validates that the user has sufficient available balance before locking.
        Writes a paired STAKE_LOCK ledger entry.

        Args:
            user_id: The user whose wallet to lock against.
            amount: The positive Decimal amount to lock.
            bet_id: The bet that generated this lock (used as reference_id).
            notes: Optional ledger note.

        Returns:
            The updated Wallet instance.

        Raises:
            InsufficientFundsError: If available_balance < amount.
            NotFoundError: If the wallet does not exist.
        """
        wallet = await self._wallet_repo.get_by_user_id_for_update(user_id)

        if wallet.available_balance < amount:
            raise InsufficientFundsError(
                f"Insufficient available balance. "
                f"Required: {amount}, Available: {wallet.available_balance}."
            )

        new_available = safe_subtract(wallet.available_balance, amount)
        new_locked = safe_add(wallet.locked_balance, amount)

        verify_non_negative(new_available, "available_balance")
        verify_non_negative(new_locked, "locked_balance")

        wallet = await self._wallet_repo.update_balances(
            wallet,
            available_balance=new_available,
            locked_balance=new_locked,
        )

        await self._ledger.write_stake_lock(wallet, amount, bet_id, notes)
        return wallet

    # -----------------------------------------------------------------------
    # Stake Unlock — locked → available (bet cancellation)
    # -----------------------------------------------------------------------

    async def unlock_stake(
        self,
        user_id: uuid.UUID,
        amount: Decimal,
        bet_id: uuid.UUID,
        notes: str | None = None,
    ) -> Wallet:
        """Move `amount` from locked_balance back to available_balance.

        Writes a paired STAKE_UNLOCK ledger entry.

        Args:
            user_id: The user whose wallet to unlock.
            amount: The positive Decimal amount to unlock.
            bet_id: The bet being cancelled (used as reference_id).
            notes: Optional ledger note.

        Returns:
            The updated Wallet instance.
        """
        wallet = await self._wallet_repo.get_by_user_id_for_update(user_id)

        new_locked = safe_subtract(wallet.locked_balance, amount)
        new_available = safe_add(wallet.available_balance, amount)

        verify_non_negative(new_locked, "locked_balance")
        verify_non_negative(new_available, "available_balance")

        wallet = await self._wallet_repo.update_balances(
            wallet,
            available_balance=new_available,
            locked_balance=new_locked,
        )

        await self._ledger.write_stake_unlock(wallet, amount, bet_id, notes)
        return wallet

    # -----------------------------------------------------------------------
    # Void Refund — locked → available (bet voided)
    # -----------------------------------------------------------------------

    async def void_refund(
        self,
        user_id: uuid.UUID,
        amount: Decimal,
        bet_id: uuid.UUID,
        notes: str | None = None,
    ) -> Wallet:
        """Move `amount` from locked_balance to available_balance on a void.

        Equivalent to unlock_stake but writes VOID_REFUND ledger entries
        with a void reference_type for audit clarity.

        Args:
            user_id: The user receiving the void refund.
            amount: Stake amount to return (full stake, no fee).
            bet_id: The voided bet (used as reference_id).
            notes: Optional ledger note.

        Returns:
            The updated Wallet instance.
        """
        wallet = await self._wallet_repo.get_by_user_id_for_update(user_id)

        new_locked = safe_subtract(wallet.locked_balance, amount)
        new_available = safe_add(wallet.available_balance, amount)

        verify_non_negative(new_locked, "locked_balance")
        verify_non_negative(new_available, "available_balance")

        wallet = await self._wallet_repo.update_balances(
            wallet,
            available_balance=new_available,
            locked_balance=new_locked,
        )

        await self._ledger.write_void_refund(wallet, amount, bet_id, notes)
        return wallet

    # -----------------------------------------------------------------------
    # Credit Available — winner payout or direct credit
    # -----------------------------------------------------------------------

    async def credit_available(
        self,
        user_id: uuid.UUID,
        amount: Decimal,
        bet_id: uuid.UUID,
        notes: str | None = None,
    ) -> Wallet:
        """Credit `amount` directly to available_balance.

        Used during settlement to credit payout to winner's available balance.
        The caller (SettlementService) manages ledger entry writing for the
        full settlement sequence; this method only updates the balance.

        This is a raw balance updater — use via SettlementService which handles
        the full atomic settlement sequence including ledger entries.
        """
        wallet = await self._wallet_repo.get_by_user_id_for_update(user_id)

        new_available = safe_add(wallet.available_balance, amount)
        verify_non_negative(new_available, "available_balance")

        wallet = await self._wallet_repo.update_balances(
            wallet,
            available_balance=new_available,
        )
        return wallet

    # -----------------------------------------------------------------------
    # Internal: get wallet with lock (used by SettlementService)
    # -----------------------------------------------------------------------

    async def get_wallet_for_update(self, user_id: uuid.UUID) -> Wallet:
        """Fetch the wallet with SELECT FOR UPDATE (for settlement service)."""
        return await self._wallet_repo.get_by_user_id_for_update(user_id)

    async def apply_balance_update(
        self,
        wallet: Wallet,
        available_balance: Decimal | None = None,
        locked_balance: Decimal | None = None,
    ) -> Wallet:
        """Apply balance changes to an already-locked wallet row.

        Used by SettlementService which acquires its own locks before calling
        this. Increments version.
        """
        if available_balance is not None:
            verify_non_negative(available_balance, "available_balance")
        if locked_balance is not None:
            verify_non_negative(locked_balance, "locked_balance")

        return await self._wallet_repo.update_balances(
            wallet,
            available_balance=available_balance,
            locked_balance=locked_balance,
        )
