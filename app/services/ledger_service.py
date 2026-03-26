"""Ledger service — writes paired immutable ledger entries for every wallet operation.

Every public method on this service writes TWO entries sharing the same reference_id
(the bet_id or deposit_id), one for each balance field affected. Both entries snapshot
both wallet balance fields after the full operation — not the intermediate state.

IMPORTANT: Callers must pass the wallet AFTER its balances have been updated
so the snapshots reflect the correct post-operation state.

All ledger writes are insert-only. No method here may update or delete entries.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import (
    BalanceField,
    LedgerDirection,
    LedgerEntryType,
    LedgerReferenceType,
)
from app.models.wallet import Wallet
from app.repositories.ledger_repository import LedgerRepository


class LedgerService:
    """Writes paired immutable ledger entries for wallet balance operations."""

    def __init__(self, db: AsyncSession) -> None:
        self._repo = LedgerRepository(db)

    # -----------------------------------------------------------------------
    # STAKE_LOCK — bet created or accepted
    # Entries: available debit + locked credit
    # -----------------------------------------------------------------------

    async def write_stake_lock(
        self,
        wallet: Wallet,
        amount: Decimal,
        bet_id: uuid.UUID,
        notes: str | None = None,
    ) -> None:
        """Write two STAKE_LOCK entries when a stake is moved from available → locked.

        Entry 1: STAKE_LOCK | available | debit  | amount
        Entry 2: STAKE_LOCK | locked    | credit | amount

        Both entries snapshot the wallet state AFTER the balance update.
        """
        # Entry 1: debit available
        await self._repo.create_entry(
            user_id=wallet.user_id,
            wallet_id=wallet.id,
            entry_type=LedgerEntryType.STAKE_LOCK,
            balance_field=BalanceField.available,
            direction=LedgerDirection.debit,
            amount=amount,
            reference_type=LedgerReferenceType.bet,
            reference_id=bet_id,
            available_balance_after=wallet.available_balance,
            locked_balance_after=wallet.locked_balance,
            notes=notes,
        )
        # Entry 2: credit locked
        await self._repo.create_entry(
            user_id=wallet.user_id,
            wallet_id=wallet.id,
            entry_type=LedgerEntryType.STAKE_LOCK,
            balance_field=BalanceField.locked,
            direction=LedgerDirection.credit,
            amount=amount,
            reference_type=LedgerReferenceType.bet,
            reference_id=bet_id,
            available_balance_after=wallet.available_balance,
            locked_balance_after=wallet.locked_balance,
            notes=notes,
        )

    # -----------------------------------------------------------------------
    # STAKE_UNLOCK — bet cancelled (OPEN, creator only)
    # Entries: locked debit + available credit
    # -----------------------------------------------------------------------

    async def write_stake_unlock(
        self,
        wallet: Wallet,
        amount: Decimal,
        bet_id: uuid.UUID,
        notes: str | None = None,
    ) -> None:
        """Write two STAKE_UNLOCK entries when a cancelled bet returns locked → available.

        Entry 1: STAKE_UNLOCK | locked    | debit  | amount
        Entry 2: STAKE_UNLOCK | available | credit | amount
        """
        # Entry 1: debit locked
        await self._repo.create_entry(
            user_id=wallet.user_id,
            wallet_id=wallet.id,
            entry_type=LedgerEntryType.STAKE_UNLOCK,
            balance_field=BalanceField.locked,
            direction=LedgerDirection.debit,
            amount=amount,
            reference_type=LedgerReferenceType.cancellation,
            reference_id=bet_id,
            available_balance_after=wallet.available_balance,
            locked_balance_after=wallet.locked_balance,
            notes=notes,
        )
        # Entry 2: credit available
        await self._repo.create_entry(
            user_id=wallet.user_id,
            wallet_id=wallet.id,
            entry_type=LedgerEntryType.STAKE_UNLOCK,
            balance_field=BalanceField.available,
            direction=LedgerDirection.credit,
            amount=amount,
            reference_type=LedgerReferenceType.cancellation,
            reference_id=bet_id,
            available_balance_after=wallet.available_balance,
            locked_balance_after=wallet.locked_balance,
            notes=notes,
        )

    # -----------------------------------------------------------------------
    # VOID_REFUND — match voided (cancelled/postponed/abandoned)
    # Entries: locked debit + available credit
    # -----------------------------------------------------------------------

    async def write_void_refund(
        self,
        wallet: Wallet,
        amount: Decimal,
        bet_id: uuid.UUID,
        notes: str | None = None,
    ) -> None:
        """Write two VOID_REFUND entries when a voided bet returns locked → available.

        Entry 1: VOID_REFUND | locked    | debit  | amount
        Entry 2: VOID_REFUND | available | credit | amount
        """
        # Entry 1: debit locked
        await self._repo.create_entry(
            user_id=wallet.user_id,
            wallet_id=wallet.id,
            entry_type=LedgerEntryType.VOID_REFUND,
            balance_field=BalanceField.locked,
            direction=LedgerDirection.debit,
            amount=amount,
            reference_type=LedgerReferenceType.void,
            reference_id=bet_id,
            available_balance_after=wallet.available_balance,
            locked_balance_after=wallet.locked_balance,
            notes=notes,
        )
        # Entry 2: credit available
        await self._repo.create_entry(
            user_id=wallet.user_id,
            wallet_id=wallet.id,
            entry_type=LedgerEntryType.VOID_REFUND,
            balance_field=BalanceField.available,
            direction=LedgerDirection.credit,
            amount=amount,
            reference_type=LedgerReferenceType.void,
            reference_id=bet_id,
            available_balance_after=wallet.available_balance,
            locked_balance_after=wallet.locked_balance,
            notes=notes,
        )

    # -----------------------------------------------------------------------
    # SETTLEMENT — winner path (PATH A / B)
    # Per spec section 9.3 ledger sequence:
    #   Step 1: Winner  SETTLEMENT_DEDUCT locked debit  S
    #   Step 2: Loser   SETTLEMENT_DEDUCT locked debit  S
    #   Step 3: Winner  PAYOUT_CREDIT     available credit  winner_payout
    # -----------------------------------------------------------------------

    async def write_settlement_winner(
        self,
        winner_wallet: Wallet,
        loser_wallet: Wallet,
        stake_amount: Decimal,
        winner_payout: Decimal,
        bet_id: uuid.UUID,
        notes: str | None = None,
    ) -> None:
        """Write settlement entries for the winner path.

        Caller must update both wallets before calling this method so that
        the balance snapshots reflect the post-settlement state.

        Steps written (all share reference_id = bet_id):
          1. Winner: SETTLEMENT_DEDUCT | locked    | debit  | stake_amount
          2. Loser:  SETTLEMENT_DEDUCT | locked    | debit  | stake_amount
          3. Winner: PAYOUT_CREDIT     | available | credit | winner_payout
        """
        # Step 1: Winner locked stake consumed
        await self._repo.create_entry(
            user_id=winner_wallet.user_id,
            wallet_id=winner_wallet.id,
            entry_type=LedgerEntryType.SETTLEMENT_DEDUCT,
            balance_field=BalanceField.locked,
            direction=LedgerDirection.debit,
            amount=stake_amount,
            reference_type=LedgerReferenceType.settlement,
            reference_id=bet_id,
            available_balance_after=winner_wallet.available_balance,
            locked_balance_after=winner_wallet.locked_balance,
            notes=notes or "Winner: locked stake consumed at settlement",
        )
        # Step 2: Loser locked stake consumed
        await self._repo.create_entry(
            user_id=loser_wallet.user_id,
            wallet_id=loser_wallet.id,
            entry_type=LedgerEntryType.SETTLEMENT_DEDUCT,
            balance_field=BalanceField.locked,
            direction=LedgerDirection.debit,
            amount=stake_amount,
            reference_type=LedgerReferenceType.settlement,
            reference_id=bet_id,
            available_balance_after=loser_wallet.available_balance,
            locked_balance_after=loser_wallet.locked_balance,
            notes=notes or "Loser: locked stake consumed at settlement",
        )
        # Step 3: Winner receives payout in available
        await self._repo.create_entry(
            user_id=winner_wallet.user_id,
            wallet_id=winner_wallet.id,
            entry_type=LedgerEntryType.PAYOUT_CREDIT,
            balance_field=BalanceField.available,
            direction=LedgerDirection.credit,
            amount=winner_payout,
            reference_type=LedgerReferenceType.settlement,
            reference_id=bet_id,
            available_balance_after=winner_wallet.available_balance,
            locked_balance_after=winner_wallet.locked_balance,
            notes=notes or "Winner payout (90% of pool) credited to available",
        )

    # -----------------------------------------------------------------------
    # SETTLEMENT — no-winner path (PATH C)
    # Per spec section 9.4 ledger sequence:
    #   Step 1: User A  FEE_DEDUCT        locked debit  fee_per_user
    #   Step 2: User A  SETTLEMENT_DEDUCT locked debit  refund_per_user
    #   Step 3: User A  REFUND_CREDIT     available credit refund_per_user
    #   Step 4: User B  FEE_DEDUCT        locked debit  fee_per_user
    #   Step 5: User B  SETTLEMENT_DEDUCT locked debit  refund_per_user
    #   Step 6: User B  REFUND_CREDIT     available credit refund_per_user
    # -----------------------------------------------------------------------

    # -----------------------------------------------------------------------
    # DEPOSIT — funds credited to available on deposit completion
    # Entry: available credit (single entry — no locked movement)
    # -----------------------------------------------------------------------

    async def write_deposit_credit(
        self,
        wallet: Wallet,
        amount: Decimal,
        deposit_id: uuid.UUID,
        notes: str | None = None,
    ) -> None:
        """Write a single DEPOSIT entry when a deposit is completed.

        Entry: DEPOSIT | available | credit | amount

        The wallet must already have its available_balance incremented before
        this is called so the snapshot reflects the post-credit state.
        """
        await self._repo.create_entry(
            user_id=wallet.user_id,
            wallet_id=wallet.id,
            entry_type=LedgerEntryType.DEPOSIT,
            balance_field=BalanceField.available,
            direction=LedgerDirection.credit,
            amount=amount,
            reference_type=LedgerReferenceType.deposit,
            reference_id=deposit_id,
            available_balance_after=wallet.available_balance,
            locked_balance_after=wallet.locked_balance,
            notes=notes or "Deposit completed — funds credited to available balance",
        )

    # -----------------------------------------------------------------------
    # WITHDRAWAL_HOLD — available → locked when withdrawal is requested
    # Entries: available debit + locked credit
    # -----------------------------------------------------------------------

    async def write_withdrawal_hold(
        self,
        wallet: Wallet,
        amount: Decimal,
        withdrawal_id: uuid.UUID,
        notes: str | None = None,
    ) -> None:
        """Write two WITHDRAWAL_HOLD entries when funds are reserved for withdrawal.

        Entry 1: WITHDRAWAL_HOLD | available | debit  | amount
        Entry 2: WITHDRAWAL_HOLD | locked    | credit | amount
        """
        await self._repo.create_entry(
            user_id=wallet.user_id,
            wallet_id=wallet.id,
            entry_type=LedgerEntryType.WITHDRAWAL_HOLD,
            balance_field=BalanceField.available,
            direction=LedgerDirection.debit,
            amount=amount,
            reference_type=LedgerReferenceType.withdrawal,
            reference_id=withdrawal_id,
            available_balance_after=wallet.available_balance,
            locked_balance_after=wallet.locked_balance,
            notes=notes or "Withdrawal hold — funds moved from available to locked",
        )
        await self._repo.create_entry(
            user_id=wallet.user_id,
            wallet_id=wallet.id,
            entry_type=LedgerEntryType.WITHDRAWAL_HOLD,
            balance_field=BalanceField.locked,
            direction=LedgerDirection.credit,
            amount=amount,
            reference_type=LedgerReferenceType.withdrawal,
            reference_id=withdrawal_id,
            available_balance_after=wallet.available_balance,
            locked_balance_after=wallet.locked_balance,
            notes=notes or "Withdrawal hold — funds moved from available to locked",
        )

    # -----------------------------------------------------------------------
    # WITHDRAWAL_RELEASE — locked → available on rejection or failure
    # Entries: locked debit + available credit
    # -----------------------------------------------------------------------

    async def write_withdrawal_release(
        self,
        wallet: Wallet,
        amount: Decimal,
        withdrawal_id: uuid.UUID,
        notes: str | None = None,
    ) -> None:
        """Write two WITHDRAWAL_RELEASE entries when held funds are returned.

        Entry 1: WITHDRAWAL_RELEASE | locked    | debit  | amount
        Entry 2: WITHDRAWAL_RELEASE | available | credit | amount
        """
        await self._repo.create_entry(
            user_id=wallet.user_id,
            wallet_id=wallet.id,
            entry_type=LedgerEntryType.WITHDRAWAL_RELEASE,
            balance_field=BalanceField.locked,
            direction=LedgerDirection.debit,
            amount=amount,
            reference_type=LedgerReferenceType.withdrawal,
            reference_id=withdrawal_id,
            available_balance_after=wallet.available_balance,
            locked_balance_after=wallet.locked_balance,
            notes=notes or "Withdrawal released — held funds returned to available",
        )
        await self._repo.create_entry(
            user_id=wallet.user_id,
            wallet_id=wallet.id,
            entry_type=LedgerEntryType.WITHDRAWAL_RELEASE,
            balance_field=BalanceField.available,
            direction=LedgerDirection.credit,
            amount=amount,
            reference_type=LedgerReferenceType.withdrawal,
            reference_id=withdrawal_id,
            available_balance_after=wallet.available_balance,
            locked_balance_after=wallet.locked_balance,
            notes=notes or "Withdrawal released — held funds returned to available",
        )

    # -----------------------------------------------------------------------
    # WITHDRAWAL — final debit from locked on completion
    # Entry: locked debit (single entry — funds leave the platform)
    # -----------------------------------------------------------------------

    async def write_withdrawal_debit(
        self,
        wallet: Wallet,
        amount: Decimal,
        withdrawal_id: uuid.UUID,
        notes: str | None = None,
    ) -> None:
        """Write a single WITHDRAWAL entry when a withdrawal is finalised.

        Entry: WITHDRAWAL | locked | debit | amount

        The wallet must already have its locked_balance decremented before
        this is called so the snapshot reflects the post-debit state.
        """
        await self._repo.create_entry(
            user_id=wallet.user_id,
            wallet_id=wallet.id,
            entry_type=LedgerEntryType.WITHDRAWAL,
            balance_field=BalanceField.locked,
            direction=LedgerDirection.debit,
            amount=amount,
            reference_type=LedgerReferenceType.withdrawal,
            reference_id=withdrawal_id,
            available_balance_after=wallet.available_balance,
            locked_balance_after=wallet.locked_balance,
            notes=notes or "Withdrawal completed — funds debited from locked balance",
        )

    async def write_settlement_no_winner(
        self,
        creator_wallet: Wallet,
        opponent_wallet: Wallet,
        fee_per_user: Decimal,
        refund_per_user: Decimal,
        bet_id: uuid.UUID,
        notes: str | None = None,
    ) -> None:
        """Write settlement entries for the no-winner path.

        Caller must update both wallets before calling this method.

        Steps written (all share reference_id = bet_id):
          1. Creator: FEE_DEDUCT        | locked    | debit  | fee_per_user
          2. Creator: SETTLEMENT_DEDUCT | locked    | debit  | refund_per_user
          3. Creator: REFUND_CREDIT     | available | credit | refund_per_user
          4. Opponent: FEE_DEDUCT        | locked    | debit  | fee_per_user
          5. Opponent: SETTLEMENT_DEDUCT | locked    | debit  | refund_per_user
          6. Opponent: REFUND_CREDIT     | available | credit | refund_per_user
        """
        for wallet in (creator_wallet, opponent_wallet):
            actor_label = "Creator" if wallet.user_id == creator_wallet.user_id else "Opponent"

            # FEE_DEDUCT — platform fee portion from locked
            await self._repo.create_entry(
                user_id=wallet.user_id,
                wallet_id=wallet.id,
                entry_type=LedgerEntryType.FEE_DEDUCT,
                balance_field=BalanceField.locked,
                direction=LedgerDirection.debit,
                amount=fee_per_user,
                reference_type=LedgerReferenceType.settlement,
                reference_id=bet_id,
                available_balance_after=wallet.available_balance,
                locked_balance_after=wallet.locked_balance,
                notes=f"{actor_label}: platform fee (5%) deducted from locked stake",
            )
            # SETTLEMENT_DEDUCT — refund portion consumed from locked
            await self._repo.create_entry(
                user_id=wallet.user_id,
                wallet_id=wallet.id,
                entry_type=LedgerEntryType.SETTLEMENT_DEDUCT,
                balance_field=BalanceField.locked,
                direction=LedgerDirection.debit,
                amount=refund_per_user,
                reference_type=LedgerReferenceType.settlement,
                reference_id=bet_id,
                available_balance_after=wallet.available_balance,
                locked_balance_after=wallet.locked_balance,
                notes=f"{actor_label}: refund portion consumed from locked",
            )
            # REFUND_CREDIT — refund credited to available
            await self._repo.create_entry(
                user_id=wallet.user_id,
                wallet_id=wallet.id,
                entry_type=LedgerEntryType.REFUND_CREDIT,
                balance_field=BalanceField.available,
                direction=LedgerDirection.credit,
                amount=refund_per_user,
                reference_type=LedgerReferenceType.settlement,
                reference_id=bet_id,
                available_balance_after=wallet.available_balance,
                locked_balance_after=wallet.locked_balance,
                notes=f"{actor_label}: 95% refund credited to available balance",
            )
