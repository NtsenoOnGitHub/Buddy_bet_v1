"""Tests for the withdrawal lifecycle.

Covers:
  A. Withdrawal request creation (hold funds, reject insufficient)
  B. Admin approve
  C. Admin complete (finalize debit)
  D. Admin reject (release funds)
  E. Admin fail (release funds)
  F. Terminal-state guards and idempotency
  G. Wallet and ledger integrity
  H. User access control
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from tests.conftest import fund_wallet, make_admin, register_user


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def create_withdrawal(
    client: AsyncClient,
    token: str,
    amount: str = "200.00",
    destination: str = "0821234567",
) -> dict:
    return await client.post(
        "/api/v1/wallet/withdrawals",
        json={
            "amount": amount,
            "destination_account": destination,
            "destination_type": "mobile_money",
        },
        headers={"Authorization": f"Bearer {token}"},
    )


async def create_deposit_and_complete(
    client: AsyncClient,
    token: str,
    admin_token: str,
    amount: str,
) -> str:
    """Create a deposit and immediately complete it. Returns deposit_id."""
    r = await client.post(
        "/api/v1/wallet/deposits",
        json={"amount": amount},
        headers={"Authorization": f"Bearer {token}"},
    )
    deposit_id = r.json()["id"]
    await client.post(
        f"/api/v1/admin/deposits/{deposit_id}/complete",
        json={},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    return deposit_id


async def admin_approve(client, admin_token, wid):
    return await client.post(
        f"/api/v1/admin/withdrawals/{wid}/approve",
        json={},
        headers={"Authorization": f"Bearer {admin_token}"},
    )


async def admin_complete_w(client, admin_token, wid):
    return await client.post(
        f"/api/v1/admin/withdrawals/{wid}/complete",
        json={},
        headers={"Authorization": f"Bearer {admin_token}"},
    )


async def admin_reject(client, admin_token, wid, reason=None):
    return await client.post(
        f"/api/v1/admin/withdrawals/{wid}/reject",
        json={"reason": reason} if reason else {},
        headers={"Authorization": f"Bearer {admin_token}"},
    )


async def admin_fail_w(client, admin_token, wid, reason=None):
    return await client.post(
        f"/api/v1/admin/withdrawals/{wid}/fail",
        json={"reason": reason} if reason else {},
        headers={"Authorization": f"Bearer {admin_token}"},
    )


# ===========================================================================
# A. Withdrawal request creation
# ===========================================================================


class TestCreateWithdrawal:
    async def test_create_withdrawal_returns_201(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        user_id, token = await register_user(client, email="wr1@test.com")
        await fund_wallet(db_session, user_id, Decimal("1000.00"))

        r = await create_withdrawal(client, token, amount="200.00")
        assert r.status_code == 201
        data = r.json()
        assert data["status"] == "pending"
        assert data["amount"] == "200.00"
        assert data["destination_account"] == "0821234567"

    async def test_create_withdrawal_holds_funds(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """available -= amount, locked += amount on creation."""
        user_id, token = await register_user(client, email="wr2@test.com")
        await fund_wallet(db_session, user_id, Decimal("1000.00"))

        await create_withdrawal(client, token, amount="300.00")

        wallet_r = await client.get(
            "/api/v1/wallet", headers={"Authorization": f"Bearer {token}"}
        )
        data = wallet_r.json()
        assert Decimal(data["available_balance"]) == Decimal("700.00")
        assert Decimal(data["locked_balance"]) == Decimal("300.00")
        assert Decimal(data["total_balance"]) == Decimal("1000.00")

    async def test_create_withdrawal_ledger_entry(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        user_id, token = await register_user(client, email="wr3@test.com")
        await fund_wallet(db_session, user_id, Decimal("500.00"))

        await create_withdrawal(client, token, amount="150.00")

        tx_r = await client.get(
            "/api/v1/wallet/transactions",
            headers={"Authorization": f"Bearer {token}"},
        )
        items = tx_r.json()["items"]
        # Expect 2 WITHDRAWAL_HOLD entries: available debit + locked credit
        hold_entries = [e for e in items if e["entry_type"] == "WITHDRAWAL_HOLD"]
        assert len(hold_entries) == 2
        debit = next(e for e in hold_entries if e["direction"] == "debit")
        credit = next(e for e in hold_entries if e["direction"] == "credit")
        assert debit["balance_field"] == "available"
        assert credit["balance_field"] == "locked"
        assert Decimal(debit["amount"]) == Decimal("150.00")

    async def test_create_withdrawal_insufficient_funds_rejected(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        user_id, token = await register_user(client, email="wr4@test.com")
        await fund_wallet(db_session, user_id, Decimal("100.00"))

        r = await create_withdrawal(client, token, amount="200.00")
        assert r.status_code == 422

    async def test_create_withdrawal_zero_amount_rejected(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        user_id, token = await register_user(client, email="wr5@test.com")
        await fund_wallet(db_session, user_id, Decimal("100.00"))

        r = await create_withdrawal(client, token, amount="0")
        assert r.status_code == 422

    async def test_create_withdrawal_negative_amount_rejected(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        user_id, token = await register_user(client, email="wr6@test.com")
        await fund_wallet(db_session, user_id, Decimal("100.00"))

        r = await create_withdrawal(client, token, amount="-50.00")
        assert r.status_code == 422

    async def test_create_withdrawal_unauthenticated_rejected(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        r = await client.post(
            "/api/v1/wallet/withdrawals",
            json={"amount": "100.00", "destination_account": "123"},
        )
        assert r.status_code == 401

    async def test_create_withdrawal_exactly_available_balance(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """Withdrawing the exact available balance should succeed."""
        user_id, token = await register_user(client, email="wr7@test.com")
        await fund_wallet(db_session, user_id, Decimal("500.00"))

        r = await create_withdrawal(client, token, amount="500.00")
        assert r.status_code == 201

        wallet_r = await client.get(
            "/api/v1/wallet", headers={"Authorization": f"Bearer {token}"}
        )
        assert Decimal(wallet_r.json()["available_balance"]) == Decimal("0.00")
        assert Decimal(wallet_r.json()["locked_balance"]) == Decimal("500.00")


# ===========================================================================
# B. Admin approve
# ===========================================================================


class TestApproveWithdrawal:
    async def test_approve_changes_status_to_approved(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        user_id, token = await register_user(client, email="wa1@test.com")
        admin_id, admin_token = await register_user(client, email="waa@test.com")
        await make_admin(db_session, admin_id)
        await fund_wallet(db_session, user_id, Decimal("500.00"))

        wid = (await create_withdrawal(client, token)).json()["id"]
        r = await admin_approve(client, admin_token, wid)

        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "approved"
        assert data["approved_at"] is not None

    async def test_approve_does_not_change_balances(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        user_id, token = await register_user(client, email="wa2@test.com")
        admin_id, admin_token = await register_user(client, email="waa2@test.com")
        await make_admin(db_session, admin_id)
        await fund_wallet(db_session, user_id, Decimal("500.00"))

        wid = (await create_withdrawal(client, token, amount="300.00")).json()["id"]
        await admin_approve(client, admin_token, wid)

        wallet_r = await client.get(
            "/api/v1/wallet", headers={"Authorization": f"Bearer {token}"}
        )
        assert Decimal(wallet_r.json()["available_balance"]) == Decimal("200.00")
        assert Decimal(wallet_r.json()["locked_balance"]) == Decimal("300.00")

    async def test_approve_non_pending_rejected(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        user_id, token = await register_user(client, email="wa3@test.com")
        admin_id, admin_token = await register_user(client, email="waa3@test.com")
        await make_admin(db_session, admin_id)
        await fund_wallet(db_session, user_id, Decimal("500.00"))

        wid = (await create_withdrawal(client, token)).json()["id"]
        await admin_approve(client, admin_token, wid)
        # Approve again — should fail
        r = await admin_approve(client, admin_token, wid)
        assert r.status_code == 409

    async def test_approve_non_admin_rejected(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        user_id, token = await register_user(client, email="wa4@test.com")
        await fund_wallet(db_session, user_id, Decimal("500.00"))
        wid = (await create_withdrawal(client, token)).json()["id"]

        r = await admin_approve(client, token, wid)
        assert r.status_code == 403


# ===========================================================================
# C. Admin complete (finalize debit)
# ===========================================================================


class TestCompleteWithdrawal:
    async def test_complete_debits_locked_balance(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        user_id, token = await register_user(client, email="wc1@test.com")
        admin_id, admin_token = await register_user(client, email="wca@test.com")
        await make_admin(db_session, admin_id)
        await fund_wallet(db_session, user_id, Decimal("600.00"))

        wid = (await create_withdrawal(client, token, amount="250.00")).json()["id"]
        await admin_approve(client, admin_token, wid)
        r = await admin_complete_w(client, admin_token, wid)

        assert r.status_code == 200
        assert r.json()["status"] == "completed"
        assert r.json()["completed_at"] is not None

        wallet_r = await client.get(
            "/api/v1/wallet", headers={"Authorization": f"Bearer {token}"}
        )
        data = wallet_r.json()
        assert Decimal(data["available_balance"]) == Decimal("350.00")
        assert Decimal(data["locked_balance"]) == Decimal("0.00")

    async def test_complete_creates_withdrawal_debit_ledger_entry(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        user_id, token = await register_user(client, email="wc2@test.com")
        admin_id, admin_token = await register_user(client, email="wca2@test.com")
        await make_admin(db_session, admin_id)
        await fund_wallet(db_session, user_id, Decimal("400.00"))

        wid = (await create_withdrawal(client, token, amount="100.00")).json()["id"]
        await admin_approve(client, admin_token, wid)
        await admin_complete_w(client, admin_token, wid)

        tx_r = await client.get(
            "/api/v1/wallet/transactions",
            headers={"Authorization": f"Bearer {token}"},
        )
        items = tx_r.json()["items"]
        debit_entries = [
            e for e in items
            if e["entry_type"] == "WITHDRAWAL" and e["direction"] == "debit"
        ]
        assert len(debit_entries) == 1
        assert debit_entries[0]["balance_field"] == "locked"
        assert Decimal(debit_entries[0]["amount"]) == Decimal("100.00")

    async def test_complete_from_pending_rejected(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """Must be approved first — can't skip directly to complete."""
        user_id, token = await register_user(client, email="wc3@test.com")
        admin_id, admin_token = await register_user(client, email="wca3@test.com")
        await make_admin(db_session, admin_id)
        await fund_wallet(db_session, user_id, Decimal("400.00"))

        wid = (await create_withdrawal(client, token)).json()["id"]
        r = await admin_complete_w(client, admin_token, wid)
        assert r.status_code == 409

    async def test_complete_already_completed_returns_409(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        user_id, token = await register_user(client, email="wc4@test.com")
        admin_id, admin_token = await register_user(client, email="wca4@test.com")
        await make_admin(db_session, admin_id)
        await fund_wallet(db_session, user_id, Decimal("400.00"))

        wid = (await create_withdrawal(client, token, amount="100.00")).json()["id"]
        await admin_approve(client, admin_token, wid)
        await admin_complete_w(client, admin_token, wid)

        r2 = await admin_complete_w(client, admin_token, wid)
        assert r2.status_code == 409


# ===========================================================================
# D. Admin reject (release funds)
# ===========================================================================


class TestRejectWithdrawal:
    async def test_reject_releases_funds_to_available(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        user_id, token = await register_user(client, email="wrej1@test.com")
        admin_id, admin_token = await register_user(client, email="wrja@test.com")
        await make_admin(db_session, admin_id)
        await fund_wallet(db_session, user_id, Decimal("500.00"))

        wid = (await create_withdrawal(client, token, amount="200.00")).json()["id"]
        r = await admin_reject(client, admin_token, wid, reason="Invalid account")

        assert r.status_code == 200
        assert r.json()["status"] == "rejected"
        assert r.json()["rejection_reason"] == "Invalid account"

        wallet_r = await client.get(
            "/api/v1/wallet", headers={"Authorization": f"Bearer {token}"}
        )
        data = wallet_r.json()
        assert Decimal(data["available_balance"]) == Decimal("500.00")
        assert Decimal(data["locked_balance"]) == Decimal("0.00")

    async def test_reject_creates_withdrawal_release_ledger_entries(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        user_id, token = await register_user(client, email="wrej2@test.com")
        admin_id, admin_token = await register_user(client, email="wrja2@test.com")
        await make_admin(db_session, admin_id)
        await fund_wallet(db_session, user_id, Decimal("500.00"))

        wid = (await create_withdrawal(client, token, amount="200.00")).json()["id"]
        await admin_reject(client, admin_token, wid)

        tx_r = await client.get(
            "/api/v1/wallet/transactions",
            headers={"Authorization": f"Bearer {token}"},
        )
        items = tx_r.json()["items"]
        release_entries = [e for e in items if e["entry_type"] == "WITHDRAWAL_RELEASE"]
        assert len(release_entries) == 2
        locked_debit = next(
            e for e in release_entries if e["balance_field"] == "locked"
        )
        available_credit = next(
            e for e in release_entries if e["balance_field"] == "available"
        )
        assert locked_debit["direction"] == "debit"
        assert available_credit["direction"] == "credit"

    async def test_reject_approved_withdrawal(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """Can reject from approved status too."""
        user_id, token = await register_user(client, email="wrej3@test.com")
        admin_id, admin_token = await register_user(client, email="wrja3@test.com")
        await make_admin(db_session, admin_id)
        await fund_wallet(db_session, user_id, Decimal("500.00"))

        wid = (await create_withdrawal(client, token, amount="100.00")).json()["id"]
        await admin_approve(client, admin_token, wid)
        r = await admin_reject(client, admin_token, wid)
        assert r.status_code == 200
        assert r.json()["status"] == "rejected"

        # Funds must be returned
        wallet_r = await client.get(
            "/api/v1/wallet", headers={"Authorization": f"Bearer {token}"}
        )
        assert Decimal(wallet_r.json()["available_balance"]) == Decimal("500.00")
        assert Decimal(wallet_r.json()["locked_balance"]) == Decimal("0.00")

    async def test_reject_already_rejected_returns_409(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        user_id, token = await register_user(client, email="wrej4@test.com")
        admin_id, admin_token = await register_user(client, email="wrja4@test.com")
        await make_admin(db_session, admin_id)
        await fund_wallet(db_session, user_id, Decimal("500.00"))

        wid = (await create_withdrawal(client, token)).json()["id"]
        await admin_reject(client, admin_token, wid)
        r2 = await admin_reject(client, admin_token, wid)
        assert r2.status_code == 409

    async def test_reject_completed_withdrawal_returns_409(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        user_id, token = await register_user(client, email="wrej5@test.com")
        admin_id, admin_token = await register_user(client, email="wrja5@test.com")
        await make_admin(db_session, admin_id)
        await fund_wallet(db_session, user_id, Decimal("500.00"))

        wid = (await create_withdrawal(client, token, amount="100.00")).json()["id"]
        await admin_approve(client, admin_token, wid)
        await admin_complete_w(client, admin_token, wid)
        r = await admin_reject(client, admin_token, wid)
        assert r.status_code == 409


# ===========================================================================
# E. Admin fail (release funds)
# ===========================================================================


class TestFailWithdrawal:
    async def test_fail_releases_funds_to_available(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        user_id, token = await register_user(client, email="wf1@test.com")
        admin_id, admin_token = await register_user(client, email="wfa@test.com")
        await make_admin(db_session, admin_id)
        await fund_wallet(db_session, user_id, Decimal("800.00"))

        wid = (await create_withdrawal(client, token, amount="400.00")).json()["id"]
        r = await admin_fail_w(client, admin_token, wid, reason="Provider error")

        assert r.status_code == 200
        assert r.json()["status"] == "failed"
        assert r.json()["failed_at"] is not None

        wallet_r = await client.get(
            "/api/v1/wallet", headers={"Authorization": f"Bearer {token}"}
        )
        assert Decimal(wallet_r.json()["available_balance"]) == Decimal("800.00")
        assert Decimal(wallet_r.json()["locked_balance"]) == Decimal("0.00")

    async def test_fail_creates_release_ledger_entries(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        user_id, token = await register_user(client, email="wf2@test.com")
        admin_id, admin_token = await register_user(client, email="wfa2@test.com")
        await make_admin(db_session, admin_id)
        await fund_wallet(db_session, user_id, Decimal("800.00"))

        wid = (await create_withdrawal(client, token, amount="200.00")).json()["id"]
        await admin_fail_w(client, admin_token, wid)

        tx_r = await client.get(
            "/api/v1/wallet/transactions",
            headers={"Authorization": f"Bearer {token}"},
        )
        items = tx_r.json()["items"]
        release = [e for e in items if e["entry_type"] == "WITHDRAWAL_RELEASE"]
        assert len(release) == 2

    async def test_fail_approved_withdrawal(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        user_id, token = await register_user(client, email="wf3@test.com")
        admin_id, admin_token = await register_user(client, email="wfa3@test.com")
        await make_admin(db_session, admin_id)
        await fund_wallet(db_session, user_id, Decimal("300.00"))

        wid = (await create_withdrawal(client, token, amount="100.00")).json()["id"]
        await admin_approve(client, admin_token, wid)
        r = await admin_fail_w(client, admin_token, wid)
        assert r.status_code == 200
        assert r.json()["status"] == "failed"

        wallet_r = await client.get(
            "/api/v1/wallet", headers={"Authorization": f"Bearer {token}"}
        )
        assert Decimal(wallet_r.json()["available_balance"]) == Decimal("300.00")
        assert Decimal(wallet_r.json()["locked_balance"]) == Decimal("0.00")

    async def test_fail_already_completed_returns_409(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        user_id, token = await register_user(client, email="wf4@test.com")
        admin_id, admin_token = await register_user(client, email="wfa4@test.com")
        await make_admin(db_session, admin_id)
        await fund_wallet(db_session, user_id, Decimal("300.00"))

        wid = (await create_withdrawal(client, token, amount="100.00")).json()["id"]
        await admin_approve(client, admin_token, wid)
        await admin_complete_w(client, admin_token, wid)
        r = await admin_fail_w(client, admin_token, wid)
        assert r.status_code == 409


# ===========================================================================
# F. Wallet and ledger integrity
# ===========================================================================


class TestWalletAndLedgerIntegrity:
    async def test_total_balance_unchanged_through_hold(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """total_balance = available + locked must not change when funds are held."""
        user_id, token = await register_user(client, email="wi1@test.com")
        await fund_wallet(db_session, user_id, Decimal("1000.00"))

        await create_withdrawal(client, token, amount="400.00")

        wallet_r = await client.get(
            "/api/v1/wallet", headers={"Authorization": f"Bearer {token}"}
        )
        data = wallet_r.json()
        total = Decimal(data["available_balance"]) + Decimal(data["locked_balance"])
        assert total == Decimal("1000.00")

    async def test_balances_never_negative_after_completion(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        user_id, token = await register_user(client, email="wi2@test.com")
        admin_id, admin_token = await register_user(client, email="wia@test.com")
        await make_admin(db_session, admin_id)
        await fund_wallet(db_session, user_id, Decimal("500.00"))

        wid = (await create_withdrawal(client, token, amount="500.00")).json()["id"]
        await admin_approve(client, admin_token, wid)
        await admin_complete_w(client, admin_token, wid)

        wallet_r = await client.get(
            "/api/v1/wallet", headers={"Authorization": f"Bearer {token}"}
        )
        data = wallet_r.json()
        assert Decimal(data["available_balance"]) >= Decimal("0.00")
        assert Decimal(data["locked_balance"]) >= Decimal("0.00")

    async def test_full_ledger_sequence_hold_then_complete(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """Full sequence: hold → complete. Verify all ledger entries are correct."""
        user_id, token = await register_user(client, email="wi3@test.com")
        admin_id, admin_token = await register_user(client, email="wia2@test.com")
        await make_admin(db_session, admin_id)
        await fund_wallet(db_session, user_id, Decimal("500.00"))

        wid = (await create_withdrawal(client, token, amount="200.00")).json()["id"]
        await admin_approve(client, admin_token, wid)
        await admin_complete_w(client, admin_token, wid)

        tx_r = await client.get(
            "/api/v1/wallet/transactions",
            headers={"Authorization": f"Bearer {token}"},
        )
        items = tx_r.json()["items"]
        types = {e["entry_type"] for e in items}
        assert "WITHDRAWAL_HOLD" in types
        assert "WITHDRAWAL" in types
        assert "WITHDRAWAL_RELEASE" not in types

    async def test_full_ledger_sequence_hold_then_reject(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """Full sequence: hold → reject. Verify release entries."""
        user_id, token = await register_user(client, email="wi4@test.com")
        admin_id, admin_token = await register_user(client, email="wia3@test.com")
        await make_admin(db_session, admin_id)
        await fund_wallet(db_session, user_id, Decimal("500.00"))

        wid = (await create_withdrawal(client, token, amount="200.00")).json()["id"]
        await admin_reject(client, admin_token, wid)

        tx_r = await client.get(
            "/api/v1/wallet/transactions",
            headers={"Authorization": f"Bearer {token}"},
        )
        items = tx_r.json()["items"]
        types = {e["entry_type"] for e in items}
        assert "WITHDRAWAL_HOLD" in types
        assert "WITHDRAWAL_RELEASE" in types
        assert "WITHDRAWAL" not in types

    async def test_deposit_and_withdrawal_combined_balance(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """Deposit 500 → withdraw 200. Final: available=300, locked=0 after complete."""
        user_id, token = await register_user(client, email="wi5@test.com")
        admin_id, admin_token = await register_user(client, email="wia4@test.com")
        await make_admin(db_session, admin_id)

        # Deposit 500 and complete it
        await create_deposit_and_complete(client, token, admin_token, "500.00")

        # Withdraw 200 and complete it
        wid = (await create_withdrawal(client, token, amount="200.00")).json()["id"]
        await admin_approve(client, admin_token, wid)
        await admin_complete_w(client, admin_token, wid)

        wallet_r = await client.get(
            "/api/v1/wallet", headers={"Authorization": f"Bearer {token}"}
        )
        data = wallet_r.json()
        assert Decimal(data["available_balance"]) == Decimal("300.00")
        assert Decimal(data["locked_balance"]) == Decimal("0.00")


# ===========================================================================
# G. User access control
# ===========================================================================


class TestWithdrawalAccessControl:
    async def test_user_cannot_view_other_users_withdrawal(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        user1_id, token1 = await register_user(client, email="wac1@test.com")
        _, token2 = await register_user(client, email="wac2@test.com")
        await fund_wallet(db_session, user1_id, Decimal("500.00"))

        wid = (await create_withdrawal(client, token1)).json()["id"]

        r = await client.get(
            f"/api/v1/wallet/withdrawals/{wid}",
            headers={"Authorization": f"Bearer {token2}"},
        )
        assert r.status_code == 403

    async def test_user_can_view_own_withdrawal(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        user_id, token = await register_user(client, email="wac3@test.com")
        await fund_wallet(db_session, user_id, Decimal("500.00"))

        wid = (await create_withdrawal(client, token)).json()["id"]

        r = await client.get(
            f"/api/v1/wallet/withdrawals/{wid}",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 200

    async def test_list_only_returns_own_withdrawals(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        user1_id, token1 = await register_user(client, email="wac4@test.com")
        user2_id, token2 = await register_user(client, email="wac5@test.com")
        await fund_wallet(db_session, user1_id, Decimal("1000.00"))
        await fund_wallet(db_session, user2_id, Decimal("1000.00"))

        await create_withdrawal(client, token1, amount="100.00")
        await create_withdrawal(client, token1, amount="200.00")
        await create_withdrawal(client, token2, amount="50.00")

        r = await client.get(
            "/api/v1/wallet/withdrawals",
            headers={"Authorization": f"Bearer {token1}"},
        )
        data = r.json()
        assert data["total"] == 2
        assert all(w["amount"] != "50.00" for w in data["items"])

    async def test_admin_can_list_all_withdrawals(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        user1_id, token1 = await register_user(client, email="wac6@test.com")
        user2_id, token2 = await register_user(client, email="wac7@test.com")
        admin_id, admin_token = await register_user(client, email="waca@test.com")
        await make_admin(db_session, admin_id)
        await fund_wallet(db_session, user1_id, Decimal("500.00"))
        await fund_wallet(db_session, user2_id, Decimal("500.00"))

        await create_withdrawal(client, token1, amount="100.00")
        await create_withdrawal(client, token2, amount="200.00")

        r = await client.get(
            "/api/v1/admin/withdrawals",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert r.status_code == 200
        assert r.json()["total"] >= 2

    async def test_admin_list_filter_by_pending(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        user_id, token = await register_user(client, email="wac8@test.com")
        admin_id, admin_token = await register_user(client, email="waca2@test.com")
        await make_admin(db_session, admin_id)
        await fund_wallet(db_session, user_id, Decimal("1000.00"))

        w1 = (await create_withdrawal(client, token, amount="100.00")).json()["id"]
        await create_withdrawal(client, token, amount="200.00")
        await admin_approve(client, admin_token, w1)

        r = await client.get(
            "/api/v1/admin/withdrawals?status=pending",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert r.status_code == 200
        for item in r.json()["items"]:
            assert item["status"] == "pending"

    async def test_admin_list_non_admin_rejected(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        _, token = await register_user(client, email="wac9@test.com")
        r = await client.get(
            "/api/v1/admin/withdrawals",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 403
