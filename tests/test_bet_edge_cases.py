"""Additional bet lifecycle edge-case tests.

Covers:
- Kickoff cutoff: bet creation rejected when match kicks off too soon
- Cancel MATCHED bet: must fail (only OPEN bets can be cancelled)
- Accept already-MATCHED bet: must fail with 422
- Wallet transaction history: ledger entries after bet operations
- Bet detail endpoint
- Unauthenticated bet endpoints
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tests.conftest import create_match, fund_wallet, register_user


class TestKickoffCutoff:
    """Bet creation is blocked when kickoff is within the cutoff window."""

    async def test_create_bet_rejected_within_cutoff(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """A match kicking off in 5 minutes cannot accept new bets."""
        from app.models.enums import MatchStatus
        from app.models.match import Match

        user_id, token = await register_user(
            client, email="cutoff_creator@example.com", display_name="Cutoff User"
        )
        await fund_wallet(db_session, user_id, Decimal("500.00"))

        # Kickoff in 5 minutes — inside the default 30-minute cutoff
        imminent_match = Match(
            external_id=f"cutoff-{uuid.uuid4()}",
            home_team="Rush FC",
            away_team="Sprint United",
            competition="Fast Cup",
            kickoff_at=datetime.now(tz=timezone.utc) + timedelta(minutes=5),
            status=MatchStatus.scheduled,
        )
        db_session.add(imminent_match)
        await db_session.flush()

        resp = await client.post(
            "/api/v1/bets",
            json={
                "match_id": str(imminent_match.id),
                "creator_prediction": "home_win",
                "stake_amount": "50.00",
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        # Should be rejected (match too close to kickoff)
        assert resp.status_code in (409, 422)

    async def test_create_bet_allowed_with_plenty_of_time(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """A match kicking off in 2 hours accepts new bets normally."""
        user_id, token = await register_user(
            client, email="cutoff_ok@example.com", display_name="OK User"
        )
        await fund_wallet(db_session, user_id, Decimal("500.00"))
        match_id = await create_match(db_session, kickoff_hours_from_now=2)

        resp = await client.post(
            "/api/v1/bets",
            json={
                "match_id": match_id,
                "creator_prediction": "draw",
                "stake_amount": "50.00",
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 201


class TestCancelMatchedBet:
    """Only OPEN bets can be cancelled."""

    async def test_cancel_matched_bet_returns_error(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Cancelling a MATCHED bet (already accepted) returns an error."""
        creator_id, creator_token = await register_user(
            client, email="cancel_matched_creator@example.com", display_name="Creator"
        )
        opp_id, opp_token = await register_user(
            client, email="cancel_matched_opp@example.com", display_name="Opponent"
        )
        await fund_wallet(db_session, creator_id, Decimal("300.00"))
        await fund_wallet(db_session, opp_id, Decimal("300.00"))
        match_id = await create_match(db_session)

        # Create and immediately accept the bet
        create_resp = await client.post(
            "/api/v1/bets",
            json={
                "match_id": match_id,
                "creator_prediction": "home_win",
                "stake_amount": "75.00",
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

        # Try to cancel — must fail
        cancel_resp = await client.post(
            f"/api/v1/bets/{bet_id}/cancel",
            headers={"Authorization": f"Bearer {creator_token}"},
        )
        assert cancel_resp.status_code in (409, 422)

    async def test_cancel_cancelled_bet_returns_error(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Cancelling an already-CANCELLED bet is rejected."""
        user_id, token = await register_user(
            client, email="cancel_twice@example.com", display_name="Twice User"
        )
        await fund_wallet(db_session, user_id, Decimal("300.00"))
        match_id = await create_match(db_session)

        create_resp = await client.post(
            "/api/v1/bets",
            json={
                "match_id": match_id,
                "creator_prediction": "draw",
                "stake_amount": "50.00",
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        bet_id = create_resp.json()["id"]

        # First cancel
        r1 = await client.post(
            f"/api/v1/bets/{bet_id}/cancel",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r1.status_code == 200

        # Second cancel
        r2 = await client.post(
            f"/api/v1/bets/{bet_id}/cancel",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r2.status_code in (409, 422)


class TestAcceptBetEdgeCases:
    """Acceptance validation beyond the happy path."""

    async def test_accept_already_matched_bet_returns_422(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Attempting to accept a bet that is already MATCHED returns 422."""
        creator_id, creator_token = await register_user(
            client, email="accept_dup_creator@example.com", display_name="Creator"
        )
        opp1_id, opp1_token = await register_user(
            client, email="accept_dup_opp1@example.com", display_name="Opp 1"
        )
        opp2_id, opp2_token = await register_user(
            client, email="accept_dup_opp2@example.com", display_name="Opp 2"
        )
        await fund_wallet(db_session, creator_id, Decimal("400.00"))
        await fund_wallet(db_session, opp1_id, Decimal("400.00"))
        await fund_wallet(db_session, opp2_id, Decimal("400.00"))
        match_id = await create_match(db_session)

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

        # Opp 1 accepts
        r1 = await client.post(
            f"/api/v1/bets/{bet_id}/accept",
            json={"opponent_prediction": "away_win"},
            headers={"Authorization": f"Bearer {opp1_token}"},
        )
        assert r1.status_code == 200

        # Opp 2 tries to accept the same (now MATCHED) bet
        r2 = await client.post(
            f"/api/v1/bets/{bet_id}/accept",
            json={"opponent_prediction": "draw"},
            headers={"Authorization": f"Bearer {opp2_token}"},
        )
        assert r2.status_code in (409, 422)

    async def test_accept_non_existent_bet_returns_404(
        self, client: AsyncClient
    ) -> None:
        """Accepting a non-existent bet returns 404."""
        _, token = await register_user(
            client, email="accept_404@example.com"
        )
        resp = await client.post(
            f"/api/v1/bets/{uuid.uuid4()}/accept",
            json={"opponent_prediction": "home_win"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 404

    async def test_accept_cancelled_bet_returns_422(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Accepting a CANCELLED bet returns 422."""
        creator_id, creator_token = await register_user(
            client, email="accept_cancelled_creator@example.com", display_name="Creator"
        )
        opp_id, opp_token = await register_user(
            client, email="accept_cancelled_opp@example.com", display_name="Opp"
        )
        await fund_wallet(db_session, creator_id, Decimal("300.00"))
        await fund_wallet(db_session, opp_id, Decimal("300.00"))
        match_id = await create_match(db_session)

        # Create then cancel the bet
        create_resp = await client.post(
            "/api/v1/bets",
            json={
                "match_id": match_id,
                "creator_prediction": "draw",
                "stake_amount": "50.00",
            },
            headers={"Authorization": f"Bearer {creator_token}"},
        )
        bet_id = create_resp.json()["id"]

        await client.post(
            f"/api/v1/bets/{bet_id}/cancel",
            headers={"Authorization": f"Bearer {creator_token}"},
        )

        # Try to accept the now-CANCELLED bet
        resp = await client.post(
            f"/api/v1/bets/{bet_id}/accept",
            json={"opponent_prediction": "home_win"},
            headers={"Authorization": f"Bearer {opp_token}"},
        )
        assert resp.status_code in (409, 422)


class TestBetDetailEndpoint:
    """GET /bets/{id}"""

    async def test_get_bet_by_id_returns_bet(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Authenticated user can retrieve any bet by ID."""
        creator_id, creator_token = await register_user(
            client, email="detail_creator@example.com", display_name="Creator"
        )
        await fund_wallet(db_session, creator_id, Decimal("200.00"))
        match_id = await create_match(db_session)

        create_resp = await client.post(
            "/api/v1/bets",
            json={
                "match_id": match_id,
                "creator_prediction": "home_win",
                "stake_amount": "50.00",
            },
            headers={"Authorization": f"Bearer {creator_token}"},
        )
        bet_id = create_resp.json()["id"]

        resp = await client.get(
            f"/api/v1/bets/{bet_id}",
            headers={"Authorization": f"Bearer {creator_token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == bet_id
        assert data["status"] == "OPEN"
        assert "match" in data

    async def test_get_bet_not_found_returns_404(
        self, client: AsyncClient
    ) -> None:
        """Non-existent bet ID returns 404."""
        _, token = await register_user(client, email="bet404@example.com")
        resp = await client.get(
            f"/api/v1/bets/{uuid.uuid4()}",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 404

    async def test_get_bet_unauthenticated_returns_401(
        self, client: AsyncClient
    ) -> None:
        """GET /bets/{id} requires authentication."""
        resp = await client.get(f"/api/v1/bets/{uuid.uuid4()}")
        assert resp.status_code == 401


class TestWalletTransactions:
    """GET /wallet/transactions — ledger history endpoint."""

    async def test_transactions_after_bet_creation_shows_stake_lock(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Creating a bet produces a STAKE_LOCK ledger entry in transaction history."""
        user_id, token = await register_user(
            client, email="txn_creator@example.com", display_name="Txn User"
        )
        await fund_wallet(db_session, user_id, Decimal("500.00"))
        match_id = await create_match(db_session)

        await client.post(
            "/api/v1/bets",
            json={
                "match_id": match_id,
                "creator_prediction": "home_win",
                "stake_amount": "100.00",
            },
            headers={"Authorization": f"Bearer {token}"},
        )

        resp = await client.get(
            "/api/v1/wallet/transactions",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] >= 1
        entry_types = [e["entry_type"] for e in data["items"]]
        assert "STAKE_LOCK" in entry_types

    async def test_transactions_after_cancel_shows_stake_unlock(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Cancelling a bet produces a STAKE_UNLOCK entry in transaction history."""
        user_id, token = await register_user(
            client, email="txn_cancel@example.com", display_name="Txn Cancel User"
        )
        await fund_wallet(db_session, user_id, Decimal("300.00"))
        match_id = await create_match(db_session)

        create_resp = await client.post(
            "/api/v1/bets",
            json={
                "match_id": match_id,
                "creator_prediction": "draw",
                "stake_amount": "75.00",
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        bet_id = create_resp.json()["id"]

        await client.post(
            f"/api/v1/bets/{bet_id}/cancel",
            headers={"Authorization": f"Bearer {token}"},
        )

        resp = await client.get(
            "/api/v1/wallet/transactions",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        entry_types = [e["entry_type"] for e in resp.json()["items"]]
        assert "STAKE_LOCK" in entry_types
        assert "STAKE_UNLOCK" in entry_types

    async def test_transactions_unauthenticated_returns_401(
        self, client: AsyncClient
    ) -> None:
        """GET /wallet/transactions without a token returns 401."""
        resp = await client.get("/api/v1/wallet/transactions")
        assert resp.status_code == 401

    async def test_transactions_empty_for_new_user(
        self, client: AsyncClient
    ) -> None:
        """A brand-new user with no activity has zero transactions."""
        _, token = await register_user(
            client, email="txn_new@example.com", display_name="New Txn User"
        )

        resp = await client.get(
            "/api/v1/wallet/transactions",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        assert resp.json()["total"] == 0
