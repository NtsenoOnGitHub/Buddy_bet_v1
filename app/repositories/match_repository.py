"""Match repository."""

from __future__ import annotations

import uuid
from typing import List, Optional, Tuple

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.models.enums import MatchStatus
from app.models.match import Match
from app.repositories.base import BaseRepository
from app.schemas.common import PageParams
from app.utils.pagination import paginate


class MatchRepository(BaseRepository[Match]):
    """Data access layer for the matches table."""

    def __init__(self, db: AsyncSession) -> None:
        super().__init__(Match, db)

    async def get_available(self, params: PageParams) -> Tuple[List[Match], int]:
        """Return paginated matches available for betting.

        'Available' means status = 'scheduled', ordered by kickoff_at ASC
        (next match first).
        """
        query = (
            select(Match)
            .where(Match.status == MatchStatus.scheduled)
            .order_by(Match.kickoff_at.asc())
        )
        return await paginate(self.db, query, params)

    async def get_by_id(self, match_id: uuid.UUID) -> Optional[Match]:  # type: ignore[override]
        """Return a match by primary key, or None."""
        result = await self.db.execute(
            select(Match).where(Match.id == match_id)
        )
        return result.scalar_one_or_none()

    async def get_by_id_or_404(self, match_id: uuid.UUID) -> Match:
        """Return a match by primary key, raising NotFoundError if absent."""
        match = await self.get_by_id(match_id)
        if match is None:
            raise NotFoundError(f"Match with id={match_id} not found.")
        return match
