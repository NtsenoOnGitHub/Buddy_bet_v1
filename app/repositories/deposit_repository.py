"""Deposit repository — data access for deposit_requests table."""

from __future__ import annotations

import uuid
from typing import List, Tuple

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.deposit import DepositRequest
from app.models.enums import DepositStatus
from app.repositories.base import BaseRepository
from app.schemas.common import PageParams
from app.utils.pagination import paginate


class DepositRepository(BaseRepository[DepositRequest]):
    def __init__(self, db: AsyncSession) -> None:
        super().__init__(DepositRequest, db)

    async def get_by_user(
        self,
        user_id: uuid.UUID,
        params: PageParams,
    ) -> Tuple[List[DepositRequest], int]:
        """Return paginated deposits for a specific user, newest first."""
        query = (
            select(DepositRequest)
            .where(DepositRequest.user_id == user_id)
            .order_by(DepositRequest.requested_at.desc())
        )
        return await paginate(self.db, query, params)

    async def list_all(
        self,
        params: PageParams,
        status: DepositStatus | None = None,
    ) -> Tuple[List[DepositRequest], int]:
        """Return paginated deposits across all users (admin view), newest first."""
        query = select(DepositRequest).order_by(DepositRequest.requested_at.desc())
        if status is not None:
            query = query.where(DepositRequest.status == status)
        return await paginate(self.db, query, params)

    async def get_by_provider_reference(
        self, provider_reference: str
    ) -> DepositRequest | None:
        """Look up a deposit by its external provider reference (for webhooks)."""
        result = await self.db.execute(
            select(DepositRequest).where(
                DepositRequest.provider_reference == provider_reference
            )
        )
        return result.scalar_one_or_none()
