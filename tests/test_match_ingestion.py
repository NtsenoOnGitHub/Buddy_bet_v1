"""Tests for the match ingestion / synchronisation layer.

Coverage
--------
1.  Status mapper — API-Football status codes → internal MatchStatus
2.  Outcome derivation from scores
3.  Provider payload parsing (happy path + malformed input)
4.  Sync service: new fixture creation
5.  Sync service: existing fixture update (kickoff change, status, result)
6.  Sync service: duplicate prevention (idempotency)
7.  Sync service: result update only when not yet admin-confirmed
8.  Sync service: partial provider failure (one bad payload, others succeed)
9.  Sync service: provider HTTP error (graceful degradation)
10. Sync service: match listing / betting eligibility still works after sync

All tests mock the provider client; no real HTTP calls are made.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.providers.api_football import ApiFootballProvider
from app.integrations.providers.base import BaseSportsProvider, ProviderMatchPayload
from app.integrations.status_mapper import (
    derive_outcome,
    is_completed_api_football_status,
    map_api_football_status,
)
from app.integrations.sync_service import MatchSyncService, SyncResult
from app.models.enums import FootballOutcome, MatchStatus
from app.models.match import Match
from tests.conftest import create_match, fund_wallet, make_admin, register_user


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _future_kickoff(hours: int = 48) -> datetime:
    return datetime.now(tz=timezone.utc) + timedelta(hours=hours)


def _make_payload(
    *,
    external_id: str = "api_football:99999",
    home_team: str = "Arsenal",
    away_team: str = "Chelsea",
    competition: str = "Premier League",
    kickoff_hours: int = 48,
    raw_status: str = "NS",
    home_score: Optional[int] = None,
    away_score: Optional[int] = None,
) -> ProviderMatchPayload:
    """Build a ProviderMatchPayload for testing."""
    internal_status = map_api_football_status(raw_status)
    outcome = derive_outcome(home_score, away_score)
    return ProviderMatchPayload(
        external_id=external_id,
        provider_name="api_football",
        home_team=home_team,
        away_team=away_team,
        competition=competition,
        kickoff_at=_future_kickoff(kickoff_hours),
        raw_status=raw_status,
        internal_status=internal_status,
        home_score=home_score,
        away_score=away_score,
        internal_outcome=outcome,
    )


class _MockProvider(BaseSportsProvider):
    """Minimal in-memory provider for testing."""

    def __init__(self, payloads: list[ProviderMatchPayload]) -> None:
        self._payloads = payloads

    @property
    def provider_name(self) -> str:
        return "mock_provider"

    async def fetch_upcoming_fixtures(self, days_ahead=7, league_ids=None):
        return self._payloads

    async def fetch_results(self, days_back=2, league_ids=None):
        return self._payloads

    async def fetch_live_fixtures(self, league_ids=None):
        return self._payloads


# ---------------------------------------------------------------------------
# 1. Status mapper
# ---------------------------------------------------------------------------


class TestStatusMapper:
    """map_api_football_status — status code → MatchStatus."""

    def test_not_started_maps_to_scheduled(self) -> None:
        assert map_api_football_status("NS") == MatchStatus.scheduled

    def test_tbd_maps_to_scheduled(self) -> None:
        assert map_api_football_status("TBD") == MatchStatus.scheduled

    def test_first_half_maps_to_live(self) -> None:
        assert map_api_football_status("1H") == MatchStatus.live

    def test_halftime_maps_to_live(self) -> None:
        assert map_api_football_status("HT") == MatchStatus.live

    def test_second_half_maps_to_live(self) -> None:
        assert map_api_football_status("2H") == MatchStatus.live

    def test_full_time_maps_to_completed(self) -> None:
        assert map_api_football_status("FT") == MatchStatus.completed

    def test_after_extra_time_maps_to_completed(self) -> None:
        assert map_api_football_status("AET") == MatchStatus.completed

    def test_after_penalties_maps_to_completed(self) -> None:
        assert map_api_football_status("PEN") == MatchStatus.completed

    def test_postponed_maps_correctly(self) -> None:
        assert map_api_football_status("PST") == MatchStatus.postponed

    def test_cancelled_maps_correctly(self) -> None:
        assert map_api_football_status("CANC") == MatchStatus.cancelled

    def test_abandoned_maps_correctly(self) -> None:
        assert map_api_football_status("ABD") == MatchStatus.abandoned

    def test_unknown_code_falls_back_to_scheduled(self) -> None:
        assert map_api_football_status("UNKNOWN_CODE") == MatchStatus.scheduled

    def test_case_insensitive(self) -> None:
        assert map_api_football_status("ft") == MatchStatus.completed
        assert map_api_football_status("Ft") == MatchStatus.completed

    def test_is_completed_ft(self) -> None:
        assert is_completed_api_football_status("FT") is True

    def test_is_completed_ns(self) -> None:
        assert is_completed_api_football_status("NS") is False

    def test_is_completed_live(self) -> None:
        assert is_completed_api_football_status("1H") is False


# ---------------------------------------------------------------------------
# 2. Outcome derivation
# ---------------------------------------------------------------------------


class TestDeriveOutcome:
    """derive_outcome — score pair → FootballOutcome."""

    def test_home_win(self) -> None:
        assert derive_outcome(2, 1) == FootballOutcome.home_win

    def test_away_win(self) -> None:
        assert derive_outcome(0, 1) == FootballOutcome.away_win

    def test_draw(self) -> None:
        assert derive_outcome(1, 1) == FootballOutcome.draw

    def test_zero_zero_draw(self) -> None:
        assert derive_outcome(0, 0) == FootballOutcome.draw

    def test_none_home_returns_none(self) -> None:
        assert derive_outcome(None, 1) is None

    def test_none_away_returns_none(self) -> None:
        assert derive_outcome(1, None) is None

    def test_both_none_returns_none(self) -> None:
        assert derive_outcome(None, None) is None


# ---------------------------------------------------------------------------
# 3. Provider payload parsing — API-Football
# ---------------------------------------------------------------------------


class TestApiFootballParsing:
    """ApiFootballProvider._parse_fixture — raw dict → ProviderMatchPayload."""

    def _parse(self, raw: dict) -> Optional[ProviderMatchPayload]:
        return ApiFootballProvider._parse_fixture(raw)

    def _minimal_raw(self, **overrides) -> dict:
        base = {
            "fixture": {
                "id": 123456,
                "date": "2025-09-15T15:00:00+00:00",
                "status": {"short": "NS", "elapsed": None},
            },
            "league": {"id": 39, "name": "Premier League", "season": 2025},
            "teams": {
                "home": {"id": 42, "name": "Arsenal"},
                "away": {"id": 49, "name": "Chelsea"},
            },
            "goals": {"home": None, "away": None},
            "score": {"fulltime": {"home": None, "away": None}},
        }
        base.update(overrides)
        return base

    def test_parses_upcoming_fixture(self) -> None:
        payload = self._parse(self._minimal_raw())
        assert payload is not None
        assert payload.external_id == "api_football:123456"
        assert payload.provider_name == "api_football"
        assert payload.home_team == "Arsenal"
        assert payload.away_team == "Chelsea"
        assert payload.competition == "Premier League"
        assert payload.raw_status == "NS"
        assert payload.internal_status == MatchStatus.scheduled
        assert payload.home_score is None
        assert payload.away_score is None
        assert payload.internal_outcome is None

    def test_parses_completed_fixture_with_scores(self) -> None:
        raw = self._minimal_raw()
        raw["fixture"]["status"]["short"] = "FT"
        raw["goals"] = {"home": 3, "away": 1}
        raw["score"]["fulltime"] = {"home": 3, "away": 1}

        payload = self._parse(raw)
        assert payload is not None
        assert payload.internal_status == MatchStatus.completed
        assert payload.home_score == 3
        assert payload.away_score == 1
        assert payload.internal_outcome == FootballOutcome.home_win

    def test_parses_draw(self) -> None:
        raw = self._minimal_raw()
        raw["fixture"]["status"]["short"] = "FT"
        raw["goals"] = {"home": 2, "away": 2}
        raw["score"]["fulltime"] = {"home": 2, "away": 2}

        payload = self._parse(raw)
        assert payload is not None
        assert payload.internal_outcome == FootballOutcome.draw

    def test_scores_cleared_for_non_completed_status(self) -> None:
        """Scores must not be stored if the match is still in progress."""
        raw = self._minimal_raw()
        raw["fixture"]["status"]["short"] = "1H"
        raw["goals"] = {"home": 1, "away": 0}  # Interim score — should be ignored

        payload = self._parse(raw)
        assert payload is not None
        assert payload.home_score is None
        assert payload.away_score is None
        assert payload.internal_outcome is None

    def test_returns_none_when_fixture_id_missing(self) -> None:
        raw = self._minimal_raw()
        del raw["fixture"]["id"]
        assert self._parse(raw) is None

    def test_returns_none_when_date_missing(self) -> None:
        raw = self._minimal_raw()
        del raw["fixture"]["date"]
        assert self._parse(raw) is None

    def test_returns_none_when_team_names_missing(self) -> None:
        raw = self._minimal_raw()
        raw["teams"]["home"] = {}
        assert self._parse(raw) is None

    def test_kickoff_is_utc(self) -> None:
        raw = self._minimal_raw()
        raw["fixture"]["date"] = "2025-09-15T17:00:00+02:00"  # UTC+2

        payload = self._parse(raw)
        assert payload is not None
        assert payload.kickoff_at.tzinfo == timezone.utc
        assert payload.kickoff_at.hour == 15  # 17:00+02:00 = 15:00 UTC


# ---------------------------------------------------------------------------
# 4–9. MatchSyncService — integration tests with real DB
# ---------------------------------------------------------------------------


class TestMatchSyncServiceCreate:
    """Sync service creates new match rows for unknown external_ids."""

    async def test_create_new_fixture(
        self, db_session: AsyncSession
    ) -> None:
        """A fixture with an unknown external_id is inserted as a new Match."""
        payload = _make_payload(external_id="api_football:10001")
        provider = _MockProvider([payload])
        svc = MatchSyncService(db_session, provider)

        result = await svc.sync_upcoming()

        assert result.created == 1
        assert result.updated == 0
        assert result.failed == 0

        row = await db_session.execute(
            select(Match).where(Match.external_id == "api_football:10001")
        )
        match = row.scalar_one()
        assert match.home_team == "Arsenal"
        assert match.away_team == "Chelsea"
        assert match.competition == "Premier League"
        assert match.provider_name == "api_football"
        assert match.last_synced_at is not None

    async def test_create_sets_correct_status(
        self, db_session: AsyncSession
    ) -> None:
        """Created match has the internal_status from the payload."""
        payload = _make_payload(
            external_id="api_football:10002",
            raw_status="PST",  # postponed
        )
        provider = _MockProvider([payload])
        svc = MatchSyncService(db_session, provider)

        await svc.sync_upcoming()

        row = (
            await db_session.execute(
                select(Match).where(Match.external_id == "api_football:10002")
            )
        ).scalar_one()
        assert row.status == MatchStatus.postponed

    async def test_create_with_completed_fixture_stores_result(
        self, db_session: AsyncSession
    ) -> None:
        """Creating a completed fixture stores scores and outcome."""
        payload = _make_payload(
            external_id="api_football:10003",
            raw_status="FT",
            home_score=2,
            away_score=1,
        )
        provider = _MockProvider([payload])
        svc = MatchSyncService(db_session, provider)

        await svc.sync_results()

        row = (
            await db_session.execute(
                select(Match).where(Match.external_id == "api_football:10003")
            )
        ).scalar_one()
        assert row.status == MatchStatus.completed
        assert row.outcome == FootballOutcome.home_win
        assert row.result_home_score == 2
        assert row.result_away_score == 1
        assert row.result_confirmed_at is None  # NOT admin-confirmed


class TestMatchSyncServiceUpdate:
    """Sync service updates existing match rows."""

    async def _seed_match(
        self,
        db_session: AsyncSession,
        external_id: str,
        kickoff_hours: int = 48,
    ) -> Match:
        """Insert a match directly and return it."""
        match = Match(
            external_id=external_id,
            provider_name="api_football",
            home_team="Team A",
            away_team="Team B",
            competition="Test League",
            kickoff_at=_future_kickoff(kickoff_hours),
            status=MatchStatus.scheduled,
        )
        db_session.add(match)
        await db_session.flush()
        await db_session.refresh(match)
        return match

    async def test_update_kickoff_time(
        self, db_session: AsyncSession
    ) -> None:
        """Rescheduled kickoff is updated on the internal record."""
        ext_id = "api_football:20001"
        existing = await self._seed_match(db_session, ext_id, kickoff_hours=48)
        old_kickoff = existing.kickoff_at

        # Provider returns new kickoff 72 hours from now
        payload = _make_payload(
            external_id=ext_id,
            kickoff_hours=72,
        )
        provider = _MockProvider([payload])
        svc = MatchSyncService(db_session, provider)
        result = await svc.sync_upcoming()

        assert result.updated == 1
        await db_session.refresh(existing)
        assert existing.kickoff_at != old_kickoff

    async def test_update_status_scheduled_to_live(
        self, db_session: AsyncSession
    ) -> None:
        """Status can transition from scheduled to live."""
        ext_id = "api_football:20002"
        existing = await self._seed_match(db_session, ext_id)

        payload = _make_payload(external_id=ext_id, raw_status="1H")
        provider = _MockProvider([payload])
        svc = MatchSyncService(db_session, provider)
        result = await svc.sync_live()

        assert result.updated == 1
        await db_session.refresh(existing)
        assert existing.status == MatchStatus.live

    async def test_update_result_on_completion(
        self, db_session: AsyncSession
    ) -> None:
        """When provider marks match complete, scores and outcome are stored."""
        ext_id = "api_football:20003"
        existing = await self._seed_match(db_session, ext_id)

        payload = _make_payload(
            external_id=ext_id, raw_status="FT", home_score=0, away_score=2
        )
        provider = _MockProvider([payload])
        svc = MatchSyncService(db_session, provider)
        result = await svc.sync_results()

        assert result.updated == 1
        await db_session.refresh(existing)
        assert existing.status == MatchStatus.completed
        assert existing.outcome == FootballOutcome.away_win
        assert existing.result_home_score == 0
        assert existing.result_away_score == 2

    async def test_update_team_name_correction(
        self, db_session: AsyncSession
    ) -> None:
        """Provider corrections to team names are applied."""
        ext_id = "api_football:20004"
        existing = await self._seed_match(db_session, ext_id)

        payload = _make_payload(
            external_id=ext_id,
            home_team="Arsenal FC",   # Corrected name
            away_team="Chelsea FC",   # Corrected name
        )
        provider = _MockProvider([payload])
        svc = MatchSyncService(db_session, provider)
        result = await svc.sync_upcoming()

        assert result.updated == 1
        await db_session.refresh(existing)
        assert existing.home_team == "Arsenal FC"
        assert existing.away_team == "Chelsea FC"

    async def test_last_synced_at_always_updated(
        self, db_session: AsyncSession
    ) -> None:
        """last_synced_at is set on every sync pass, even for unchanged records."""
        ext_id = "api_football:20005"
        existing = await self._seed_match(db_session, ext_id)
        assert existing.last_synced_at is None

        payload = _make_payload(external_id=ext_id)
        provider = _MockProvider([payload])
        svc = MatchSyncService(db_session, provider)
        await svc.sync_upcoming()

        await db_session.refresh(existing)
        assert existing.last_synced_at is not None


class TestMatchSyncServiceIdempotency:
    """Sync is safe to run multiple times without creating duplicates."""

    async def test_double_sync_no_duplicate(
        self, db_session: AsyncSession
    ) -> None:
        """Running sync twice for the same fixture creates only one row."""
        ext_id = "api_football:30001"
        payload = _make_payload(external_id=ext_id)
        provider = _MockProvider([payload])
        svc = MatchSyncService(db_session, provider)

        await svc.sync_upcoming()
        await svc.sync_upcoming()

        rows = (
            await db_session.execute(
                select(Match).where(Match.external_id == ext_id)
            )
        ).scalars().all()
        assert len(rows) == 1

    async def test_second_sync_is_skipped_when_unchanged(
        self, db_session: AsyncSession
    ) -> None:
        """Second sync of identical data is counted as 'skipped'."""
        ext_id = "api_football:30002"
        payload = _make_payload(external_id=ext_id)
        provider = _MockProvider([payload])
        svc = MatchSyncService(db_session, provider)

        r1 = await svc.sync_upcoming()
        r2 = await svc.sync_upcoming()

        assert r1.created == 1
        assert r2.created == 0
        assert r2.skipped == 1


class TestMatchSyncServiceSafetyGuards:
    """Result sync does not overwrite admin-confirmed data."""

    async def test_result_not_overwritten_after_admin_confirmation(
        self, db_session: AsyncSession
    ) -> None:
        """Sync must not change result_* or status when result_confirmed_at is set."""
        ext_id = "api_football:40001"
        confirmed_at = datetime.now(tz=timezone.utc)

        # Insert an admin-confirmed completed match
        match = Match(
            external_id=ext_id,
            provider_name="api_football",
            home_team="Arsenal",
            away_team="Chelsea",
            competition="Premier League",
            kickoff_at=_future_kickoff(-24),  # Past kickoff
            status=MatchStatus.completed,
            outcome=FootballOutcome.home_win,
            result_home_score=2,
            result_away_score=1,
            result_confirmed_at=confirmed_at,  # Admin has confirmed!
        )
        db_session.add(match)
        await db_session.flush()

        # Provider returns a conflicting result
        payload = _make_payload(
            external_id=ext_id,
            raw_status="FT",
            home_score=0,  # Different from stored
            away_score=3,  # Different from stored
        )
        # Manually set the derived outcome in the payload
        from app.integrations.status_mapper import derive_outcome, map_api_football_status
        conflicting = ProviderMatchPayload(
            external_id=ext_id,
            provider_name="api_football",
            home_team="Arsenal",
            away_team="Chelsea",
            competition="Premier League",
            kickoff_at=_future_kickoff(-24),
            raw_status="FT",
            internal_status=MatchStatus.completed,
            home_score=0,
            away_score=3,
            internal_outcome=FootballOutcome.away_win,
        )

        provider = _MockProvider([conflicting])
        svc = MatchSyncService(db_session, provider)
        await svc.sync_results()

        await db_session.refresh(match)
        # Admin-confirmed result must not have changed
        assert match.outcome == FootballOutcome.home_win
        assert match.result_home_score == 2
        assert match.result_away_score == 1

    async def test_terminal_status_not_downgraded(
        self, db_session: AsyncSession
    ) -> None:
        """A completed match cannot be transitioned back to scheduled by sync."""
        ext_id = "api_football:40002"
        match = Match(
            external_id=ext_id,
            provider_name="api_football",
            home_team="Arsenal",
            away_team="Chelsea",
            competition="Premier League",
            kickoff_at=_future_kickoff(-24),
            status=MatchStatus.completed,
            outcome=FootballOutcome.draw,
            result_home_score=1,
            result_away_score=1,
        )
        db_session.add(match)
        await db_session.flush()

        # Provider erroneously sends "NS" for a completed match
        payload = _make_payload(external_id=ext_id, raw_status="NS")
        provider = _MockProvider([payload])
        svc = MatchSyncService(db_session, provider)
        await svc.sync_upcoming()

        await db_session.refresh(match)
        assert match.status == MatchStatus.completed  # unchanged


class TestMatchSyncServiceErrorHandling:
    """Partial failures and provider errors are handled gracefully."""

    async def test_malformed_payload_counted_as_failed(
        self, db_session: AsyncSession
    ) -> None:
        """A None payload (normalisation failure) is counted as failed."""
        # Monkey-patch the sync service to raise on the first fixture
        good = _make_payload(external_id="api_football:50001")
        provider = _MockProvider([good, good])  # Two identical — won't fail

        svc = MatchSyncService(db_session, provider)

        # Patch _upsert_fixture to raise on the first call
        original = svc._upsert_fixture
        call_count = {"n": 0}

        async def _fail_first(payload):
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise RuntimeError("Simulated parse error")
            return await original(payload)

        svc._upsert_fixture = _fail_first  # type: ignore[method-assign]
        result = await svc.sync_upcoming()

        assert result.failed == 1
        assert result.created == 1  # Second payload succeeded
        assert len(result.errors) == 1

    async def test_provider_fetch_error_returns_empty_sync_result(
        self, db_session: AsyncSession
    ) -> None:
        """If the provider raises on fetch, sync returns a graceful SyncResult."""

        class _FailingProvider(BaseSportsProvider):
            @property
            def provider_name(self) -> str:
                return "failing"

            async def fetch_upcoming_fixtures(self, **_):
                raise ConnectionError("Network unreachable")

            async def fetch_results(self, **_):
                raise ConnectionError("Network unreachable")

            async def fetch_live_fixtures(self, **_):
                raise ConnectionError("Network unreachable")

        svc = MatchSyncService(db_session, _FailingProvider())
        result = await svc.sync_upcoming()

        assert result.fixtures_fetched == 0
        assert result.created == 0
        assert result.failed == 0  # Not counted as failed — fetch itself errored
        assert len(result.errors) == 1
        assert "fetch" in result.errors[0].lower() or "failing" in result.errors[0].lower()


# ---------------------------------------------------------------------------
# 10. Integration: synced matches are visible via listing endpoint + betting
# ---------------------------------------------------------------------------


class TestSyncedMatchIntegration:
    """Synced matches appear in the API and accept bets normally."""

    async def test_synced_match_appears_in_list(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """A match inserted by sync is returned by GET /matches."""
        _, token = await register_user(
            client, email="sync_list@example.com", display_name="Sync User"
        )

        ext_id = f"api_football:sync-{uuid.uuid4().hex[:8]}"
        payload = _make_payload(external_id=ext_id, competition="Sync League")
        provider = _MockProvider([payload])
        svc = MatchSyncService(db_session, provider)
        await svc.sync_upcoming()

        resp = await client.get(
            "/api/v1/matches?competition=Sync",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        ids = [m["id"] for m in resp.json()["items"]]
        # Find the match by its external_id-derived internal ID
        row = (
            await db_session.execute(
                select(Match).where(Match.external_id == ext_id)
            )
        ).scalar_one()
        assert str(row.id) in ids

    async def test_synced_match_is_betting_open(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """A freshly synced scheduled match has is_betting_open=True."""
        _, token = await register_user(
            client, email="sync_betting@example.com", display_name="Betting User"
        )

        ext_id = f"api_football:bet-{uuid.uuid4().hex[:8]}"
        payload = _make_payload(external_id=ext_id, kickoff_hours=48)
        provider = _MockProvider([payload])
        svc = MatchSyncService(db_session, provider)
        await svc.sync_upcoming()

        row = (
            await db_session.execute(
                select(Match).where(Match.external_id == ext_id)
            )
        ).scalar_one()

        resp = await client.get(
            f"/api/v1/matches/{row.id}",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        assert resp.json()["is_betting_open"] is True

    async def test_synced_completed_match_not_betting_open(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """A synced completed match has is_betting_open=False."""
        _, token = await register_user(
            client, email="sync_done@example.com", display_name="Done User"
        )

        ext_id = f"api_football:done-{uuid.uuid4().hex[:8]}"
        payload = _make_payload(
            external_id=ext_id,
            raw_status="FT",
            home_score=2,
            away_score=0,
            kickoff_hours=-3,  # Kicked off 3 hours ago
        )
        provider = _MockProvider([payload])
        svc = MatchSyncService(db_session, provider)
        await svc.sync_results()

        row = (
            await db_session.execute(
                select(Match).where(Match.external_id == ext_id)
            )
        ).scalar_one()

        resp = await client.get(
            f"/api/v1/matches/{row.id}",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        assert resp.json()["is_betting_open"] is False

    async def test_synced_match_accepts_bet(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """A bet can be placed on a synced scheduled match."""
        user_id, token = await register_user(
            client, email="sync_create_bet@example.com", display_name="Bettor"
        )
        await fund_wallet(db_session, user_id, Decimal("500.00"))

        ext_id = f"api_football:cbet-{uuid.uuid4().hex[:8]}"
        payload = _make_payload(external_id=ext_id, kickoff_hours=48)
        provider = _MockProvider([payload])
        svc = MatchSyncService(db_session, provider)
        await svc.sync_upcoming()

        row = (
            await db_session.execute(
                select(Match).where(Match.external_id == ext_id)
            )
        ).scalar_one()

        resp = await client.post(
            "/api/v1/bets",
            json={
                "match_id": str(row.id),
                "creator_prediction": "home_win",
                "stake_amount": "100.00",
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 201
        assert resp.json()["status"] == "OPEN"

    async def test_admin_can_confirm_synced_result(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Admin can confirm-result on a match pre-populated by sync."""
        creator_id, creator_token = await register_user(
            client, email="sync_admin_creator@example.com", display_name="Creator"
        )
        opp_id, opp_token = await register_user(
            client, email="sync_admin_opp@example.com", display_name="Opp"
        )
        admin_id, admin_token = await register_user(
            client, email="sync_admin_admin@example.com", display_name="Admin"
        )
        await make_admin(db_session, admin_id)
        await fund_wallet(db_session, creator_id, Decimal("500.00"))
        await fund_wallet(db_session, opp_id, Decimal("500.00"))

        # Create match via sync
        ext_id = f"api_football:conf-{uuid.uuid4().hex[:8]}"
        payload = _make_payload(external_id=ext_id, kickoff_hours=2)
        provider = _MockProvider([payload])
        svc = MatchSyncService(db_session, provider)
        await svc.sync_upcoming()

        row = (
            await db_session.execute(
                select(Match).where(Match.external_id == ext_id)
            )
        ).scalar_one()
        match_id = str(row.id)

        # Create and accept a bet
        create_resp = await client.post(
            "/api/v1/bets",
            json={
                "match_id": match_id,
                "creator_prediction": "home_win",
                "stake_amount": "100.00",
            },
            headers={"Authorization": f"Bearer {creator_token}"},
        )
        assert create_resp.status_code == 201
        bet_id = create_resp.json()["id"]

        await client.post(
            f"/api/v1/bets/{bet_id}/accept",
            json={"opponent_prediction": "away_win"},
            headers={"Authorization": f"Bearer {opp_token}"},
        )

        # Now sync marks the match as completed
        result_payload = ProviderMatchPayload(
            external_id=ext_id,
            provider_name="api_football",
            home_team=payload.home_team,
            away_team=payload.away_team,
            competition=payload.competition,
            kickoff_at=payload.kickoff_at,
            raw_status="FT",
            internal_status=MatchStatus.completed,
            home_score=1,
            away_score=0,
            internal_outcome=FootballOutcome.home_win,
        )
        result_provider = _MockProvider([result_payload])
        result_svc = MatchSyncService(db_session, result_provider)
        await result_svc.sync_results()

        # Admin confirms — should succeed even though sync pre-populated result
        confirm_resp = await client.post(
            f"/api/v1/admin/matches/{match_id}/confirm-result",
            json={"outcome": "home_win", "home_score": 1, "away_score": 0},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert confirm_resp.status_code == 200, confirm_resp.text
        data = confirm_resp.json()
        assert data["bets_settled"] == 1
