"""Integration tests for wallet endpoints and WalletService.

GET /api/v1/wallet
GET /api/v1/wallet/transactions
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from tests.conftest import create_match, fund_wallet, register_user


class TestGetWallet:
    """GET /wallet"""

    async def test_get_wallet_returns_zero_for_new_user(
        self, client: AsyncClient
    ) -> None:
        """Authenticated user receives their wallet with available and locked balances."""
        _uid, token = await register_user(
            client, email="wallet_zero@example.com", display_name="Zero User"
        )
        resp = await client.get(
            "/api/v1/wallet",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["available_balance"] == "0.00"
        assert data["locked_balance"] == "0.00"
        assert data["total_balance"] == "0.00"
        assert "user_id" in data

    async def test_get_wallet_unauthenticated_returns_401(
        self, client: AsyncClient
    ) -> None:
        """Request without a Bearer token returns 401."""
        resp = await client.get("/api/v1/wallet")
        assert resp.status_code == 401

    async def test_get_wallet_total_balance_is_sum(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """total_balance equals available_balance + locked_balance."""
        user_id, token = await register_user(
            client, email="wallet_sum@example.com", display_name="Sum User"
        )
        # Fund so we have a non-trivial available balance
        await fund_wallet(db_session, user_id, Decimal("250.00"))
        # Create a bet to lock some funds
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
            "/api/v1/wallet",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        available = Decimal(data["available_balance"])
        locked = Decimal(data["locked_balance"])
        total = Decimal(data["total_balance"])
        assert total == available + locked
        assert locked == Decimal("100.00")
        assert available == Decimal("150.00")


class TestGetTransactions:
    """GET /wallet/transactions"""

    async def test_transactions_returns_empty_for_new_user(
        self, client: AsyncClient
    ) -> None:
        """New user with no activity has no ledger entries."""
        _uid, token = await register_user(
            client, email="txn_empty@example.com", display_name="No Txn"
        )
        resp = await client.get(
            "/api/v1/wallet/transactions",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 0
        assert data["items"] == []

    async def test_transactions_recorded_after_bet_creation(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Creating a bet produces STAKE_LOCK ledger entries."""
        user_id, token = await register_user(
            client, email="txn_stake@example.com", display_name="Stake Txn"
        )
        await fund_wallet(db_session, user_id, Decimal("200.00"))
        match_id = await create_match(db_session)

        await client.post(
            "/api/v1/bets",
            json={
                "match_id": match_id,
                "creator_prediction": "away_win",
                "stake_amount": "80.00",
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

    async def test_transactions_unauthenticated_returns_401(
        self, client: AsyncClient
    ) -> None:
        """GET /wallet/transactions without a token returns 401."""
        resp = await client.get("/api/v1/wallet/transactions")
        assert resp.status_code == 401


class TestWalletService:
    """Direct wallet mutation tests via bet lifecycle (no mocking)."""

    async def test_lock_and_unlock_round_trips_balance(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Creating then cancelling a bet restores the original balance exactly."""
        user_id, token = await register_user(
            client, email="roundtrip@example.com", display_name="Round Trip"
        )
        await fund_wallet(db_session, user_id, Decimal("400.00"))
        match_id = await create_match(db_session)

        # Create bet → locks 200
        create_resp = await client.post(
            "/api/v1/bets",
            json={
                "match_id": match_id,
                "creator_prediction": "home_win",
                "stake_amount": "200.00",
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        assert create_resp.status_code == 201
        bet_id = create_resp.json()["id"]

        # Cancel → unlocks 200
        cancel_resp = await client.post(
            f"/api/v1/bets/{bet_id}/cancel",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert cancel_resp.status_code == 200

        # Balance fully restored
        wallet_resp = await client.get(
            "/api/v1/wallet", headers={"Authorization": f"Bearer {token}"}
        )
        w = wallet_resp.json()
        assert w["available_balance"] == "400.00"
        assert w["locked_balance"] == "0.00"

    async def test_insufficient_funds_raises_422(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Bet with stake > available balance returns 422."""
        user_id, token = await register_user(
            client, email="lowfunds@example.com", display_name="Low Funds"
        )
        await fund_wallet(db_session, user_id, Decimal("10.00"))
        match_id = await create_match(db_session)

        resp = await client.post(
            "/api/v1/bets",
            json={
                "match_id": match_id,
                "creator_prediction": "draw",
                "stake_amount": "50.00",
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 422
