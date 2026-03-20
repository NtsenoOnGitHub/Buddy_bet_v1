"""Match service — read-only access to the match data.

Matches are written by the Fixture Module (not part of this MVP scope).
This service provides the read-side for API endpoints and bet validation.
"""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.match_repository import MatchRepository
from app.schemas.common import PageParams
from app.schemas.match import MatchListResponse, MatchResponse


class MatchService:
    """Read-only access to the matches table."""

    def __init__(self, db: AsyncSession) -> None:
        self._repo = MatchRepository(db)

    async def get_available_matches(self, params: PageParams) -> MatchListResponse:
        """Return a paginated list of scheduled (upcoming) matches.

        Only 'scheduled' matches are returned — matches in live, completed,
        postponed, cancelled, or abandoned status are excluded from betting.

        Args:
            params: Pagination parameters.

        Returns:
            Paginated list of scheduled matches ordered by kickoff_at ASC.
        """
        matches, total = await self._repo.get_available(params)
        items = [MatchResponse.model_validate(m) for m in matches]
        return MatchListResponse.create(
            items=items,
            total=total,
            page=params.page,
            page_size=params.page_size,
        )

    async def get_match_by_id(self, match_id: uuid.UUID) -> MatchResponse:
        """Return a single match by ID.

        Args:
            match_id: The UUID of the match to retrieve.

        Returns:
            MatchResponse for the requested match.

        Raises:
            NotFoundError: If no match with the given ID exists.
        """
        match = await self._repo.get_by_id_or_404(match_id)
        return MatchResponse.model_validate(match)
