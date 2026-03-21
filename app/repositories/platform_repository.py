"""Platform repository.

Provides SELECT FOR UPDATE access to PlatformAccount rows and insert-only
access to PlatformLedgerEntry rows. These are the two data structures that
track platform fee income.

At MVP there is exactly one PlatformAccount per currency (PLATFORM_FEES_ZAR).
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.models.enums import LedgerDirection, LedgerReferenceType, PlatformEntryType, SettlementPathType
from app.models.platform import PlatformAccount, PlatformLedgerEntry
from app.utils.decimal_utils import safe_add


class PlatformRepository:
    """Data access layer for platform_accounts and platform_ledger_entries."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def get_for_currency_for_update(self, currency: str) -> PlatformAccount:
        """Return the platform account for a currency with SELECT FOR UPDATE.

        Must be called before crediting the platform to prevent concurrent
        writes from producing an incorrect balance.

        Args:
            currency: ISO 4217 currency code, e.g. "ZAR".

        Raises:
            NotFoundError: If no platform account exists for this currency.
        """
        result = await self._db.execute(
            select(PlatformAccount)
            .where(PlatformAccount.currency == currency)
            .with_for_update()
        )
        account = result.scalar_one_or_none()
        if account is None:
            raise NotFoundError(
                f"Platform account for currency={currency!r} not found. "
                "Ensure the platform account is seeded."
            )
        return account

    async def credit_fee(
        self,
        account: PlatformAccount,
        amount: Decimal,
    ) -> PlatformAccount:
        """Add amount to the platform account balance and increment version.

        The account must have been fetched with get_for_currency_for_update
        before calling this method.

        Args:
            account: The locked PlatformAccount instance.
            amount: Positive Decimal fee amount to credit.

        Returns:
            Updated PlatformAccount (flushed, not committed).
        """
        account.balance = safe_add(account.balance, amount)
        account.version += 1
        self._db.add(account)
        await self._db.flush()
        await self._db.refresh(account)
        return account

    async def write_ledger_entry(
        self,
        account: PlatformAccount,
        amount: Decimal,
        bet_id: uuid.UUID,
        entry_type: PlatformEntryType,
        settlement_path: SettlementPathType,
    ) -> PlatformLedgerEntry:
        """Insert an immutable PlatformLedgerEntry for a fee credit.

        balance_after snapshots the platform account balance AFTER the credit
        has been applied. Caller must call credit_fee before this method.

        Args:
            account: The updated PlatformAccount (used for balance snapshot).
            amount: Fee amount credited.
            bet_id: The settled bet UUID (FK to bets.id).
            entry_type: FEE_COLLECTION or FEE_COLLECTION_NO_WINNER.
            settlement_path: winner or no_winner.

        Returns:
            The persisted PlatformLedgerEntry (flushed, not committed).
        """
        entry = PlatformLedgerEntry(
            platform_account_id=account.id,
            entry_type=entry_type,
            direction=LedgerDirection.credit,
            amount=amount,
            reference_type=LedgerReferenceType.settlement,
            reference_id=bet_id,
            balance_after=account.balance,
            settlement_path=settlement_path,
        )
        self._db.add(entry)
        await self._db.flush()
        await self._db.refresh(entry)
        return entry
