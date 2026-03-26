"""Provider status → internal MatchStatus + FootballOutcome mapping.

Each provider uses its own status vocabulary.  This module centralises
all translations so that provider-specific naming never reaches beyond
the integrations layer.

Usage::

    from app.integrations.status_mapper import (
        map_api_football_status,
        derive_outcome,
        is_completed_api_football_status,
    )
"""

from __future__ import annotations

from typing import Optional

from app.models.enums import FootballOutcome, MatchStatus

# ---------------------------------------------------------------------------
# API-Football  (api-sports.io / RapidAPI)
# Short-status codes: https://www.api-football.com/documentation-v3#tag/Fixtures
# ---------------------------------------------------------------------------

_API_FOOTBALL_STATUS_MAP: dict[str, MatchStatus] = {
    # Pre-match
    "NS": MatchStatus.scheduled,    # Not Started
    "TBD": MatchStatus.scheduled,   # Time To Be Defined
    # Live / in-progress
    "1H": MatchStatus.live,         # First Half, Kick Off
    "HT": MatchStatus.live,         # Halftime
    "2H": MatchStatus.live,         # Second Half, 2nd Half Started
    "ET": MatchStatus.live,         # Extra Time
    "BT": MatchStatus.live,         # Break Time (before extra time)
    "P": MatchStatus.live,          # Penalty In Progress
    "SUSP": MatchStatus.live,       # Match Suspended
    "INT": MatchStatus.live,        # Match Interrupted
    "LIVE": MatchStatus.live,       # In Play
    # Finished
    "FT": MatchStatus.completed,    # Match Finished (Regular Time)
    "AET": MatchStatus.completed,   # Match Finished (After Extra Time)
    "PEN": MatchStatus.completed,   # Match Finished (After Penalty)
    "AWD": MatchStatus.completed,   # Technical Loss (awarded to one team)
    "WO": MatchStatus.completed,    # WalkOver
    # Not played
    "PST": MatchStatus.postponed,   # Match Postponed
    "CANC": MatchStatus.cancelled,  # Match Cancelled
    "ABD": MatchStatus.abandoned,   # Match Abandoned
}

# Statuses where a final score is available and should be stored
_API_FOOTBALL_COMPLETED_STATUSES: frozenset[str] = frozenset(
    {"FT", "AET", "PEN", "AWD", "WO"}
)


def map_api_football_status(raw_status: str) -> MatchStatus:
    """Map an API-Football short status code to an internal :class:`MatchStatus`.

    Unknown codes fall back to ``MatchStatus.scheduled`` so an unexpected
    provider value never raises during ingestion — it is logged as a warning
    by the sync service.

    Args:
        raw_status: Short code from API-Football (e.g. ``"NS"``, ``"FT"``).

    Returns:
        Corresponding :class:`~app.models.enums.MatchStatus`.
    """
    return _API_FOOTBALL_STATUS_MAP.get(raw_status.strip().upper(), MatchStatus.scheduled)


def derive_outcome(
    home_score: Optional[int],
    away_score: Optional[int],
) -> Optional[FootballOutcome]:
    """Derive :class:`FootballOutcome` from a pair of final scores.

    Returns ``None`` when either score is absent (match not yet complete).

    Args:
        home_score: Goals scored by the home team.
        away_score: Goals scored by the away team.

    Returns:
        ``home_win``, ``away_win``, or ``draw``; or ``None``.
    """
    if home_score is None or away_score is None:
        return None
    if home_score > away_score:
        return FootballOutcome.home_win
    if away_score > home_score:
        return FootballOutcome.away_win
    return FootballOutcome.draw


def is_completed_api_football_status(raw_status: str) -> bool:
    """Return ``True`` when the API-Football status signals a final score is available."""
    return raw_status.strip().upper() in _API_FOOTBALL_COMPLETED_STATUSES
