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

        Used internally by BetService for match validation. For the public
        listing API use get_filtered() which supports status/competition filters.
        """
        query = (
            select(Match)
            .where(Match.status == MatchStatus.scheduled)
            .order_by(Match.kickoff_at.asc())
        )
        return await paginate(self.db, query, params)

    async def get_filtered(
        self,
        params: PageParams,
        status: Optional[MatchStatus] = None,
        competition: Optional[str] = None,
    ) -> Tuple[List[Match], int]:
        """Return a paginated, filtered match list ordered by kickoff_at ASC.

        Args:
            params: Pagination parameters.
            status: If provided, restrict to matches with this exact status.
                    If None, all statuses are returned.
            competition: If provided, case-insensitive substring match against
                         the competition column (e.g. "premier" matches
                         "Premier League").  If None, all competitions returned.

        Returns:
            Tuple of (list of Match, total row count before pagination).

        Design note:
            All ordering is by kickoff_at ASC — next-to-kick-off first.
            The caller controls status scope; betting eligibility is a separate
            concern expressed via MatchResponse.is_betting_open.
        """
        query = select(Match)

        if status is not None:
            query = query.where(Match.status == status)

        if competition is not None:
            query = query.where(Match.competition.ilike(f"%{competition}%"))

        query = query.order_by(Match.kickoff_at.asc())
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

    async def get_by_external_id(self, external_id: str) -> Optional[Match]:
        """Return a match by provider external_id, or None if not found."""
        result = await self.db.execute(
            select(Match).where(Match.external_id == external_id)
        )
        return result.scalar_one_or_none()

    async def get_for_update(self, match_id: uuid.UUID) -> Match:
        """Return a match with SELECT FOR UPDATE.

        Must be called before updating match result or status to prevent
        concurrent admin requests from producing conflicting updates.

        Raises:
            NotFoundError: If no match exists for this ID.
        """
        result = await self.db.execute(
            select(Match).where(Match.id == match_id).with_for_update()
        )
        match = result.scalar_one_or_none()
        if match is None:
            raise NotFoundError(f"Match with id={match_id} not found.")
        return match
