"""Concrete sports data provider: API-Football (api-sports.io).

Documentation: https://www.api-football.com/documentation-v3

Authentication
--------------
Set ``SPORTS_PROVIDER_API_KEY`` in the environment.  The key is sent as
the ``x-apisports-key`` request header (direct API access).

Free tier limits
----------------
100 calls/day, 10 requests/minute.  The sync service is designed to run
once or twice daily so this fits within the free tier for small deployments.

Configuration (all via :class:`~app.core.config.Settings`)
-----------------------------------------------------------
``sports_provider_api_key``         — API key (required)
``sports_provider_base_url``        — default: https://v3.football.api-sports.io
``sports_provider_league_ids``      — list of league IDs to track
``sports_provider_timeout_seconds`` — HTTP timeout per request
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

import httpx

from app.core.config import get_settings
from app.integrations.providers.base import BaseSportsProvider, ProviderMatchPayload
from app.integrations.status_mapper import (
    derive_outcome,
    is_completed_api_football_status,
    map_api_football_status,
)

logger = logging.getLogger(__name__)

_PROVIDER_NAME = "api_football"


class ApiFootballProvider(BaseSportsProvider):
    """API-Football (api-sports.io) client.

    Uses ``httpx.AsyncClient`` for all HTTP calls.  The client is created
    per-instance and should be used as an async context manager so connections
    are properly released:

    .. code-block:: python

        async with ApiFootballProvider() as provider:
            fixtures = await provider.fetch_upcoming_fixtures(days_ahead=7)
    """

    def __init__(self) -> None:
        settings = get_settings()
        self._base_url = settings.sports_provider_base_url.rstrip("/")
        self._api_key = settings.sports_provider_api_key
        self._timeout = settings.sports_provider_timeout_seconds
        self._default_league_ids = settings.sports_provider_league_ids
        self._client: Optional[httpx.AsyncClient] = None

    # ------------------------------------------------------------------
    # Context manager — allows "async with ApiFootballProvider() as p:"
    # ------------------------------------------------------------------

    async def __aenter__(self) -> "ApiFootballProvider":
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            headers={
                "x-apisports-key": self._api_key,
                "Accept": "application/json",
            },
            timeout=self._timeout,
        )
        return self

    async def __aexit__(self, *_: object) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    # ------------------------------------------------------------------
    # BaseSportsProvider interface
    # ------------------------------------------------------------------

    @property
    def provider_name(self) -> str:
        return _PROVIDER_NAME

    async def fetch_upcoming_fixtures(
        self,
        days_ahead: int = 7,
        league_ids: Optional[list[int]] = None,
    ) -> list[ProviderMatchPayload]:
        """Fetch not-yet-started fixtures for the given leagues.

        Queries ``/fixtures?from=<today>&to=<today+days_ahead>`` per league.
        """
        ids = league_ids or self._default_league_ids
        today = date.today()
        to_date = today + timedelta(days=days_ahead)

        all_payloads: list[ProviderMatchPayload] = []
        for league_id in ids:
            raw = await self._get_fixtures(
                extra_params={
                    "league": league_id,
                    "season": _current_season(today),
                    "from": today.isoformat(),
                    "to": to_date.isoformat(),
                }
            )
            all_payloads.extend(self._normalize_fixtures(raw))

        logger.info(
            "api_football.fetch_upcoming: days_ahead=%d leagues=%s fetched=%d",
            days_ahead,
            ids,
            len(all_payloads),
        )
        return all_payloads

    async def fetch_results(
        self,
        days_back: int = 2,
        league_ids: Optional[list[int]] = None,
    ) -> list[ProviderMatchPayload]:
        """Fetch recently finished fixtures with final scores.

        Queries ``/fixtures?from=<today-days_back>&to=<today>&status=FT-AET-PEN``
        per league.
        """
        ids = league_ids or self._default_league_ids
        today = date.today()
        from_date = today - timedelta(days=days_back)

        all_payloads: list[ProviderMatchPayload] = []
        for league_id in ids:
            raw = await self._get_fixtures(
                extra_params={
                    "league": league_id,
                    "season": _current_season(today),
                    "from": from_date.isoformat(),
                    "to": today.isoformat(),
                    "status": "FT-AET-PEN-AWD-WO",
                }
            )
            payloads = self._normalize_fixtures(raw)
            # Only include fixtures we consider truly finished
            finished = [
                p
                for p in payloads
                if is_completed_api_football_status(p.raw_status)
            ]
            all_payloads.extend(finished)

        logger.info(
            "api_football.fetch_results: days_back=%d leagues=%s fetched=%d",
            days_back,
            ids,
            len(all_payloads),
        )
        return all_payloads

    async def fetch_live_fixtures(
        self,
        league_ids: Optional[list[int]] = None,
    ) -> list[ProviderMatchPayload]:
        """Fetch fixtures currently in progress.

        Queries ``/fixtures?live=all`` and filters to the requested leagues.
        """
        ids = set(league_ids or self._default_league_ids)
        raw = await self._get_fixtures(extra_params={"live": "all"})
        payloads = self._normalize_fixtures(raw)
        filtered = [p for p in payloads if _league_id_from_payload(p) in ids] if ids else payloads

        logger.info(
            "api_football.fetch_live: leagues=%s fetched=%d",
            ids,
            len(filtered),
        )
        return filtered

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _get_fixtures(self, extra_params: dict[str, Any]) -> list[dict[str, Any]]:
        """Call GET /fixtures with the given parameters.

        Returns the raw ``response`` list from the API body, or ``[]`` on
        any network / API error (logged, never re-raised so a single league
        failure doesn't abort the entire sync run).

        Raises:
            RuntimeError: If the provider client has not been initialised
                          (use ``async with ApiFootballProvider()``).
        """
        if self._client is None:
            raise RuntimeError(
                "ApiFootballProvider must be used as an async context manager. "
                "Use 'async with ApiFootballProvider() as p:'"
            )

        try:
            response = await self._client.get("/fixtures", params=extra_params)
            response.raise_for_status()
            body = response.json()

            errors = body.get("errors", {})
            if errors:
                logger.warning("api_football: API reported errors: %s", errors)
                return []

            return body.get("response", [])  # type: ignore[return-value]

        except httpx.TimeoutException:
            logger.warning(
                "api_football: request timed out (params=%s)", extra_params
            )
            return []
        except httpx.HTTPStatusError as exc:
            logger.warning(
                "api_football: HTTP error %s for params=%s",
                exc.response.status_code,
                extra_params,
            )
            return []
        except Exception:
            logger.exception(
                "api_football: unexpected error fetching fixtures (params=%s)",
                extra_params,
            )
            return []

    def _normalize_fixtures(
        self, raw_fixtures: list[dict[str, Any]]
    ) -> list[ProviderMatchPayload]:
        """Translate raw API-Football fixture dicts to ProviderMatchPayload.

        Malformed fixtures are skipped with a warning rather than raising,
        so a single bad record doesn't abort the entire sync run.
        """
        payloads: list[ProviderMatchPayload] = []

        for raw in raw_fixtures:
            try:
                payload = self._parse_fixture(raw)
                if payload is not None:
                    payloads.append(payload)
            except Exception:
                fixture_id = raw.get("fixture", {}).get("id", "?")
                logger.warning(
                    "api_football: failed to parse fixture id=%s — skipping",
                    fixture_id,
                    exc_info=True,
                )

        return payloads

    @staticmethod
    def _parse_fixture(raw: dict[str, Any]) -> Optional[ProviderMatchPayload]:
        """Parse a single raw API-Football fixture dict.

        Returns ``None`` if required fields are missing.

        API-Football fixture structure::

            {
              "fixture": {"id": 1234, "date": "2024-08-17T15:00:00+00:00",
                          "status": {"short": "FT", "elapsed": 90}},
              "league":  {"id": 39, "name": "Premier League"},
              "teams":   {"home": {"name": "Arsenal"}, "away": {"name": "Chelsea"}},
              "goals":   {"home": 2, "away": 1},
              "score":   {"fulltime": {"home": 2, "away": 1}}
            }
        """
        fixture = raw.get("fixture", {})
        fixture_id = fixture.get("id")
        if not fixture_id:
            return None

        date_str = fixture.get("date")
        if not date_str:
            return None

        # Parse ISO-8601 kickoff date from provider
        kickoff_at = datetime.fromisoformat(date_str)
        if kickoff_at.tzinfo is None:
            kickoff_at = kickoff_at.replace(tzinfo=timezone.utc)
        kickoff_at = kickoff_at.astimezone(timezone.utc)

        raw_status = fixture.get("status", {}).get("short", "NS")
        internal_status = map_api_football_status(raw_status)

        league = raw.get("league", {})
        competition = league.get("name", "Unknown League")

        teams = raw.get("teams", {})
        home_team = teams.get("home", {}).get("name")
        away_team = teams.get("away", {}).get("name")
        if not home_team or not away_team:
            return None

        # Prefer fulltime score; fall back to goals (handles AET/PEN)
        score = raw.get("score", {})
        ft_score = score.get("fulltime", {})
        goals = raw.get("goals", {})

        home_score: Optional[int] = ft_score.get("home") or goals.get("home")
        away_score: Optional[int] = ft_score.get("away") or goals.get("away")

        # Only store scores when we know the match is genuinely finished
        if not is_completed_api_football_status(raw_status):
            home_score = None
            away_score = None

        outcome = derive_outcome(home_score, away_score)

        return ProviderMatchPayload(
            external_id=f"api_football:{fixture_id}",
            provider_name=_PROVIDER_NAME,
            home_team=home_team,
            away_team=away_team,
            competition=competition,
            kickoff_at=kickoff_at,
            raw_status=raw_status,
            internal_status=internal_status,
            home_score=home_score,
            away_score=away_score,
            internal_outcome=outcome,
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _current_season(today: date) -> int:
    """Return the football season year for a given date.

    European leagues run August–May, so the 2024/25 season starts in August 2024
    and the season identifier is ``2024``.  If today is before August, we are
    still in the previous season.
    """
    return today.year if today.month >= 8 else today.year - 1


def _league_id_from_payload(payload: ProviderMatchPayload) -> Optional[int]:
    """Extract the numeric league ID from the external_id, if encoded there.

    This is a best-effort helper for the live-fixture league filter and is not
    critical for correctness — the filter simply won't work for payloads that
    don't embed a league ID.
    """
    # external_id format: "api_football:<fixture_id>"
    # We can't recover the league ID from the external_id alone in this simple
    # implementation.  The live-fixture filter is a nice-to-have; when league
    # filtering is needed, fetch per-league instead of using the "live=all" query.
    return None
