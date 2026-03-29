"""Concrete sports data provider: Football-Data.org (api.football-data.org/v4).

Documentation: https://www.football-data.org/documentation/quickstart

Authentication
--------------
Set ``SPORTS_PROVIDER_API_KEY`` in the environment.  The key is sent as
the ``X-Auth-Token`` request header.

Free tier limits
----------------
10 requests/minute.  Covers top competitions with current season data.

Default competition IDs (Football-Data.org)
-------------------------------------------
2021 — Premier League
2014 — La Liga
2002 — Bundesliga
2019 — Serie A
2015 — Ligue 1
2001 — UEFA Champions League
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
    is_completed_football_data_org_status,
    map_football_data_org_status,
)

logger = logging.getLogger(__name__)

_PROVIDER_NAME = "football_data_org"
_BASE_URL = "https://api.football-data.org/v4"

# Default competition IDs for the free tier
_DEFAULT_COMPETITION_IDS = [2021, 2014, 2002, 2019, 2015, 2001]


class FootballDataOrgProvider(BaseSportsProvider):
    """Football-Data.org API v4 client."""

    def __init__(self) -> None:
        settings = get_settings()
        self._api_key = settings.sports_provider_api_key
        self._timeout = settings.sports_provider_timeout_seconds
        self._default_competition_ids = (
            settings.sports_provider_league_ids or _DEFAULT_COMPETITION_IDS
        )
        self._client: Optional[httpx.AsyncClient] = None

    async def __aenter__(self) -> "FootballDataOrgProvider":
        self._client = httpx.AsyncClient(
            base_url=_BASE_URL,
            headers={
                "X-Auth-Token": self._api_key,
                "Accept": "application/json",
            },
            timeout=self._timeout,
        )
        return self

    async def __aexit__(self, *_: object) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    @property
    def provider_name(self) -> str:
        return _PROVIDER_NAME

    async def fetch_upcoming_fixtures(
        self,
        days_ahead: int = 7,
        league_ids: Optional[list[int]] = None,
    ) -> list[ProviderMatchPayload]:
        ids = league_ids or self._default_competition_ids
        today = date.today()
        to_date = today + timedelta(days=days_ahead)

        all_payloads: list[ProviderMatchPayload] = []
        for competition_id in ids:
            raw = await self._get_matches(
                competition_id=competition_id,
                extra_params={
                    "dateFrom": today.isoformat(),
                    "dateTo": to_date.isoformat(),
                    "status": "SCHEDULED,TIMED",
                },
            )
            all_payloads.extend(self._normalize_matches(raw, competition_id))

        logger.info(
            "football_data_org.fetch_upcoming: days_ahead=%d competitions=%s fetched=%d",
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
        ids = league_ids or self._default_competition_ids
        today = date.today()
        from_date = today - timedelta(days=days_back)

        all_payloads: list[ProviderMatchPayload] = []
        for competition_id in ids:
            raw = await self._get_matches(
                competition_id=competition_id,
                extra_params={
                    "dateFrom": from_date.isoformat(),
                    "dateTo": today.isoformat(),
                    "status": "FINISHED",
                },
            )
            payloads = self._normalize_matches(raw, competition_id)
            finished = [
                p for p in payloads
                if is_completed_football_data_org_status(p.raw_status)
            ]
            all_payloads.extend(finished)

        logger.info(
            "football_data_org.fetch_results: days_back=%d competitions=%s fetched=%d",
            days_back,
            ids,
            len(all_payloads),
        )
        return all_payloads

    async def fetch_live_fixtures(
        self,
        league_ids: Optional[list[int]] = None,
    ) -> list[ProviderMatchPayload]:
        ids = set(league_ids or self._default_competition_ids)

        all_payloads: list[ProviderMatchPayload] = []
        for competition_id in ids:
            raw = await self._get_matches(
                competition_id=competition_id,
                extra_params={"status": "IN_PLAY,PAUSED"},
            )
            all_payloads.extend(self._normalize_matches(raw, competition_id))

        logger.info(
            "football_data_org.fetch_live: competitions=%s fetched=%d",
            ids,
            len(all_payloads),
        )
        return all_payloads

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _get_matches(
        self,
        competition_id: int,
        extra_params: dict[str, Any],
    ) -> list[dict[str, Any]]:
        if self._client is None:
            raise RuntimeError(
                "FootballDataOrgProvider must be used as an async context manager."
            )
        try:
            response = await self._client.get(
                f"/competitions/{competition_id}/matches",
                params=extra_params,
            )
            if response.status_code == 429:
                logger.warning("football_data_org: rate limit hit for competition %d", competition_id)
                return []
            response.raise_for_status()
            body = response.json()
            return body.get("matches", [])

        except httpx.TimeoutException:
            logger.warning("football_data_org: request timed out (competition=%d)", competition_id)
            return []
        except httpx.HTTPStatusError as exc:
            logger.warning(
                "football_data_org: HTTP %s for competition=%d",
                exc.response.status_code,
                competition_id,
            )
            return []
        except Exception:
            logger.exception("football_data_org: unexpected error (competition=%d)", competition_id)
            return []

    def _normalize_matches(
        self,
        raw_matches: list[dict[str, Any]],
        competition_id: int,
    ) -> list[ProviderMatchPayload]:
        payloads: list[ProviderMatchPayload] = []
        for raw in raw_matches:
            try:
                payload = self._parse_match(raw, competition_id)
                if payload is not None:
                    payloads.append(payload)
            except Exception:
                match_id = raw.get("id", "?")
                logger.warning(
                    "football_data_org: failed to parse match id=%s — skipping",
                    match_id,
                    exc_info=True,
                )
        return payloads

    @staticmethod
    def _parse_match(raw: dict[str, Any], competition_id: int) -> Optional[ProviderMatchPayload]:
        match_id = raw.get("id")
        if not match_id:
            return None

        utc_date = raw.get("utcDate")
        if not utc_date:
            return None

        kickoff_at = datetime.fromisoformat(utc_date.replace("Z", "+00:00"))
        if kickoff_at.tzinfo is None:
            kickoff_at = kickoff_at.replace(tzinfo=timezone.utc)
        kickoff_at = kickoff_at.astimezone(timezone.utc)

        raw_status = raw.get("status", "SCHEDULED")
        internal_status = map_football_data_org_status(raw_status)

        competition = raw.get("competition", {}).get("name", "Unknown Competition")

        home_team = raw.get("homeTeam", {}).get("name")
        away_team = raw.get("awayTeam", {}).get("name")
        if not home_team or not away_team:
            return None

        home_score: Optional[int] = None
        away_score: Optional[int] = None

        if is_completed_football_data_org_status(raw_status):
            score = raw.get("score", {})
            ft = score.get("fullTime", {})
            home_score = ft.get("home")
            away_score = ft.get("away")

        outcome = derive_outcome(home_score, away_score)

        return ProviderMatchPayload(
            external_id=f"football_data_org:{match_id}",
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
