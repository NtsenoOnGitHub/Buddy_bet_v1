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

from app.core.exceptions import InsufficientFundsError, NotFoundError, ValidationError
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

    # -----------------------------------------------------------------------
    # lock_funds — generic available → locked (any reference type)
    # -----------------------------------------------------------------------

    async def lock_funds(
        self,
        user_id: uuid.UUID,
        amount: Decimal,
        reference_id: uuid.UUID,
        notes: str | None = None,
    ) -> Wallet:
        """Move ``amount`` from available_balance to locked_balance.

        Generic counterpart to lock_stake; use this when the locking operation
        is not directly tied to a bet (e.g. deposit hold, admin lock).

        Invariants guaranteed:
        - available_balance >= 0 after operation (raises InsufficientFundsError
          before touching the row if the pre-check fails; verify_non_negative
          provides a second guard after arithmetic).
        - locked_balance >= 0 after operation (always true when adding a
          positive amount to a non-negative value; verify_non_negative confirms).
        - Row is acquired with SELECT FOR UPDATE before any read of balances,
          preventing lost-update races under concurrent requests.
        - All writes (balance update + ledger entries) are flushed inside the
          caller's transaction — no partial state is ever committed.

        Args:
            user_id: Target user.
            amount: Positive Decimal to move from available → locked.
            reference_id: UUID of the entity causing the lock (bet, deposit, …).
            notes: Optional human-readable note stored on ledger entries.

        Returns:
            Updated Wallet (flushed, not committed).

        Raises:
            InsufficientFundsError: available_balance < amount.
            NotFoundError: Wallet does not exist for user_id.
            ValidationError: amount is not positive.
        """
        if amount <= Decimal("0"):
            raise ValidationError("lock_funds: amount must be positive.")

        wallet = await self._wallet_repo.get_by_user_id_for_update(user_id)

        if wallet.available_balance < amount:
            raise InsufficientFundsError(
                f"Insufficient available balance. "
                f"Required: {amount}, Available: {wallet.available_balance}."
            )

        new_available = safe_subtract(wallet.available_balance, amount)
        new_locked = safe_add(wallet.locked_balance, amount)

        # Second-level guards — protect against arithmetic edge-cases.
        verify_non_negative(new_available, "available_balance")
        verify_non_negative(new_locked, "locked_balance")

        wallet = await self._wallet_repo.update_balances(
            wallet,
            available_balance=new_available,
            locked_balance=new_locked,
        )

        # Ledger: available debit + locked credit (STAKE_LOCK entry type)
        await self._ledger.write_stake_lock(wallet, amount, reference_id, notes)
        return wallet

    # -----------------------------------------------------------------------
    # unlock_funds — generic locked → available (any reference type)
    # -----------------------------------------------------------------------

    async def unlock_funds(
        self,
        user_id: uuid.UUID,
        amount: Decimal,
        reference_id: uuid.UUID,
        notes: str | None = None,
    ) -> Wallet:
        """Move ``amount`` from locked_balance back to available_balance.

        Generic counterpart to unlock_stake; use when releasing a hold that was
        not placed via lock_stake (e.g. admin unlock, deposit release).

        Invariants guaranteed:
        - locked_balance >= 0 after operation (explicit pre-check raises
          InsufficientFundsError; verify_non_negative is a second guard).
        - available_balance >= 0 after operation (always true when adding to
          a non-negative value; verify_non_negative confirms).
        - SELECT FOR UPDATE prevents concurrent reads from seeing stale values.
        - All writes are flushed inside the caller's transaction atomically.

        Args:
            user_id: Target user.
            amount: Positive Decimal to move from locked → available.
            reference_id: UUID of the entity whose hold is being released.
            notes: Optional ledger note.

        Returns:
            Updated Wallet (flushed, not committed).

        Raises:
            InsufficientFundsError: locked_balance < amount.
            NotFoundError: Wallet does not exist for user_id.
            ValidationError: amount is not positive.
        """
        if amount <= Decimal("0"):
            raise ValidationError("unlock_funds: amount must be positive.")

        wallet = await self._wallet_repo.get_by_user_id_for_update(user_id)

        # Explicit locked-balance guard (invariant: locked >= 0 always).
        if wallet.locked_balance < amount:
            raise InsufficientFundsError(
                f"Insufficient locked balance. "
                f"Required: {amount}, Locked: {wallet.locked_balance}."
            )

        new_locked = safe_subtract(wallet.locked_balance, amount)
        new_available = safe_add(wallet.available_balance, amount)

        verify_non_negative(new_locked, "locked_balance")
        verify_non_negative(new_available, "available_balance")

        wallet = await self._wallet_repo.update_balances(
            wallet,
            available_balance=new_available,
            locked_balance=new_locked,
        )

        # Ledger: locked debit + available credit (STAKE_UNLOCK entry type)
        await self._ledger.write_stake_unlock(wallet, amount, reference_id, notes)
        return wallet

    # -----------------------------------------------------------------------
    # Deposit credit — credit available_balance on deposit completion
    # -----------------------------------------------------------------------

    async def credit_deposit(
        self,
        user_id: uuid.UUID,
        amount: Decimal,
        deposit_id: uuid.UUID,
        notes: str | None = None,
    ) -> Wallet:
        """Credit ``amount`` to available_balance when a deposit is completed.

        Acquires SELECT FOR UPDATE, adds amount to available_balance, writes
        a DEPOSIT ledger entry.

        Args:
            user_id: Recipient user.
            amount: Positive Decimal to credit.
            deposit_id: The DepositRequest UUID (used as ledger reference_id).
            notes: Optional ledger note.

        Raises:
            ValidationError: amount is not positive.
            NotFoundError: Wallet does not exist.
        """
        if amount <= Decimal("0"):
            raise ValidationError("credit_deposit: amount must be positive.")

        wallet = await self._wallet_repo.get_by_user_id_for_update(user_id)
        new_available = safe_add(wallet.available_balance, amount)
        verify_non_negative(new_available, "available_balance")

        wallet = await self._wallet_repo.update_balances(
            wallet, available_balance=new_available
        )
        await self._ledger.write_deposit_credit(wallet, amount, deposit_id, notes)
        return wallet

    # -----------------------------------------------------------------------
    # Withdrawal hold — available → locked when withdrawal is requested
    # -----------------------------------------------------------------------

    async def hold_withdrawal(
        self,
        user_id: uuid.UUID,
        amount: Decimal,
        withdrawal_id: uuid.UUID,
        notes: str | None = None,
    ) -> Wallet:
        """Move ``amount`` from available_balance to locked_balance.

        Called when a withdrawal request is created. Funds are held in locked
        until the withdrawal is completed (debited) or rejected/failed (released).

        Writes paired WITHDRAWAL_HOLD ledger entries.

        Raises:
            InsufficientFundsError: available_balance < amount.
            ValidationError: amount is not positive.
            NotFoundError: Wallet does not exist.
        """
        if amount <= Decimal("0"):
            raise ValidationError("hold_withdrawal: amount must be positive.")

        wallet = await self._wallet_repo.get_by_user_id_for_update(user_id)

        if wallet.available_balance < amount:
            raise InsufficientFundsError(
                f"Insufficient available balance for withdrawal. "
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
        await self._ledger.write_withdrawal_hold(wallet, amount, withdrawal_id, notes)
        return wallet

    # -----------------------------------------------------------------------
    # Withdrawal release — locked → available on rejection / failure
    # -----------------------------------------------------------------------

    async def release_withdrawal_hold(
        self,
        user_id: uuid.UUID,
        amount: Decimal,
        withdrawal_id: uuid.UUID,
        notes: str | None = None,
    ) -> Wallet:
        """Move ``amount`` from locked_balance back to available_balance.

        Called when a withdrawal is rejected or fails. Reverses the hold
        placed by hold_withdrawal.

        Writes paired WITHDRAWAL_RELEASE ledger entries.

        Raises:
            InsufficientFundsError: locked_balance < amount.
            ValidationError: amount is not positive.
            NotFoundError: Wallet does not exist.
        """
        if amount <= Decimal("0"):
            raise ValidationError("release_withdrawal_hold: amount must be positive.")

        wallet = await self._wallet_repo.get_by_user_id_for_update(user_id)

        if wallet.locked_balance < amount:
            raise InsufficientFundsError(
                f"Insufficient locked balance to release. "
                f"Required: {amount}, Locked: {wallet.locked_balance}."
            )

        new_locked = safe_subtract(wallet.locked_balance, amount)
        new_available = safe_add(wallet.available_balance, amount)
        verify_non_negative(new_locked, "locked_balance")
        verify_non_negative(new_available, "available_balance")

        wallet = await self._wallet_repo.update_balances(
            wallet,
            available_balance=new_available,
            locked_balance=new_locked,
        )
        await self._ledger.write_withdrawal_release(wallet, amount, withdrawal_id, notes)
        return wallet

    # -----------------------------------------------------------------------
    # Withdrawal finalise — debit locked on completion (funds leave platform)
    # -----------------------------------------------------------------------

    async def finalize_withdrawal_debit(
        self,
        user_id: uuid.UUID,
        amount: Decimal,
        withdrawal_id: uuid.UUID,
        notes: str | None = None,
    ) -> Wallet:
        """Debit ``amount`` from locked_balance when a withdrawal is completed.

        The held funds are permanently removed. Writes a single WITHDRAWAL
        ledger entry (locked debit — funds leave the platform).

        Raises:
            InsufficientFundsError: locked_balance < amount.
            ValidationError: amount is not positive.
            NotFoundError: Wallet does not exist.
        """
        if amount <= Decimal("0"):
            raise ValidationError("finalize_withdrawal_debit: amount must be positive.")

        wallet = await self._wallet_repo.get_by_user_id_for_update(user_id)

        if wallet.locked_balance < amount:
            raise InsufficientFundsError(
                f"Insufficient locked balance to finalise withdrawal. "
                f"Required: {amount}, Locked: {wallet.locked_balance}."
            )

        new_locked = safe_subtract(wallet.locked_balance, amount)
        verify_non_negative(new_locked, "locked_balance")

        wallet = await self._wallet_repo.update_balances(
            wallet, locked_balance=new_locked
        )
        await self._ledger.write_withdrawal_debit(wallet, amount, withdrawal_id, notes)
        return wallet

    # -----------------------------------------------------------------------
    # transfer_locked_funds — atomic winner-path settlement
    # -----------------------------------------------------------------------

    async def transfer_locked_funds(
        self,
        winner_id: uuid.UUID,
        loser_id: uuid.UUID,
        amount: Decimal,
        fee: Decimal,
        bet_id: uuid.UUID,
        notes: str | None = None,
    ) -> tuple[Wallet, Wallet]:
        """Consume both users' locked stakes and credit the winner net of fee.

        This is the single-method implementation of the winner settlement path.
        It is designed to be called inside an already-open database transaction
        owned by SettlementService; it does NOT commit.

        Balance movements:
          winner.locked    -= amount              (stake consumed)
          loser.locked     -= amount              (stake consumed)
          winner.available += (2 * amount) - fee  (net payout credited)

        Ledger entries written (all reference bet_id, type = settlement):
          1. Winner: SETTLEMENT_DEDUCT | locked    | debit  | amount
          2. Loser:  SETTLEMENT_DEDUCT | locked    | debit  | amount
          3. Winner: PAYOUT_CREDIT     | available | credit | winner_payout
             (notes carry the fee figure for full traceability)

        The platform fee (``fee`` argument) is not credited to the platform
        account here — that is the caller's responsibility (SettlementService).

        Deadlock prevention:
          Both wallets are locked with SELECT FOR UPDATE in ascending UUID order
          so that concurrent settlement attempts always acquire locks in the same
          sequence, eliminating deadlock cycles.

        Invariants guaranteed:
          - winner.locked_balance  >= 0 (explicit pre-check + verify_non_negative)
          - loser.locked_balance   >= 0 (explicit pre-check + verify_non_negative)
          - winner.available_balance >= 0 (always true: positive credit; verified)
          - No partial state: all four mutations flushed together before ledger
            writes; if any step raises, the transaction rolls back in full.

        Args:
            winner_id:  User who won the bet.
            loser_id:   User who lost the bet.
            amount:     Per-user stake (positive Decimal).
            fee:        Platform fee deducted from the total pool (>= 0,
                        must be strictly less than 2 * amount).
            bet_id:     Settled bet UUID — used as ledger reference_id.
            notes:      Optional note appended to ledger entries.

        Returns:
            Tuple of (winner_wallet, loser_wallet) after update.

        Raises:
            ValidationError:        amount <= 0, fee < 0, or fee >= 2 * amount.
            InsufficientFundsError: Either wallet has insufficient locked balance.
            NotFoundError:          Either wallet does not exist.
        """
        # ------------------------------------------------------------------
        # 1. Input validation
        # ------------------------------------------------------------------
        if amount <= Decimal("0"):
            raise ValidationError("transfer_locked_funds: amount must be positive.")
        if fee < Decimal("0"):
            raise ValidationError("transfer_locked_funds: fee must not be negative.")

        total_pool = safe_add(amount, amount)  # 2 * amount
        winner_payout = safe_subtract(total_pool, fee)

        if winner_payout <= Decimal("0"):
            raise ValidationError(
                f"transfer_locked_funds: fee ({fee}) must be less than "
                f"total pool ({total_pool})."
            )

        # ------------------------------------------------------------------
        # 2. Acquire SELECT FOR UPDATE locks in deterministic UUID order
        #    to prevent deadlocks when two settlements run concurrently.
        # ------------------------------------------------------------------
        ids_ordered = sorted([winner_id, loser_id], key=str)

        wallets: dict[uuid.UUID, Wallet] = {}
        for uid in ids_ordered:
            wallets[uid] = await self._wallet_repo.get_by_user_id_for_update(uid)

        winner_wallet = wallets[winner_id]
        loser_wallet = wallets[loser_id]

        # ------------------------------------------------------------------
        # 3. Validate locked balances (explicit pre-checks before any mutation)
        # ------------------------------------------------------------------
        if winner_wallet.locked_balance < amount:
            raise InsufficientFundsError(
                f"Winner locked_balance insufficient. "
                f"Required: {amount}, Locked: {winner_wallet.locked_balance}."
            )
        if loser_wallet.locked_balance < amount:
            raise InsufficientFundsError(
                f"Loser locked_balance insufficient. "
                f"Required: {amount}, Locked: {loser_wallet.locked_balance}."
            )

        # ------------------------------------------------------------------
        # 4. Compute new balances (no mutation yet — all-or-nothing)
        # ------------------------------------------------------------------
        winner_new_locked = safe_subtract(winner_wallet.locked_balance, amount)
        winner_new_available = safe_add(winner_wallet.available_balance, winner_payout)
        loser_new_locked = safe_subtract(loser_wallet.locked_balance, amount)
        # loser available_balance is unchanged

        # Second-level arithmetic guards
        verify_non_negative(winner_new_locked, "winner locked_balance")
        verify_non_negative(winner_new_available, "winner available_balance")
        verify_non_negative(loser_new_locked, "loser locked_balance")

        # ------------------------------------------------------------------
        # 5. Persist both balance updates (both flushed before any ledger write)
        # ------------------------------------------------------------------
        winner_wallet = await self._wallet_repo.update_balances(
            winner_wallet,
            available_balance=winner_new_available,
            locked_balance=winner_new_locked,
        )
        loser_wallet = await self._wallet_repo.update_balances(
            loser_wallet,
            locked_balance=loser_new_locked,
        )

        # ------------------------------------------------------------------
        # 6. Write ledger entries (post-update snapshots are now on wallets)
        # ------------------------------------------------------------------
        fee_note = (
            f"platform fee={fee}" if fee > Decimal("0") else "zero fee"
        )
        entry_notes = (
            f"{notes}; {fee_note}" if notes else fee_note
        )

        await self._ledger.write_settlement_winner(
            winner_wallet=winner_wallet,
            loser_wallet=loser_wallet,
            stake_amount=amount,
            winner_payout=winner_payout,
            bet_id=bet_id,
            notes=entry_notes,
        )

        return winner_wallet, loser_wallet
