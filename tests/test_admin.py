"""Integration tests for admin endpoints.

POST /api/v1/admin/bets/{id}/void
POST /api/v1/admin/matches/{id}/confirm-result  (edge cases)
POST /api/v1/admin/bets/{id}/settle
GET  /api/v1/admin/bets/pending
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tests.conftest import create_match, fund_wallet, make_admin, register_user


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


async def _setup_open_bet(
    client: AsyncClient,
    db_session: AsyncSession,
    *,
    creator_email: str,
    admin_email: str,
    stake: str = "100.00",
) -> dict:
    """Register creator + admin, fund creator, create an OPEN bet. Return context."""
    creator_id, creator_token = await register_user(
        client, email=creator_email, display_name="Creator"
    )
    admin_id, admin_token = await register_user(
        client, email=admin_email, display_name="Admin"
    )
    await make_admin(db_session, admin_id)
    await fund_wallet(db_session, creator_id, Decimal("500.00"))
    match_id = await create_match(db_session)

    create_resp = await client.post(
        "/api/v1/bets",
        json={
            "match_id": match_id,
            "creator_prediction": "home_win",
            "stake_amount": stake,
        },
        headers={"Authorization": f"Bearer {creator_token}"},
    )
    assert create_resp.status_code == 201, create_resp.text
    return dict(
        creator_id=creator_id,
        creator_token=creator_token,
        admin_id=admin_id,
        admin_token=admin_token,
        bet_id=create_resp.json()["id"],
        match_id=match_id,
    )


async def _setup_matched_bet(
    client: AsyncClient,
    db_session: AsyncSession,
    *,
    creator_email: str,
    opponent_email: str,
    admin_email: str,
    stake: str = "100.00",
) -> dict:
    """Create a MATCHED bet (both sides accepted). Return context."""
    ctx = await _setup_open_bet(
        client,
        db_session,
        creator_email=creator_email,
        admin_email=admin_email,
        stake=stake,
    )
    opp_id, opp_token = await register_user(
        client, email=opponent_email, display_name="Opponent"
    )
    await fund_wallet(db_session, opp_id, Decimal("500.00"))

    accept_resp = await client.post(
        f"/api/v1/bets/{ctx['bet_id']}/accept",
        json={"opponent_prediction": "away_win"},
        headers={"Authorization": f"Bearer {opp_token}"},
    )
    assert accept_resp.status_code == 200, accept_resp.text
    ctx["opponent_id"] = opp_id
    ctx["opponent_token"] = opp_token
    return ctx


class TestVoidBet:
    """POST /admin/bets/{id}/void"""

    async def test_void_open_bet_refunds_creator_stake(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Voiding an OPEN bet unlocks the creator's stake back to available."""
        ctx = await _setup_open_bet(
            client,
            db_session,
            creator_email="void_open_creator@example.com",
            admin_email="void_open_admin@example.com",
        )

        # Creator has 100 locked before void
        w_before = (
            await client.get(
                "/api/v1/wallet",
                headers={"Authorization": f"Bearer {ctx['creator_token']}"},
            )
        ).json()
        assert w_before["locked_balance"] == "100.00"
        assert w_before["available_balance"] == "400.00"

        resp = await client.post(
            f"/api/v1/admin/bets/{ctx['bet_id']}/void",
            json={"reason": "Test void — OPEN bet"},
            headers={"Authorization": f"Bearer {ctx['admin_token']}"},
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert ctx["creator_id"] in [str(u) for u in data["refunded_user_ids"]]

        # Creator is fully refunded
        w_after = (
            await client.get(
                "/api/v1/wallet",
                headers={"Authorization": f"Bearer {ctx['creator_token']}"},
            )
        ).json()
        assert w_after["locked_balance"] == "0.00"
        assert w_after["available_balance"] == "500.00"

    async def test_void_matched_bet_refunds_both_users(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Voiding a MATCHED bet refunds both creator and opponent."""
        ctx = await _setup_matched_bet(
            client,
            db_session,
            creator_email="void_matched_creator@example.com",
            opponent_email="void_matched_opp@example.com",
            admin_email="void_matched_admin@example.com",
        )

        resp = await client.post(
            f"/api/v1/admin/bets/{ctx['bet_id']}/void",
            json={"reason": "Test void — MATCHED bet"},
            headers={"Authorization": f"Bearer {ctx['admin_token']}"},
        )
        assert resp.status_code == 200, resp.text
        refunded = [str(u) for u in resp.json()["refunded_user_ids"]]
        assert ctx["creator_id"] in refunded
        assert ctx["opponent_id"] in refunded

        # Both wallets restored to 500
        for token in (ctx["creator_token"], ctx["opponent_token"]):
            w = (
                await client.get(
                    "/api/v1/wallet",
                    headers={"Authorization": f"Bearer {token}"},
                )
            ).json()
            assert w["locked_balance"] == "0.00"
            assert w["available_balance"] == "500.00"

    async def test_void_already_voided_bet_returns_error(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Voiding a VOIDED bet is rejected."""
        ctx = await _setup_open_bet(
            client,
            db_session,
            creator_email="void_twice_creator@example.com",
            admin_email="void_twice_admin@example.com",
        )

        # First void succeeds
        r1 = await client.post(
            f"/api/v1/admin/bets/{ctx['bet_id']}/void",
            json={"reason": "First void"},
            headers={"Authorization": f"Bearer {ctx['admin_token']}"},
        )
        assert r1.status_code == 200

        # Second void fails
        r2 = await client.post(
            f"/api/v1/admin/bets/{ctx['bet_id']}/void",
            json={"reason": "Second void"},
            headers={"Authorization": f"Bearer {ctx['admin_token']}"},
        )
        assert r2.status_code in (409, 422)

    async def test_void_non_admin_returns_403(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """A regular user cannot void a bet."""
        ctx = await _setup_open_bet(
            client,
            db_session,
            creator_email="void_perm_creator@example.com",
            admin_email="void_perm_admin@example.com",
        )

        resp = await client.post(
            f"/api/v1/admin/bets/{ctx['bet_id']}/void",
            json={"reason": "Should fail"},
            headers={"Authorization": f"Bearer {ctx['creator_token']}"},
        )
        assert resp.status_code == 403

    async def test_void_not_found_returns_404(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Voiding a non-existent bet returns 404."""
        _, admin_token = await register_user(
            client, email="void_404_admin@example.com"
        )
        await make_admin(db_session, _)

        resp = await client.post(
            f"/api/v1/admin/bets/{uuid.uuid4()}/void",
            json={"reason": "Not found"},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 404

    async def test_void_sets_bet_status_to_voided(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """After voiding, the bet's status is VOIDED in the database."""
        from app.models.bet import Bet

        ctx = await _setup_open_bet(
            client,
            db_session,
            creator_email="void_status_creator@example.com",
            admin_email="void_status_admin@example.com",
        )

        await client.post(
            f"/api/v1/admin/bets/{ctx['bet_id']}/void",
            json={"reason": "Status check"},
            headers={"Authorization": f"Bearer {ctx['admin_token']}"},
        )

        result = await db_session.execute(
            select(Bet).where(Bet.id == uuid.UUID(ctx["bet_id"]))
        )
        bet = result.scalar_one()
        assert bet.status.value == "VOIDED"


class TestConfirmResultEdgeCases:
    """Idempotency and auth guards for POST /admin/matches/{id}/confirm-result."""

    async def test_confirm_result_non_admin_returns_403(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """A regular user cannot confirm a match result."""
        match_id = await create_match(db_session)
        _, user_token = await register_user(
            client, email="confirm_perm@example.com"
        )

        resp = await client.post(
            f"/api/v1/admin/matches/{match_id}/confirm-result",
            json={"outcome": "home_win", "home_score": 1, "away_score": 0},
            headers={"Authorization": f"Bearer {user_token}"},
        )
        assert resp.status_code == 403

    async def test_double_confirm_same_match_returns_error(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Confirming an already-completed match is rejected."""
        match_id = await create_match(db_session)
        _, admin_token = await register_user(
            client, email="double_confirm_admin@example.com"
        )
        await make_admin(db_session, _)

        # First confirm
        r1 = await client.post(
            f"/api/v1/admin/matches/{match_id}/confirm-result",
            json={"outcome": "home_win", "home_score": 2, "away_score": 0},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert r1.status_code == 200

        # Second confirm on same match
        r2 = await client.post(
            f"/api/v1/admin/matches/{match_id}/confirm-result",
            json={"outcome": "draw", "home_score": 1, "away_score": 1},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert r2.status_code in (409, 422)

    async def test_confirm_non_existent_match_returns_404(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Confirming a non-existent match returns 404."""
        _, admin_token = await register_user(
            client, email="confirm_404_admin@example.com"
        )
        await make_admin(db_session, _)

        resp = await client.post(
            f"/api/v1/admin/matches/{uuid.uuid4()}/confirm-result",
            json={"outcome": "home_win", "home_score": 1, "away_score": 0},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 404


class TestPendingSettlement:
    """GET /admin/bets/pending and POST /admin/bets/{id}/settle."""

    async def test_pending_settlement_list_requires_admin(
        self, client: AsyncClient
    ) -> None:
        """GET /admin/bets/pending requires admin role."""
        _, user_token = await register_user(
            client, email="pending_user@example.com"
        )

        resp = await client.get(
            "/api/v1/admin/bets/pending",
            headers={"Authorization": f"Bearer {user_token}"},
        )
        assert resp.status_code == 403

    async def test_pending_settlement_list_empty_when_none(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Empty list when no bets are pending settlement."""
        _, admin_token = await register_user(
            client, email="pending_empty_admin@example.com"
        )
        await make_admin(db_session, _)

        resp = await client.get(
            "/api/v1/admin/bets/pending",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "items" in data
        assert data["total"] == 0

    async def test_manual_settle_requires_admin(
        self, client: AsyncClient
    ) -> None:
        """POST /admin/bets/{id}/settle requires admin role."""
        _, user_token = await register_user(
            client, email="settle_perm@example.com"
        )

        resp = await client.post(
            f"/api/v1/admin/bets/{uuid.uuid4()}/settle",
            headers={"Authorization": f"Bearer {user_token}"},
        )
        assert resp.status_code == 403
