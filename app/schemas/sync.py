"""Pydantic schemas for match sync request/response."""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field


class SyncRequest(BaseModel):
    """Optional overrides for a manual sync trigger."""

    days_ahead: Optional[int] = Field(
        default=None,
        ge=1,
        le=30,
        description="Override: how many days ahead to fetch upcoming fixtures.",
    )
    days_back: Optional[int] = Field(
        default=None,
        ge=1,
        le=14,
        description="Override: how many days back to fetch recent results.",
    )
    league_ids: Optional[List[int]] = Field(
        default=None,
        description=(
            "Override: specific provider league IDs to sync. "
            "Omit to use the configured defaults."
        ),
    )


class SyncResultResponse(BaseModel):
    """Summary of a completed sync run."""

    provider: str
    run_at: datetime
    fixtures_fetched: int
    created: int
    updated: int
    skipped: int
    failed: int
    errors: List[str]
