"""Match service — read-only access to the match data.

Matches are written by the Fixture Module (not part of this MVP scope).
This service provides the read-side for API endpoints and bet validation.

Design note — external provider integration:
  The matches table is the single source of truth for fixture data.
  When an external sports data provider is integrated, ingestion jobs will
  write Match rows (using the external_id as an idempotency key) and update
  status / scores.  This service remains unchanged — it simply reads whatever
  is in the table.
"""

from __future__ import annotations

import uuid
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import MatchStatus
from app.repositories.match_repository import MatchRepository
from app.schemas.common import PageParams
from app.schemas.match import MatchListResponse, MatchResponse


class MatchService:
    """Read-only access to the matches table."""

    def __init__(self, db: AsyncSession) -> None:
        self._repo = MatchRepository(db)

    async def get_matches(
        self,
        params: PageParams,
        status: Optional[MatchStatus] = None,
        competition: Optional[str] = None,
    ) -> MatchListResponse:
        """Return a filtered, paginated list of matches.

        Args:
            params: Pagination parameters.
            status: Restrict results to a single MatchStatus.  If None, all
                    statuses are returned.  Pass MatchStatus.scheduled to get
                    only the matches that are eligible for new bets.
            competition: Case-insensitive substring filter on competition name.
                         'premier' matches 'Premier League', etc.

        Returns:
            Paginated MatchListResponse.  Each item includes is_betting_open,
            which reflects whether the kickoff cutoff has been reached — a
            match can be 'scheduled' but past the cutoff and therefore closed
            for new bets.
        """
        matches, total = await self._repo.get_filtered(
            params,
            status=status,
            competition=competition,
        )
        items = [MatchResponse.model_validate(m) for m in matches]
        return MatchListResponse.create(
            items=items,
            total=total,
            page=params.page,
            page_size=params.page_size,
        )

    async def get_available_matches(self, params: PageParams) -> MatchListResponse:
        """Return a paginated list of scheduled (upcoming) matches.

        Convenience wrapper around get_matches(status=scheduled) kept for
        backward compatibility with any callers that reference it by name.

        Only 'scheduled' matches are returned — matches in live, completed,
        postponed, cancelled, or abandoned status are excluded.
        """
        return await self.get_matches(params, status=MatchStatus.scheduled)

    async def get_match_by_id(self, match_id: uuid.UUID) -> MatchResponse:
        """Return a single match by ID.

        Args:
            match_id: The UUID of the match to retrieve.

        Returns:
            MatchResponse for the requested match, including is_betting_open.

        Raises:
            NotFoundError: If no match with the given ID exists.
        """
        match = await self._repo.get_by_id_or_404(match_id)
        return MatchResponse.model_validate(match)
