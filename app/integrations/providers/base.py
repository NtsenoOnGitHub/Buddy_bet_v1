"""Provider abstraction for sports data.

BaseSportsProvider defines the interface all concrete provider clients must
implement.  ProviderMatchPayload is the normalized DTO that flows from any
provider into the sync service — provider-specific naming never leaks further.
"""

from __future__ import annotations

import abc
import dataclasses
from datetime import datetime
from typing import Optional

from app.models.enums import FootballOutcome, MatchStatus


@dataclasses.dataclass(frozen=True)
class ProviderMatchPayload:
    """Normalized fixture/result from any sports data provider.

    Attributes:
        external_id:      Provider-unique fixture identifier.
                          Used as the deduplication key in the matches table.
        provider_name:    Stable identifier for the source provider
                          (e.g. ``"api_football"``).
        home_team:        Home team name as returned by the provider.
        away_team:        Away team name as returned by the provider.
        competition:      Competition / league name as returned by the provider.
        kickoff_at:       Kickoff time in UTC.
        raw_status:       Raw provider status string (e.g. ``"FT"``, ``"NS"``).
        internal_status:  Mapped internal :class:`~app.models.enums.MatchStatus`.
        home_score:       Final home score; ``None`` if match is not yet complete.
        away_score:       Final away score; ``None`` if match is not yet complete.
        internal_outcome: Derived :class:`~app.models.enums.FootballOutcome`;
                          ``None`` if the match has not finished.
    """

    external_id: str
    provider_name: str
    home_team: str
    away_team: str
    competition: str
    kickoff_at: datetime
    raw_status: str
    internal_status: MatchStatus
    home_score: Optional[int] = None
    away_score: Optional[int] = None
    internal_outcome: Optional[FootballOutcome] = None


class BaseSportsProvider(abc.ABC):
    """Abstract interface for sports data providers.

    Each subclass handles authentication, HTTP transport, rate-limit handling,
    and response normalization for a specific external API.
    """

    @property
    @abc.abstractmethod
    def provider_name(self) -> str:
        """Stable lowercase identifier for this provider (e.g. ``"api_football"``)."""

    @abc.abstractmethod
    async def fetch_upcoming_fixtures(
        self,
        days_ahead: int = 7,
        league_ids: Optional[list[int]] = None,
    ) -> list[ProviderMatchPayload]:
        """Fetch fixtures that have not yet been played.

        Args:
            days_ahead:  How many calendar days ahead to query.
            league_ids:  Provider-specific competition IDs to include.
                         ``None`` uses the provider/config default.

        Returns:
            Normalized fixture payloads, typically with
            ``internal_status == MatchStatus.scheduled``.
        """

    @abc.abstractmethod
    async def fetch_results(
        self,
        days_back: int = 2,
        league_ids: Optional[list[int]] = None,
    ) -> list[ProviderMatchPayload]:
        """Fetch recently completed fixtures with final scores.

        Args:
            days_back:   How many calendar days back to query.
            league_ids:  Provider-specific competition IDs to include.
                         ``None`` uses the provider/config default.

        Returns:
            Normalized fixture payloads with
            ``internal_status == MatchStatus.completed``.
        """

    @abc.abstractmethod
    async def fetch_live_fixtures(
        self,
        league_ids: Optional[list[int]] = None,
    ) -> list[ProviderMatchPayload]:
        """Fetch fixtures currently in progress.

        Args:
            league_ids:  Provider-specific competition IDs to include.
                         ``None`` uses the provider/config default.

        Returns:
            Normalized fixture payloads with
            ``internal_status == MatchStatus.live``.
        """
