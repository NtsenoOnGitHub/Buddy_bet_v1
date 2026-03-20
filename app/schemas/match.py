"""Match schemas — list and detail responses."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict

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


# Paginated list alias for consistency
MatchListResponse = PaginatedResponse[MatchResponse]
