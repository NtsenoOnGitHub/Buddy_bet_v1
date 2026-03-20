"""Ledger repository.

Ledger entries are IMMUTABLE — only INSERT (create_entry) operations are
permitted. No UPDATE or DELETE methods exist here by design.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import List, Tuple

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import (
    BalanceField,
    LedgerDirection,
    LedgerEntryType,
    LedgerReferenceType,
)
from app.models.ledger import LedgerEntry
from app.repositories.base import BaseRepository
from app.schemas.common import PageParams
from app.utils.pagination import paginate


class LedgerRepository(BaseRepository[LedgerEntry]):
    """Data access layer for the ledger_entries table (insert-only)."""

    def __init__(self, db: AsyncSession) -> None:
        super().__init__(LedgerEntry, db)

    async def create_entry(
        self,
        user_id: uuid.UUID,
        wallet_id: uuid.UUID,
        entry_type: LedgerEntryType,
        balance_field: BalanceField,
        direction: LedgerDirection,
        amount: Decimal,
        reference_type: LedgerReferenceType,
        reference_id: uuid.UUID,
        available_balance_after: Decimal,
        locked_balance_after: Decimal,
        notes: str | None = None,
    ) -> LedgerEntry:
        """Insert a single immutable ledger entry.

        Both balance snapshots (available_balance_after and locked_balance_after)
        must reflect the wallet state AFTER the balance change has been applied.
        This enables point-in-time wallet reconstruction from the ledger alone.

        Args:
            user_id: The affected user.
            wallet_id: The affected wallet.
            entry_type: The type of financial event.
            balance_field: Which balance field (available | locked) this entry affects.
            direction: Whether this is a credit or debit on the balance_field.
            amount: Positive amount of the change.
            reference_type: Category of the source record.
            reference_id: ID of the source record (e.g. bet_id).
            available_balance_after: Snapshot of wallet.available_balance after this entry.
            locked_balance_after: Snapshot of wallet.locked_balance after this entry.
            notes: Optional human-readable annotation.

        Returns:
            The newly created LedgerEntry (flushed, not committed).
        """
        return await super().create(
            user_id=user_id,
            wallet_id=wallet_id,
            entry_type=entry_type,
            balance_field=balance_field,
            direction=direction,
            amount=amount,
            reference_type=reference_type,
            reference_id=reference_id,
            available_balance_after=available_balance_after,
            locked_balance_after=locked_balance_after,
            notes=notes,
        )

    async def get_user_history(
        self,
        user_id: uuid.UUID,
        params: PageParams,
    ) -> Tuple[List[LedgerEntry], int]:
        """Return a user's paginated ledger history, newest first.

        Used by GET /wallet/transactions.
        """
        query = (
            select(LedgerEntry)
            .where(LedgerEntry.user_id == user_id)
            .order_by(LedgerEntry.created_at.desc())
        )
        return await paginate(self.db, query, params)
