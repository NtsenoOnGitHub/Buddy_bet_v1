"""Admin match sync endpoints.

POST /api/v1/admin/sync/upcoming — pull upcoming fixtures from provider
POST /api/v1/admin/sync/results  — pull recent results from provider
POST /api/v1/admin/sync/live     — pull currently live fixtures

All routes require admin role.
If the provider is disabled (SPORTS_PROVIDER_ENABLED=false), the endpoints
return a clear 503 instead of silently succeeding.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.dependencies import get_current_admin, get_db
from app.integrations.providers.api_football import ApiFootballProvider
from app.integrations.providers.football_data_org import FootballDataOrgProvider
from app.integrations.providers.base import BaseSportsProvider
from app.integrations.sync_service import MatchSyncService
from app.models.user import User
from app.schemas.sync import SyncRequest, SyncResultResponse

logger = logging.getLogger(__name__)
router = APIRouter()
settings = get_settings()


def _get_provider() -> BaseSportsProvider:
    """Return the configured sports provider instance."""
    if settings.sports_provider == "football_data_org":
        return FootballDataOrgProvider()
    return ApiFootballProvider()


def _require_provider_enabled() -> None:
    """Raise HTTP 503 if the provider is disabled via config."""
    if not settings.sports_provider_enabled:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "Sports provider sync is disabled. "
                "Set SPORTS_PROVIDER_ENABLED=true and SPORTS_PROVIDER_API_KEY "
                "to enable fixture ingestion."
            ),
        )


@router.post(
    "/upcoming",
    response_model=SyncResultResponse,
    status_code=status.HTTP_200_OK,
    summary="Sync upcoming fixtures",
    description=(
        "Pull upcoming fixtures from the configured sports data provider "
        "and upsert them into the internal matches table. "
        "Creates new fixtures and updates existing ones (kickoff time, teams, "
        "competition, status). "
        "Requires admin role and SPORTS_PROVIDER_ENABLED=true."
    ),
)
async def sync_upcoming(
    body: SyncRequest = Depends(),
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(get_current_admin),
) -> SyncResultResponse:
    _require_provider_enabled()

    days_ahead = body.days_ahead or settings.sports_provider_sync_days_ahead
    league_ids = body.league_ids  # None = use provider/config defaults

    async with _get_provider() as provider:
        svc = MatchSyncService(db, provider)
        result = await svc.sync_upcoming(
            days_ahead=days_ahead, league_ids=league_ids
        )

    return SyncResultResponse(
        provider=result.provider,
        run_at=result.run_at,
        fixtures_fetched=result.fixtures_fetched,
        created=result.created,
        updated=result.updated,
        skipped=result.skipped,
        failed=result.failed,
        errors=result.errors,
    )


@router.post(
    "/results",
    response_model=SyncResultResponse,
    status_code=status.HTTP_200_OK,
    summary="Sync recent results",
    description=(
        "Pull recently completed fixtures from the provider and update "
        "internal match records with final scores and outcome. "
        "Does NOT trigger settlement — admin confirm-result is still required. "
        "Requires admin role and SPORTS_PROVIDER_ENABLED=true."
    ),
)
async def sync_results(
    body: SyncRequest = Depends(),
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(get_current_admin),
) -> SyncResultResponse:
    _require_provider_enabled()

    days_back = body.days_back or settings.sports_provider_sync_days_back
    league_ids = body.league_ids

    async with _get_provider() as provider:
        svc = MatchSyncService(db, provider)
        result = await svc.sync_results(
            days_back=days_back, league_ids=league_ids
        )

    return SyncResultResponse(
        provider=result.provider,
        run_at=result.run_at,
        fixtures_fetched=result.fixtures_fetched,
        created=result.created,
        updated=result.updated,
        skipped=result.skipped,
        failed=result.failed,
        errors=result.errors,
    )


@router.post(
    "/live",
    response_model=SyncResultResponse,
    status_code=status.HTTP_200_OK,
    summary="Sync live fixtures",
    description=(
        "Pull currently in-progress fixtures and update their status to 'live'. "
        "Requires admin role and SPORTS_PROVIDER_ENABLED=true."
    ),
)
async def sync_live(
    body: SyncRequest = Depends(),
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(get_current_admin),
) -> SyncResultResponse:
    _require_provider_enabled()

    league_ids = body.league_ids

    async with _get_provider() as provider:
        svc = MatchSyncService(db, provider)
        result = await svc.sync_live(league_ids=league_ids)

    return SyncResultResponse(
        provider=result.provider,
        run_at=result.run_at,
        fixtures_fetched=result.fixtures_fetched,
        created=result.created,
        updated=result.updated,
        skipped=result.skipped,
        failed=result.failed,
        errors=result.errors,
    )
