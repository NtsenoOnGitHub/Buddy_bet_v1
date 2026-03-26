"""Withdrawal repository — data access for withdrawal_requests table."""

from __future__ import annotations

import uuid
from typing import List, Tuple

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import WithdrawalStatus
from app.models.withdrawal import WithdrawalRequest
from app.repositories.base import BaseRepository
from app.schemas.common import PageParams
from app.utils.pagination import paginate


class WithdrawalRepository(BaseRepository[WithdrawalRequest]):
    def __init__(self, db: AsyncSession) -> None:
        super().__init__(WithdrawalRequest, db)

    async def get_by_user(
        self,
        user_id: uuid.UUID,
        params: PageParams,
    ) -> Tuple[List[WithdrawalRequest], int]:
        """Return paginated withdrawals for a specific user, newest first."""
        query = (
            select(WithdrawalRequest)
            .where(WithdrawalRequest.user_id == user_id)
            .order_by(WithdrawalRequest.requested_at.desc())
        )
        return await paginate(self.db, query, params)

    async def list_all(
        self,
        params: PageParams,
        status: WithdrawalStatus | None = None,
    ) -> Tuple[List[WithdrawalRequest], int]:
        """Return paginated withdrawals across all users (admin view), newest first."""
        query = select(WithdrawalRequest).order_by(
            WithdrawalRequest.requested_at.desc()
        )
        if status is not None:
            query = query.where(WithdrawalRequest.status == status)
        return await paginate(self.db, query, params)
