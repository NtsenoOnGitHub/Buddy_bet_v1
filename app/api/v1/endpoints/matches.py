"""Match endpoints.

GET /matches       — paginated, filterable list of matches.
GET /matches/{id}  — single match detail.

Query parameters for GET /matches:
  status      — filter by MatchStatus value (e.g. 'scheduled', 'completed').
                 Omit to return all statuses.
  competition — case-insensitive substring match on competition name
                (e.g. 'premier' returns 'Premier League' matches).
                Omit to return all competitions.
  page        — 1-based page number (default: 1)
  page_size   — results per page, max 100 (default: 20)

Each match in the response includes is_betting_open: a computed boolean that
indicates whether the bet-creation window is still open.  A match can be
'scheduled' but past the kickoff cutoff — in that case is_betting_open=false
even though status='scheduled'.
"""

from __future__ import annotations

import uuid
from typing import Optional

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user, get_db
from app.models.enums import MatchStatus
from app.models.user import User
from app.schemas.common import PageParams
from app.schemas.match import MatchListResponse, MatchResponse
from app.services.match_service import MatchService

router = APIRouter()


@router.get(
    "",
    response_model=MatchListResponse,
    status_code=status.HTTP_200_OK,
    summary="List matches",
    description=(
        "Returns a paginated list of matches. "
        "Filter by status and/or competition. "
        "Sorted by kickoff time ascending (soonest first). "
        "Each match includes `is_betting_open` indicating whether "
        "the bet-creation window is still active."
    ),
)
async def list_matches(
    page: int = Query(default=1, ge=1, description="Page number (1-based)"),
    page_size: int = Query(default=20, ge=1, le=100, description="Results per page"),
    status_filter: Optional[MatchStatus] = Query(
        default=None,
        alias="status",
        description=(
            "Filter by match status. "
            "Omit to return all statuses. "
            "Use 'scheduled' to see only matches open for betting."
        ),
    ),
    competition: Optional[str] = Query(
        default=None,
        min_length=1,
        max_length=200,
        description=(
            "Case-insensitive substring filter on competition name. "
            "E.g. 'premier' matches 'Premier League'."
        ),
    ),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> MatchListResponse:
    service = MatchService(db)
    params = PageParams(page=page, page_size=page_size)
    return await service.get_matches(
        params,
        status=status_filter,
        competition=competition,
    )


@router.get(
    "/{match_id}",
    response_model=MatchResponse,
    status_code=status.HTTP_200_OK,
    summary="Get match detail",
    description=(
        "Returns full details for a single match by its ID, "
        "including the computed `is_betting_open` field."
    ),
)
async def get_match(
    match_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> MatchResponse:
    service = MatchService(db)
    return await service.get_match_by_id(match_id)
