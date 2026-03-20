"""Match endpoints.

GET /matches     — paginated list of available (scheduled) matches.
GET /matches/{id} — single match detail.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user, get_db
from app.models.user import User
from app.schemas.match import MatchListResponse, MatchResponse
from app.schemas.common import PageParams
from app.services.match_service import MatchService

router = APIRouter()


@router.get(
    "",
    response_model=MatchListResponse,
    status_code=status.HTTP_200_OK,
    summary="List available matches",
    description="Returns a paginated list of scheduled (upcoming) matches available for betting.",
)
async def list_matches(
    page: int = Query(default=1, ge=1, description="Page number (1-based)"),
    page_size: int = Query(default=20, ge=1, le=100, description="Results per page"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> MatchListResponse:
    service = MatchService(db)
    params = PageParams(page=page, page_size=page_size)
    return await service.get_available_matches(params)


@router.get(
    "/{match_id}",
    response_model=MatchResponse,
    status_code=status.HTTP_200_OK,
    summary="Get match detail",
    description="Returns full details for a single match by its ID.",
)
async def get_match(
    match_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> MatchResponse:
    service = MatchService(db)
    return await service.get_match_by_id(match_id)
