"""Integration tests for match listing endpoints.

GET /api/v1/matches
GET /api/v1/matches/{id}

Covers: pagination, status/competition filters, is_betting_open computed field.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from tests.conftest import create_match, register_user


async def _auth_header(client: AsyncClient) -> dict[str, str]:
    """Register a throw-away user and return its Bearer header."""
    _, token = await register_user(
        client,
        email=f"matches_user_{uuid.uuid4().hex[:8]}@example.com",
        display_name="Matches User",
    )
    return {"Authorization": f"Bearer {token}"}


class TestListMatches:
    """GET /matches"""

    async def test_list_matches_requires_auth(self, client: AsyncClient) -> None:
        """Unauthenticated request returns 401."""
        resp = await client.get("/api/v1/matches")
        assert resp.status_code == 401

    async def test_list_matches_returns_200(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Authenticated request returns 200 with pagination fields."""
        headers = await _auth_header(client)
        await create_match(db_session)

        resp = await client.get("/api/v1/matches", headers=headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "items" in data
        assert "total" in data
        assert "page" in data
        assert "page_size" in data

    async def test_list_matches_includes_created_match(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """A match inserted in this test appears in the listing."""
        headers = await _auth_header(client)
        match_id = await create_match(db_session)

        resp = await client.get("/api/v1/matches", headers=headers)
        assert resp.status_code == 200
        ids = [m["id"] for m in resp.json()["items"]]
        assert match_id in ids

    async def test_list_matches_status_filter_scheduled(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """?status=scheduled returns only scheduled matches."""
        headers = await _auth_header(client)

        # Insert a completed match
        from app.models.enums import MatchStatus
        from app.models.match import Match

        completed = Match(
            external_id=f"completed-filter-{uuid.uuid4()}",
            home_team="Team A",
            away_team="Team B",
            competition="Test Cup",
            kickoff_at=datetime(2024, 3, 1, 15, 0, tzinfo=timezone.utc),
            status=MatchStatus.completed,
        )
        db_session.add(completed)
        await db_session.flush()

        # Insert a scheduled match
        scheduled_id = await create_match(db_session)

        resp = await client.get(
            "/api/v1/matches?status=scheduled", headers=headers
        )
        assert resp.status_code == 200
        items = resp.json()["items"]
        statuses = {m["status"] for m in items}
        assert statuses == {"scheduled"}, f"Got statuses: {statuses}"
        ids = [m["id"] for m in items]
        assert scheduled_id in ids
        assert str(completed.id) not in ids

    async def test_list_matches_competition_filter(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """?competition=<term> returns only matches whose competition contains the term."""
        headers = await _auth_header(client)

        from app.models.enums import MatchStatus
        from app.models.match import Match

        pl_match = Match(
            external_id=f"pl-comp-{uuid.uuid4()}",
            home_team="Arsenal",
            away_team="Chelsea",
            competition="Premier League",
            kickoff_at=datetime.now(tz=timezone.utc) + timedelta(hours=3),
            status=MatchStatus.scheduled,
        )
        other_match = Match(
            external_id=f"other-comp-{uuid.uuid4()}",
            home_team="PSG",
            away_team="Lyon",
            competition="Ligue 1",
            kickoff_at=datetime.now(tz=timezone.utc) + timedelta(hours=3),
            status=MatchStatus.scheduled,
        )
        db_session.add(pl_match)
        db_session.add(other_match)
        await db_session.flush()

        resp = await client.get(
            "/api/v1/matches?competition=premier", headers=headers
        )
        assert resp.status_code == 200
        items = resp.json()["items"]
        ids = [m["id"] for m in items]
        assert str(pl_match.id) in ids
        assert str(other_match.id) not in ids

    async def test_list_matches_response_includes_is_betting_open(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Every match in the response includes the is_betting_open field."""
        headers = await _auth_header(client)
        await create_match(db_session)

        resp = await client.get("/api/v1/matches", headers=headers)
        assert resp.status_code == 200
        for match in resp.json()["items"]:
            assert "is_betting_open" in match

    async def test_is_betting_open_true_for_future_match(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """is_betting_open=True when the match kicks off well in the future."""
        headers = await _auth_header(client)
        match_id = await create_match(db_session, kickoff_hours_from_now=6)

        resp = await client.get("/api/v1/matches", headers=headers)
        match = next(m for m in resp.json()["items"] if m["id"] == match_id)
        assert match["is_betting_open"] is True

    async def test_is_betting_open_false_for_imminent_match(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """is_betting_open=False when kickoff is within the cutoff window."""
        from app.models.enums import MatchStatus
        from app.models.match import Match

        headers = await _auth_header(client)

        # Kickoff in 5 minutes — within the default 30-minute cutoff
        imminent = Match(
            external_id=f"imminent-{uuid.uuid4()}",
            home_team="Speed FC",
            away_team="Rush United",
            competition="Fast League",
            kickoff_at=datetime.now(tz=timezone.utc) + timedelta(minutes=5),
            status=MatchStatus.scheduled,
        )
        db_session.add(imminent)
        await db_session.flush()

        resp = await client.get("/api/v1/matches", headers=headers)
        match = next(
            (m for m in resp.json()["items"] if m["id"] == str(imminent.id)),
            None,
        )
        assert match is not None
        assert match["is_betting_open"] is False

    async def test_is_betting_open_false_for_completed_match(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """is_betting_open=False for a completed match."""
        from app.models.enums import MatchStatus
        from app.models.match import Match

        headers = await _auth_header(client)

        done = Match(
            external_id=f"done-ibo-{uuid.uuid4()}",
            home_team="Old Team A",
            away_team="Old Team B",
            competition="History Cup",
            kickoff_at=datetime(2024, 1, 1, 15, 0, tzinfo=timezone.utc),
            status=MatchStatus.completed,
        )
        db_session.add(done)
        await db_session.flush()

        resp = await client.get("/api/v1/matches", headers=headers)
        match = next(
            (m for m in resp.json()["items"] if m["id"] == str(done.id)),
            None,
        )
        assert match is not None
        assert match["is_betting_open"] is False

    async def test_list_matches_pagination(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """page_size is respected; page 2 returns different items than page 1."""
        headers = await _auth_header(client)

        # Insert 3 scheduled matches
        for i in range(3):
            from app.models.enums import MatchStatus
            from app.models.match import Match

            m = Match(
                external_id=f"page-test-{uuid.uuid4()}",
                home_team=f"Team {i}A",
                away_team=f"Team {i}B",
                competition="Pagination Cup",
                kickoff_at=datetime.now(tz=timezone.utc) + timedelta(hours=i + 2),
                status=MatchStatus.scheduled,
            )
            db_session.add(m)
        await db_session.flush()

        page1 = (
            await client.get(
                "/api/v1/matches?status=scheduled&page=1&page_size=2",
                headers=headers,
            )
        ).json()
        page2 = (
            await client.get(
                "/api/v1/matches?status=scheduled&page=2&page_size=2",
                headers=headers,
            )
        ).json()

        assert len(page1["items"]) <= 2
        # Page 2 should contain different items (or be empty if there are only 2)
        page1_ids = {m["id"] for m in page1["items"]}
        page2_ids = {m["id"] for m in page2["items"]}
        assert page1_ids.isdisjoint(page2_ids)


class TestGetMatchById:
    """GET /matches/{id}"""

    async def test_get_match_by_id_returns_match(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Returns match detail including is_betting_open."""
        headers = await _auth_header(client)
        match_id = await create_match(db_session)

        resp = await client.get(f"/api/v1/matches/{match_id}", headers=headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == match_id
        assert "is_betting_open" in data
        assert data["home_team"] == "Arsenal"
        assert data["away_team"] == "Chelsea"

    async def test_get_match_by_id_not_found_returns_404(
        self, client: AsyncClient
    ) -> None:
        """A non-existent match ID returns 404."""
        headers = await _auth_header(client)
        fake_id = uuid.uuid4()

        resp = await client.get(f"/api/v1/matches/{fake_id}", headers=headers)
        assert resp.status_code == 404

    async def test_get_match_requires_auth(self, client: AsyncClient) -> None:
        """GET /matches/{id} without token returns 401."""
        resp = await client.get(f"/api/v1/matches/{uuid.uuid4()}")
        assert resp.status_code == 401
