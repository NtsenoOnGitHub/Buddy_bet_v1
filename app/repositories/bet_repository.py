"""Bet repository.

get_for_update issues SELECT FOR UPDATE on a bet row to prevent the concurrent
acceptance race condition (Section 4.1 / 11.1 of the spec).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import List, Optional, Tuple

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.models.bet import Bet
from app.models.enums import BetStatus
from app.repositories.base import BaseRepository
from app.schemas.common import PageParams
from app.utils.pagination import paginate


class BetRepository(BaseRepository[Bet]):
    """Data access layer for the bets table."""

    def __init__(self, db: AsyncSession) -> None:
        super().__init__(Bet, db)

    async def get_for_update(self, bet_id: uuid.UUID) -> Bet:
        """Fetch a bet row with SELECT FOR UPDATE.

        Must be called at the start of every acceptance transaction to prevent
        two users from accepting the same OPEN bet simultaneously.

        Raises:
            NotFoundError: If the bet does not exist.
        """
        result = await self.db.execute(
            select(Bet).where(Bet.id == bet_id).with_for_update()
        )
        bet = result.scalar_one_or_none()
        if bet is None:
            raise NotFoundError(f"Bet with id={bet_id} not found.")
        return bet

    async def get_open_bets(
        self,
        params: PageParams,
    ) -> Tuple[List[Bet], int]:
        """Return paginated OPEN bets that have not yet expired.

        Bets are ordered by created_at DESC (newest first).
        Only bets with expires_at > now() are returned.
        """
        now = datetime.now(tz=timezone.utc)
        query = (
            select(Bet)
            .where(Bet.status == BetStatus.OPEN)
            .where(Bet.expires_at > now)
            .order_by(Bet.created_at.desc())
        )
        return await paginate(self.db, query, params)

    async def get_user_bets(
        self,
        user_id: uuid.UUID,
        params: PageParams,
    ) -> Tuple[List[Bet], int]:
        """Return all bets for a user (as creator or opponent), newest first.

        Covers the GET /bets/my endpoint — returns bets across all statuses.
        """
        query = (
            select(Bet)
            .where(
                or_(Bet.creator_id == user_id, Bet.opponent_id == user_id)
            )
            .order_by(Bet.created_at.desc())
        )
        return await paginate(self.db, query, params)

    async def get_by_match_pending_settlement(
        self,
        match_id: uuid.UUID,
    ) -> List[Bet]:
        """Return all bets for a match that are awaiting settlement.

        Used by the Settlement Engine to locate bets after a match result
        is confirmed. Matches bets in MATCHED or PENDING_SETTLEMENT status.
        """
        result = await self.db.execute(
            select(Bet)
            .where(Bet.match_id == match_id)
            .where(
                Bet.status.in_([BetStatus.MATCHED, BetStatus.PENDING_SETTLEMENT])
            )
        )
        return list(result.scalars().all())
