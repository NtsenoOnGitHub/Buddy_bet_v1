"""Wallet repository.

get_by_user_id_for_update issues SELECT FOR UPDATE to serialise concurrent
wallet mutations. All balance-mutating operations must call this method, not
get_by_user_id, to prevent race conditions.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.models.wallet import Wallet
from app.repositories.base import BaseRepository


class WalletRepository(BaseRepository[Wallet]):
    """Data access layer for the wallets table."""

    def __init__(self, db: AsyncSession) -> None:
        super().__init__(Wallet, db)

    async def get_by_user_id(self, user_id: uuid.UUID) -> Optional[Wallet]:
        """Return the wallet for a user without locking."""
        result = await self.db.execute(
            select(Wallet).where(Wallet.user_id == user_id)
        )
        return result.scalar_one_or_none()

    async def get_by_user_id_or_404(self, user_id: uuid.UUID) -> Wallet:
        """Return the wallet for a user without locking, raising 404 if absent."""
        wallet = await self.get_by_user_id(user_id)
        if wallet is None:
            raise NotFoundError(f"Wallet for user_id={user_id} not found.")
        return wallet

    async def get_by_user_id_for_update(self, user_id: uuid.UUID) -> Wallet:
        """Return the wallet for a user with SELECT FOR UPDATE.

        This method MUST be called before any balance mutation to serialise
        concurrent writes on the same wallet row.

        Raises:
            NotFoundError: If no wallet exists for the given user_id.
        """
        result = await self.db.execute(
            select(Wallet)
            .where(Wallet.user_id == user_id)
            .with_for_update()
        )
        wallet = result.scalar_one_or_none()
        if wallet is None:
            raise NotFoundError(f"Wallet for user_id={user_id} not found.")
        return wallet

    async def update_balances(
        self,
        wallet: Wallet,
        available_balance: Optional[Decimal] = None,
        locked_balance: Optional[Decimal] = None,
    ) -> Wallet:
        """Apply balance changes and increment the optimistic lock version.

        Only updates the fields that are explicitly provided (non-None).
        Always increments wallet.version.

        Args:
            wallet: The locked Wallet instance (must have been fetched with FOR UPDATE).
            available_balance: New available balance value, or None to leave unchanged.
            locked_balance: New locked balance value, or None to leave unchanged.

        Returns:
            The updated Wallet instance (flushed but not committed).
        """
        if available_balance is not None:
            wallet.available_balance = available_balance
        if locked_balance is not None:
            wallet.locked_balance = locked_balance
        wallet.version += 1

        self.db.add(wallet)
        await self.db.flush()
        await self.db.refresh(wallet)
        return wallet
