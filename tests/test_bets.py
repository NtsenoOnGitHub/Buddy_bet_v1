"""Integration tests for bet endpoints and BetService business rules.

GET  /api/v1/bets/open
GET  /api/v1/bets/my
POST /api/v1/bets
POST /api/v1/bets/{id}/accept
POST /api/v1/bets/{id}/cancel
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tests.conftest import create_match, fund_wallet, make_admin, register_user


class TestCreateBet:
    """POST /bets"""

    async def test_create_bet_locks_creator_stake(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Creating a bet moves stake_amount from available to locked."""
        user_id, token = await register_user(
            client, email="creator@example.com", display_name="Creator"
        )
        await fund_wallet(db_session, user_id, Decimal("500.00"))
        match_id = await create_match(db_session)

        resp = await client.post(
            "/api/v1/bets",
            json={
                "match_id": match_id,
                "creator_prediction": "home_win",
                "stake_amount": "100.00",
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 201, resp.text
        data = resp.json()
        assert data["status"] == "OPEN"
        assert data["stake_amount"] == "100.00"

        # Verify wallet: available decreases, locked increases
        wallet_resp = await client.get(
            "/api/v1/wallet",
            headers={"Authorization": f"Bearer {token}"},
        )
        wallet = wallet_resp.json()
        assert wallet["available_balance"] == "400.00"
        assert wallet["locked_balance"] == "100.00"

    async def test_create_bet_insufficient_funds_returns_422(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Creating a bet with more than available_balance returns 422."""
        user_id, token = await register_user(
            client, email="broke@example.com", display_name="Broke User"
        )
        # Wallet has 0 balance — no funding
        match_id = await create_match(db_session)

        resp = await client.post(
            "/api/v1/bets",
            json={
                "match_id": match_id,
                "creator_prediction": "home_win",
                "stake_amount": "50.00",
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 422

    async def test_create_bet_on_non_scheduled_match_returns_error(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Bet creation on a completed match is rejected."""
        from app.models.enums import MatchStatus
        from app.models.match import Match

        user_id, token = await register_user(
            client, email="badmatch@example.com", display_name="Bad Match User"
        )
        await fund_wallet(db_session, user_id, Decimal("500.00"))

        # Insert a completed match directly
        match = Match(
            external_id=f"completed-{id(user_id)}",
            home_team="Man City",
            away_team="Liverpool",
            competition="PL",
            kickoff_at=__import__("datetime").datetime(
                2024, 1, 1, 15, 0, tzinfo=__import__("datetime").timezone.utc
            ),
            status=MatchStatus.completed,
        )
        db_session.add(match)
        await db_session.flush()

        resp = await client.post(
            "/api/v1/bets",
            json={
                "match_id": str(match.id),
                "creator_prediction": "home_win",
                "stake_amount": "50.00",
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code in (409, 422)


class TestAcceptBet:
    """POST /bets/{id}/accept"""

    async def test_accept_bet_locks_opponent_stake_and_transitions_to_matched(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Accepting an OPEN bet sets status to MATCHED and locks opponent's stake."""
        creator_id, creator_token = await register_user(
            client, email="creator2@example.com", display_name="Creator 2"
        )
        opponent_id, opponent_token = await register_user(
            client, email="opponent@example.com", display_name="Opponent"
        )
        await fund_wallet(db_session, creator_id, Decimal("500.00"))
        await fund_wallet(db_session, opponent_id, Decimal("500.00"))
        match_id = await create_match(db_session)

        # Creator opens a bet
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

        # Opponent accepts with opposite prediction
        accept_resp = await client.post(
            f"/api/v1/bets/{bet_id}/accept",
            json={"opponent_prediction": "away_win"},
            headers={"Authorization": f"Bearer {opponent_token}"},
        )
        assert accept_resp.status_code == 200, accept_resp.text
        bet_data = accept_resp.json()
        assert bet_data["status"] == "MATCHED"
        assert bet_data["opponent_id"] == opponent_id
        assert bet_data["opponent_prediction"] == "away_win"

        # Opponent's wallet: 400 available, 100 locked
        opp_wallet = (
            await client.get(
                "/api/v1/wallet",
                headers={"Authorization": f"Bearer {opponent_token}"},
            )
        ).json()
        assert opp_wallet["available_balance"] == "400.00"
        assert opp_wallet["locked_balance"] == "100.00"

    async def test_accept_own_bet_returns_422(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """BR-01: A user cannot accept their own bet."""
        user_id, token = await register_user(
            client, email="selfbet@example.com", display_name="Self Better"
        )
        await fund_wallet(db_session, user_id, Decimal("500.00"))
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
        assert create_resp.status_code == 201
        bet_id = create_resp.json()["id"]

        accept_resp = await client.post(
            f"/api/v1/bets/{bet_id}/accept",
            json={"opponent_prediction": "away_win"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert accept_resp.status_code == 422

    async def test_accept_bet_same_prediction_returns_422(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """BR-06/07: opponent_prediction must differ from creator_prediction."""
        creator_id, creator_token = await register_user(
            client, email="samepred_creator@example.com", display_name="Creator SP"
        )
        opp_id, opp_token = await register_user(
            client, email="samepred_opp@example.com", display_name="Opp SP"
        )
        await fund_wallet(db_session, creator_id, Decimal("200.00"))
        await fund_wallet(db_session, opp_id, Decimal("200.00"))
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
        assert create_resp.status_code == 201
        bet_id = create_resp.json()["id"]

        accept_resp = await client.post(
            f"/api/v1/bets/{bet_id}/accept",
            json={"opponent_prediction": "home_win"},  # same as creator
            headers={"Authorization": f"Bearer {opp_token}"},
        )
        assert accept_resp.status_code == 422


class TestCancelBet:
    """POST /bets/{id}/cancel"""

    async def test_cancel_open_bet_unlocks_creator_stake(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Cancelling an OPEN bet moves stake from locked back to available."""
        user_id, token = await register_user(
            client, email="cancel_creator@example.com", display_name="Cancel User"
        )
        await fund_wallet(db_session, user_id, Decimal("300.00"))
        match_id = await create_match(db_session)

        # Create the bet
        create_resp = await client.post(
            "/api/v1/bets",
            json={
                "match_id": match_id,
                "creator_prediction": "draw",
                "stake_amount": "150.00",
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        assert create_resp.status_code == 201
        bet_id = create_resp.json()["id"]

        # Confirm locked
        w1 = (
            await client.get(
                "/api/v1/wallet", headers={"Authorization": f"Bearer {token}"}
            )
        ).json()
        assert w1["locked_balance"] == "150.00"
        assert w1["available_balance"] == "150.00"

        # Cancel the bet
        cancel_resp = await client.post(
            f"/api/v1/bets/{bet_id}/cancel",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert cancel_resp.status_code == 200, cancel_resp.text
        assert cancel_resp.json()["status"] == "CANCELLED"

        # Funds restored
        w2 = (
            await client.get(
                "/api/v1/wallet", headers={"Authorization": f"Bearer {token}"}
            )
        ).json()
        assert w2["locked_balance"] == "0.00"
        assert w2["available_balance"] == "300.00"

    async def test_cancel_by_non_creator_returns_403(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """BR-13: Only the creator may cancel their bet."""
        creator_id, creator_token = await register_user(
            client, email="nc_creator@example.com", display_name="NC Creator"
        )
        other_id, other_token = await register_user(
            client, email="nc_other@example.com", display_name="NC Other"
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
        assert create_resp.status_code == 201
        bet_id = create_resp.json()["id"]

        cancel_resp = await client.post(
            f"/api/v1/bets/{bet_id}/cancel",
            headers={"Authorization": f"Bearer {other_token}"},
        )
        assert cancel_resp.status_code in (403, 422)


class TestSettlementFlow:
    """Full settlement flow via admin confirm-result endpoint."""

    async def test_full_settlement_updates_wallets_and_bet_status(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """End-to-end: two users bet, match confirmed, winner gets payout, fee collected."""
        # Setup users
        creator_id, creator_token = await register_user(
            client, email="settle_creator@example.com", display_name="Settle Creator"
        )
        opponent_id, opponent_token = await register_user(
            client, email="settle_opponent@example.com", display_name="Settle Opponent"
        )
        admin_id, admin_token = await register_user(
            client, email="settle_admin@example.com", display_name="Settle Admin"
        )
        await make_admin(db_session, admin_id)
        await fund_wallet(db_session, creator_id, Decimal("500.00"))
        await fund_wallet(db_session, opponent_id, Decimal("500.00"))
        match_id = await create_match(db_session)

        # Creator bets home_win
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

        # Opponent bets away_win
        accept_resp = await client.post(
            f"/api/v1/bets/{bet_id}/accept",
            json={"opponent_prediction": "away_win"},
            headers={"Authorization": f"Bearer {opponent_token}"},
        )
        assert accept_resp.status_code == 200
        assert accept_resp.json()["status"] == "MATCHED"

        # Admin confirms: home_win (creator wins)
        confirm_resp = await client.post(
            f"/api/v1/admin/matches/{match_id}/confirm-result",
            json={"outcome": "home_win", "home_score": 2, "away_score": 1},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert confirm_resp.status_code == 200, confirm_resp.text
        summary = confirm_resp.json()
        assert summary["outcome"] == "home_win"
        assert summary["bets_found"] == 1
        assert summary["bets_settled"] == 1
        assert summary["bets_failed"] == 0

        # Creator (winner) should have received payout
        # stake=100, pool=200, fee=20 (10%), payout=180
        creator_wallet = (
            await client.get(
                "/api/v1/wallet",
                headers={"Authorization": f"Bearer {creator_token}"},
            )
        ).json()
        assert creator_wallet["locked_balance"] == "0.00"
        # started with 500, staked 100 (locked), won 180 back → 580
        assert creator_wallet["available_balance"] == "580.00"

        # Opponent (loser): stake was taken
        opponent_wallet = (
            await client.get(
                "/api/v1/wallet",
                headers={"Authorization": f"Bearer {opponent_token}"},
            )
        ).json()
        assert opponent_wallet["locked_balance"] == "0.00"
        # started with 500, staked 100 (locked), lost it → 400
        assert opponent_wallet["available_balance"] == "400.00"


class TestListBets:
    """GET /bets/open and GET /bets/my"""

    async def test_open_bets_returns_created_bet(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """GET /bets/open includes an OPEN bet created in this test."""
        user_id, token = await register_user(
            client, email="listopen@example.com", display_name="List Open"
        )
        await fund_wallet(db_session, user_id, Decimal("200.00"))
        match_id = await create_match(db_session)

        await client.post(
            "/api/v1/bets",
            json={
                "match_id": match_id,
                "creator_prediction": "draw",
                "stake_amount": "50.00",
            },
            headers={"Authorization": f"Bearer {token}"},
        )

        resp = await client.get(
            "/api/v1/bets/open",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] >= 1

    async def test_my_bets_includes_created_and_accepted(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """GET /bets/my returns bets where the user is creator or opponent."""
        creator_id, creator_token = await register_user(
            client, email="my_creator@example.com", display_name="My Creator"
        )
        opp_id, opp_token = await register_user(
            client, email="my_opponent@example.com", display_name="My Opponent"
        )
        await fund_wallet(db_session, creator_id, Decimal("300.00"))
        await fund_wallet(db_session, opp_id, Decimal("300.00"))
        match_id = await create_match(db_session)

        create_resp = await client.post(
            "/api/v1/bets",
            json={
                "match_id": match_id,
                "creator_prediction": "home_win",
                "stake_amount": "75.00",
            },
            headers={"Authorization": f"Bearer {creator_token}"},
        )
        bet_id = create_resp.json()["id"]

        await client.post(
            f"/api/v1/bets/{bet_id}/accept",
            json={"opponent_prediction": "draw"},
            headers={"Authorization": f"Bearer {opp_token}"},
        )

        # Creator sees it
        creator_my = (
            await client.get(
                "/api/v1/bets/my",
                headers={"Authorization": f"Bearer {creator_token}"},
            )
        ).json()
        assert any(b["id"] == bet_id for b in creator_my["items"])

        # Opponent also sees it
        opp_my = (
            await client.get(
                "/api/v1/bets/my",
                headers={"Authorization": f"Bearer {opp_token}"},
            )
        ).json()
        assert any(b["id"] == bet_id for b in opp_my["items"])
