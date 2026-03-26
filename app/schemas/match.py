"""Match schemas — list and detail responses."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from pydantic import BaseModel, ConfigDict, computed_field

from app.models.enums import FootballOutcome, MatchStatus
from app.schemas.common import PaginatedResponse


class MatchResponse(BaseModel):
    """Single match detail response."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    external_id: str
    home_team: str
    away_team: str
    competition: str
    kickoff_at: datetime
    status: MatchStatus
    result_home_score: Optional[int] = None
    result_away_score: Optional[int] = None
    outcome: Optional[FootballOutcome] = None
    result_confirmed_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    @computed_field  # type: ignore[misc]
    @property
    def is_betting_open(self) -> bool:
        """True if this match currently accepts new bets.

        A match is open for betting when:
          1. Its status is 'scheduled' (not live, completed, cancelled, etc.)
          2. The current time is before kickoff minus BET_CREATION_CUTOFF_MINUTES.

        This mirrors the exact check enforced by BetService.create_bet so the
        client and the server are always in agreement on betting eligibility.
        Settings are read from the singleton — no extra DB round-trip needed.
        """
        if self.status != MatchStatus.scheduled:
            return False

        # Import here to avoid a circular dependency at module load time.
        from app.core.config import get_settings

        settings = get_settings()
        cutoff_dt = self.kickoff_at - timedelta(
            minutes=settings.bet_creation_cutoff_minutes
        )
        return datetime.now(tz=timezone.utc) < cutoff_dt


# Paginated list alias for consistency
MatchListResponse = PaginatedResponse[MatchResponse]
