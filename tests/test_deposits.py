"""Tests for the deposit lifecycle.

Covers:
  A. Deposit request creation
  B. Admin deposit completion (wallet credit + ledger)
  C. Admin deposit failure
  D. Idempotency and terminal-state guards
  E. User access control
  F. Pagination / list endpoints
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tests.conftest import fund_wallet, make_admin, register_user


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def create_deposit(
    client: AsyncClient,
    token: str,
    amount: str = "500.00",
    **kwargs,
) -> dict:
    r = await client.post(
        "/api/v1/wallet/deposits",
        json={"amount": amount, **kwargs},
        headers={"Authorization": f"Bearer {token}"},
    )
    return r


async def admin_complete(
    client: AsyncClient,
    admin_token: str,
    deposit_id: str,
    provider_reference: str | None = None,
) -> dict:
    body = {}
    if provider_reference:
        body["provider_reference"] = provider_reference
    return await client.post(
        f"/api/v1/admin/deposits/{deposit_id}/complete",
        json=body,
        headers={"Authorization": f"Bearer {admin_token}"},
    )


async def admin_fail(
    client: AsyncClient,
    admin_token: str,
    deposit_id: str,
    reason: str | None = None,
) -> dict:
    return await client.post(
        f"/api/v1/admin/deposits/{deposit_id}/fail",
        json={"reason": reason} if reason else {},
        headers={"Authorization": f"Bearer {admin_token}"},
    )


# ===========================================================================
# A. Deposit request creation
# ===========================================================================


class TestCreateDeposit:
    async def test_create_deposit_returns_201(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        _, token = await register_user(client, email="dep1@test.com")
        r = await create_deposit(client, token, amount="200.00")
        assert r.status_code == 201
        data = r.json()
        assert data["status"] == "pending"
        assert data["amount"] == "200.00"
        assert data["currency"] == "ZAR"
        assert data["completed_at"] is None

    async def test_create_deposit_stores_payment_provider(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        _, token = await register_user(client, email="dep2@test.com")
        r = await create_deposit(
            client, token, amount="100.00", payment_provider="payfast"
        )
        assert r.status_code == 201
        assert r.json()["payment_provider"] == "payfast"

    async def test_create_deposit_stores_client_reference(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        _, token = await register_user(client, email="dep3@test.com")
        r = await create_deposit(
            client, token, amount="50.00", client_reference="my-idempotency-key-1"
        )
        assert r.status_code == 201
        assert r.json()["client_reference"] == "my-idempotency-key-1"

    async def test_create_deposit_zero_amount_rejected(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        _, token = await register_user(client, email="dep4@test.com")
        r = await create_deposit(client, token, amount="0")
        assert r.status_code == 422

    async def test_create_deposit_negative_amount_rejected(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        _, token = await register_user(client, email="dep5@test.com")
        r = await create_deposit(client, token, amount="-10.00")
        assert r.status_code == 422

    async def test_create_deposit_unauthenticated_rejected(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        r = await client.post(
            "/api/v1/wallet/deposits", json={"amount": "100.00"}
        )
        assert r.status_code == 401

    async def test_create_deposit_does_not_credit_wallet(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """Creating a deposit must NOT immediately change the wallet balance."""
        _, token = await register_user(client, email="dep6@test.com")
        await create_deposit(client, token, amount="1000.00")

        wallet_r = await client.get(
            "/api/v1/wallet", headers={"Authorization": f"Bearer {token}"}
        )
        assert Decimal(wallet_r.json()["available_balance"]) == Decimal("0.00")


# ===========================================================================
# B. Admin deposit completion
# ===========================================================================


class TestAdminCompleteDeposit:
    async def test_complete_credits_available_balance(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        user_id, token = await register_user(client, email="dc1@test.com")
        admin_id, admin_token = await register_user(client, email="dca@test.com")
        await make_admin(db_session, admin_id)

        r = await create_deposit(client, token, amount="300.00")
        deposit_id = r.json()["id"]

        await admin_complete(client, admin_token, deposit_id)

        wallet_r = await client.get(
            "/api/v1/wallet", headers={"Authorization": f"Bearer {token}"}
        )
        assert Decimal(wallet_r.json()["available_balance"]) == Decimal("300.00")
        assert Decimal(wallet_r.json()["locked_balance"]) == Decimal("0.00")

    async def test_complete_returns_completed_status(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        _, token = await register_user(client, email="dc2@test.com")
        admin_id, admin_token = await register_user(client, email="dca2@test.com")
        await make_admin(db_session, admin_id)

        r = await create_deposit(client, token, amount="50.00")
        deposit_id = r.json()["id"]

        cr = await admin_complete(client, admin_token, deposit_id)
        assert cr.status_code == 200
        data = cr.json()
        assert data["status"] == "completed"
        assert data["completed_at"] is not None

    async def test_complete_stores_provider_reference(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        _, token = await register_user(client, email="dc3@test.com")
        admin_id, admin_token = await register_user(client, email="dca3@test.com")
        await make_admin(db_session, admin_id)

        r = await create_deposit(client, token, amount="100.00")
        deposit_id = r.json()["id"]

        cr = await admin_complete(
            client, admin_token, deposit_id, provider_reference="PAY-12345"
        )
        assert cr.json()["provider_reference"] == "PAY-12345"

    async def test_complete_creates_ledger_entry(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        user_id, token = await register_user(client, email="dc4@test.com")
        admin_id, admin_token = await register_user(client, email="dca4@test.com")
        await make_admin(db_session, admin_id)

        r = await create_deposit(client, token, amount="250.00")
        deposit_id = r.json()["id"]
        await admin_complete(client, admin_token, deposit_id)

        tx_r = await client.get(
            "/api/v1/wallet/transactions",
            headers={"Authorization": f"Bearer {token}"},
        )
        items = tx_r.json()["items"]
        assert len(items) == 1
        entry = items[0]
        assert entry["entry_type"] == "DEPOSIT"
        assert entry["direction"] == "credit"
        assert entry["balance_field"] == "available"
        assert Decimal(entry["amount"]) == Decimal("250.00")
        assert Decimal(entry["available_balance_after"]) == Decimal("250.00")

    async def test_complete_non_admin_rejected(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        user_id, token = await register_user(client, email="dc5@test.com")
        r = await create_deposit(client, token, amount="100.00")
        deposit_id = r.json()["id"]

        cr = await admin_complete(client, token, deposit_id)
        assert cr.status_code == 403

    async def test_complete_nonexistent_deposit_returns_404(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        admin_id, admin_token = await register_user(client, email="dcna@test.com")
        await make_admin(db_session, admin_id)

        r = await admin_complete(client, admin_token, str(uuid.uuid4()))
        assert r.status_code == 404


# ===========================================================================
# C. Admin deposit failure
# ===========================================================================


class TestAdminFailDeposit:
    async def test_fail_does_not_credit_wallet(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        user_id, token = await register_user(client, email="df1@test.com")
        admin_id, admin_token = await register_user(client, email="dfa@test.com")
        await make_admin(db_session, admin_id)

        r = await create_deposit(client, token, amount="500.00")
        deposit_id = r.json()["id"]

        await admin_fail(client, admin_token, deposit_id, reason="Test failure")

        wallet_r = await client.get(
            "/api/v1/wallet", headers={"Authorization": f"Bearer {token}"}
        )
        assert Decimal(wallet_r.json()["available_balance"]) == Decimal("0.00")

    async def test_fail_returns_failed_status(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        _, token = await register_user(client, email="df2@test.com")
        admin_id, admin_token = await register_user(client, email="dfa2@test.com")
        await make_admin(db_session, admin_id)

        r = await create_deposit(client, token, amount="100.00")
        deposit_id = r.json()["id"]

        fr = await admin_fail(client, admin_token, deposit_id)
        assert fr.status_code == 200
        assert fr.json()["status"] == "failed"
        assert fr.json()["failed_at"] is not None

    async def test_fail_creates_no_ledger_entries(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        user_id, token = await register_user(client, email="df3@test.com")
        admin_id, admin_token = await register_user(client, email="dfa3@test.com")
        await make_admin(db_session, admin_id)

        r = await create_deposit(client, token, amount="100.00")
        deposit_id = r.json()["id"]
        await admin_fail(client, admin_token, deposit_id)

        tx_r = await client.get(
            "/api/v1/wallet/transactions",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert tx_r.json()["total"] == 0


# ===========================================================================
# D. Idempotency and terminal-state guards
# ===========================================================================


class TestDepositTerminalStateGuards:
    async def test_complete_already_completed_returns_409(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        _, token = await register_user(client, email="dg1@test.com")
        admin_id, admin_token = await register_user(client, email="dga@test.com")
        await make_admin(db_session, admin_id)

        r = await create_deposit(client, token, amount="100.00")
        deposit_id = r.json()["id"]
        await admin_complete(client, admin_token, deposit_id)

        # Second complete must be rejected
        r2 = await admin_complete(client, admin_token, deposit_id)
        assert r2.status_code == 409

    async def test_fail_already_completed_returns_409(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        _, token = await register_user(client, email="dg2@test.com")
        admin_id, admin_token = await register_user(client, email="dga2@test.com")
        await make_admin(db_session, admin_id)

        r = await create_deposit(client, token, amount="100.00")
        deposit_id = r.json()["id"]
        await admin_complete(client, admin_token, deposit_id)

        r2 = await admin_fail(client, admin_token, deposit_id)
        assert r2.status_code == 409

    async def test_complete_already_failed_returns_409(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        _, token = await register_user(client, email="dg3@test.com")
        admin_id, admin_token = await register_user(client, email="dga3@test.com")
        await make_admin(db_session, admin_id)

        r = await create_deposit(client, token, amount="100.00")
        deposit_id = r.json()["id"]
        await admin_fail(client, admin_token, deposit_id)

        r2 = await admin_complete(client, admin_token, deposit_id)
        assert r2.status_code == 409

    async def test_double_complete_does_not_double_credit(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """Even if somehow called twice, wallet should only be credited once."""
        user_id, token = await register_user(client, email="dg4@test.com")
        admin_id, admin_token = await register_user(client, email="dga4@test.com")
        await make_admin(db_session, admin_id)

        r = await create_deposit(client, token, amount="200.00")
        deposit_id = r.json()["id"]
        await admin_complete(client, admin_token, deposit_id)
        # Second attempt fails — no second credit
        await admin_complete(client, admin_token, deposit_id)

        wallet_r = await client.get(
            "/api/v1/wallet", headers={"Authorization": f"Bearer {token}"}
        )
        assert Decimal(wallet_r.json()["available_balance"]) == Decimal("200.00")


# ===========================================================================
# E. User access control
# ===========================================================================


class TestDepositAccessControl:
    async def test_user_cannot_view_other_users_deposit(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        _, token1 = await register_user(client, email="dac1@test.com")
        _, token2 = await register_user(client, email="dac2@test.com")

        r = await create_deposit(client, token1, amount="100.00")
        deposit_id = r.json()["id"]

        r2 = await client.get(
            f"/api/v1/wallet/deposits/{deposit_id}",
            headers={"Authorization": f"Bearer {token2}"},
        )
        assert r2.status_code == 403

    async def test_user_can_view_own_deposit(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        _, token = await register_user(client, email="dac3@test.com")
        r = await create_deposit(client, token, amount="100.00")
        deposit_id = r.json()["id"]

        r2 = await client.get(
            f"/api/v1/wallet/deposits/{deposit_id}",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r2.status_code == 200

    async def test_list_only_returns_own_deposits(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        _, token1 = await register_user(client, email="dac4@test.com")
        _, token2 = await register_user(client, email="dac5@test.com")

        await create_deposit(client, token1, amount="100.00")
        await create_deposit(client, token1, amount="200.00")
        await create_deposit(client, token2, amount="50.00")

        r = await client.get(
            "/api/v1/wallet/deposits",
            headers={"Authorization": f"Bearer {token1}"},
        )
        data = r.json()
        assert data["total"] == 2
        assert all(d["amount"] != "50.00" for d in data["items"])

    async def test_admin_can_list_all_deposits(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        _, token1 = await register_user(client, email="dac6@test.com")
        _, token2 = await register_user(client, email="dac7@test.com")
        admin_id, admin_token = await register_user(client, email="daca@test.com")
        await make_admin(db_session, admin_id)

        await create_deposit(client, token1, amount="100.00")
        await create_deposit(client, token2, amount="200.00")

        r = await client.get(
            "/api/v1/admin/deposits",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert r.status_code == 200
        assert r.json()["total"] >= 2

    async def test_admin_list_non_admin_rejected(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        _, token = await register_user(client, email="dac8@test.com")
        r = await client.get(
            "/api/v1/admin/deposits",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 403

    async def test_admin_list_filter_by_status(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        _, token = await register_user(client, email="dac9@test.com")
        admin_id, admin_token = await register_user(client, email="daca2@test.com")
        await make_admin(db_session, admin_id)

        r1 = await create_deposit(client, token, amount="100.00")
        r2 = await create_deposit(client, token, amount="200.00")
        await admin_complete(client, admin_token, r1.json()["id"])

        # Filter by pending — should only return the second
        r = await client.get(
            "/api/v1/admin/deposits?status=pending",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert r.status_code == 200
        for item in r.json()["items"]:
            assert item["status"] == "pending"

        # Filter by completed
        r = await client.get(
            "/api/v1/admin/deposits?status=completed",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        for item in r.json()["items"]:
            assert item["status"] == "completed"
