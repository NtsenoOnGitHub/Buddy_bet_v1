"""Tests for the PayFast ITN webhook and deposit initiation flow.

Provider calls are fully mocked — no live PayFast requests are made.

Coverage
--------
A. Deposit initiation
   - valid request creates deposit record
   - deposit status moves to processing
   - checkout_url is populated
   - wallet is NOT credited immediately
   - invalid amount rejected (too low / too high / negative)
   - PayFast disabled → 422

B. Webhook success path
   - COMPLETE ITN completes deposit + credits wallet + writes ledger entry

C. Webhook failure / cancel path
   - CANCELLED ITN fails deposit, wallet unchanged
   - FAILED ITN fails deposit, wallet unchanged

D. Idempotency
   - duplicate COMPLETE ITN does not double-credit
   - second COMPLETE on already-completed deposit → 200 (no error)

E. Security
   - invalid signature → 200 but deposit left in processing
   - wrong merchant_id → 200 but deposit unchanged
   - amount mismatch → 200 but deposit unchanged
   - unknown m_payment_id → 200, no crash

F. Edge cases
   - missing m_payment_id → 200
   - malformed m_payment_id (not UUID) → 200
   - unknown payment_status → 200, deposit unchanged

G. User access control
   - user can view own deposit
   - user cannot view another user's deposit (403)

H. Admin reconcile (verify)
   - admin can manually complete a processing deposit
"""

from __future__ import annotations

import contextlib
import hashlib
import urllib.parse
import uuid
from decimal import Decimal
from typing import Any
from unittest.mock import patch

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tests.conftest import make_admin, register_user

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PAYFAST_MERCHANT_ID = "test_merchant_001"
PAYFAST_MERCHANT_KEY = "test_key_001"

# ---------------------------------------------------------------------------
# Settings mock
# ---------------------------------------------------------------------------


def _make_fake_settings():
    """Return a fake settings object with PayFast enabled and known credentials."""
    from app.core.config import get_settings

    original = get_settings()

    overrides = {
        "payfast_enabled": True,
        "payfast_sandbox": True,
        "payfast_merchant_id": PAYFAST_MERCHANT_ID,
        "payfast_merchant_key": PAYFAST_MERCHANT_KEY,
        "payfast_passphrase": "",
        "payfast_return_url": "http://localhost:3000/wallet/deposit/return",
        "payfast_cancel_url": "http://localhost:3000/wallet/deposit/cancel",
        "payfast_notify_url": "http://localhost:8000/api/v1/payments/webhooks/payfast",
        "min_stake_amount": Decimal("10.00"),
        "max_stake_amount": Decimal("10000.00"),
        "platform_currency": "ZAR",
    }

    class _FakeSettings:
        def __getattr__(self, name: str):
            if name in overrides:
                return overrides[name]
            return getattr(original, name)

    return _FakeSettings()


@contextlib.contextmanager
def payfast_enabled():
    """Context manager that enables PayFast with test credentials in all modules."""
    fake = _make_fake_settings()
    with (
        patch("app.services.deposit_service.get_settings", return_value=fake),
        patch("app.payments.payfast.get_settings", return_value=fake),
        patch("app.api.v1.endpoints.webhooks.get_settings", return_value=fake),
    ):
        yield fake


# ---------------------------------------------------------------------------
# ITN builder
# ---------------------------------------------------------------------------


def _make_itn(
    *,
    merchant_id: str,
    m_payment_id: str,
    pf_payment_id: str,
    amount_gross: str,
    payment_status: str,
    passphrase: str = "",
) -> dict[str, str]:
    """Build a PayFast ITN parameter dict with a valid MD5 signature."""
    params: dict[str, str] = {
        "merchant_id": merchant_id,
        "m_payment_id": m_payment_id,
        "pf_payment_id": pf_payment_id,
        "amount_gross": amount_gross,
        "payment_status": payment_status,
    }
    parts = [f"{k}={urllib.parse.quote_plus(v)}" for k, v in params.items()]
    sig_string = "&".join(parts)
    if passphrase:
        sig_string += f"&passphrase={urllib.parse.quote_plus(passphrase)}"
    params["signature"] = hashlib.md5(sig_string.encode()).hexdigest()
    return params


# ---------------------------------------------------------------------------
# Shared HTTP helpers
# ---------------------------------------------------------------------------


async def _initiate(client: AsyncClient, token: str, amount: str = "500.00") -> Any:
    return await client.post(
        "/api/v1/wallet/deposits/initiate",
        json={"amount": amount},
        headers={"Authorization": f"Bearer {token}"},
    )


async def _post_itn(client: AsyncClient, params: dict[str, str]) -> Any:
    return await client.post(
        "/api/v1/payments/webhooks/payfast",
        data=params,
    )


async def _complete_itn(
    client: AsyncClient,
    deposit_id: str,
    pf_id: str,
    amount: str = "500.00",
) -> Any:
    itn = _make_itn(
        merchant_id=PAYFAST_MERCHANT_ID,
        m_payment_id=deposit_id,
        pf_payment_id=pf_id,
        amount_gross=amount,
        payment_status="COMPLETE",
    )
    return await _post_itn(client, itn)


# ---------------------------------------------------------------------------
# A. Deposit initiation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_initiate_creates_processing_record(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    _, token = await register_user(client, email="init1@example.com")
    with payfast_enabled():
        resp = await _initiate(client, token, "200.00")
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["status"] == "processing"
    assert data["checkout_url"]
    assert "sandbox.payfast.co.za" in data["checkout_url"]
    assert str(data["deposit_id"]) in data["checkout_url"]


@pytest.mark.asyncio
async def test_initiate_stores_checkout_url_on_record(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    from app.models.deposit import DepositRequest

    _, token = await register_user(client, email="init2@example.com")
    with payfast_enabled():
        resp = await _initiate(client, token, "200.00")
    assert resp.status_code == 201
    dep_id = uuid.UUID(resp.json()["deposit_id"])

    result = await db_session.execute(
        select(DepositRequest).where(DepositRequest.id == dep_id)
    )
    row = result.scalar_one()
    assert row.checkout_url is not None
    assert row.payment_provider == "payfast"
    assert row.status.value == "processing"


@pytest.mark.asyncio
async def test_initiate_does_not_credit_wallet(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    from app.models.wallet import Wallet

    user_id, token = await register_user(client, email="init3@example.com")
    with payfast_enabled():
        await _initiate(client, token, "500.00")

    result = await db_session.execute(
        select(Wallet).where(Wallet.user_id == uuid.UUID(user_id))
    )
    wallet = result.scalar_one()
    assert wallet.available_balance == Decimal("0.00")
    assert wallet.locked_balance == Decimal("0.00")


@pytest.mark.asyncio
async def test_initiate_amount_too_low_returns_422(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    _, token = await register_user(client, email="init4@example.com")
    with payfast_enabled():
        resp = await _initiate(client, token, "1.00")
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_initiate_amount_too_high_returns_422(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    _, token = await register_user(client, email="init5@example.com")
    with payfast_enabled():
        resp = await _initiate(client, token, "99999.00")
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_initiate_negative_amount_returns_422(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    _, token = await register_user(client, email="init6@example.com")
    with payfast_enabled():
        resp = await _initiate(client, token, "-100.00")
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_initiate_payfast_disabled_returns_422(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    _, token = await register_user(client, email="init7@example.com")
    # No payfast_enabled() context — payfast_enabled defaults to False
    resp = await _initiate(client, token, "200.00")
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# B. Webhook success path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_itn_complete_credits_wallet(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    from app.models.wallet import Wallet

    user_id, token = await register_user(client, email="itn1@example.com")
    with payfast_enabled():
        resp = await _initiate(client, token, "200.00")
        deposit_id = resp.json()["deposit_id"]
        r = await _complete_itn(client, deposit_id, "PF_001", "200.00")
    assert r.status_code == 200

    await db_session.execute(
        select(Wallet).where(Wallet.user_id == uuid.UUID(user_id))
    )
    # Expire cached instance to get DB state
    db_session.expire_all()
    result = await db_session.execute(
        select(Wallet).where(Wallet.user_id == uuid.UUID(user_id))
    )
    wallet = result.scalar_one()
    assert wallet.available_balance == Decimal("200.00")
    assert wallet.locked_balance == Decimal("0.00")


@pytest.mark.asyncio
async def test_itn_complete_sets_deposit_completed(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    from app.models.deposit import DepositRequest

    _, token = await register_user(client, email="itn2@example.com")
    with payfast_enabled():
        resp = await _initiate(client, token, "300.00")
        deposit_id = resp.json()["deposit_id"]
        await _complete_itn(client, deposit_id, "PF_002", "300.00")

    db_session.expire_all()
    result = await db_session.execute(
        select(DepositRequest).where(DepositRequest.id == uuid.UUID(deposit_id))
    )
    deposit = result.scalar_one()
    assert deposit.status.value == "completed"
    assert deposit.provider_reference == "PF_002"
    assert deposit.completed_at is not None


@pytest.mark.asyncio
async def test_itn_complete_writes_ledger_entry(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    from app.models.ledger import LedgerEntry

    user_id, token = await register_user(client, email="itn3@example.com")
    with payfast_enabled():
        resp = await _initiate(client, token, "150.00")
        deposit_id = resp.json()["deposit_id"]
        await _complete_itn(client, deposit_id, "PF_003", "150.00")

    db_session.expire_all()
    result = await db_session.execute(
        select(LedgerEntry).where(
            LedgerEntry.user_id == uuid.UUID(user_id),
            LedgerEntry.reference_id == uuid.UUID(deposit_id),
        )
    )
    entries = result.scalars().all()
    assert len(entries) == 1
    entry = entries[0]
    assert entry.entry_type.value == "DEPOSIT"
    assert entry.direction.value == "credit"
    assert entry.amount == Decimal("150.00")


# ---------------------------------------------------------------------------
# C. Webhook failure / cancel path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_itn_cancelled_fails_deposit_no_credit(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    from app.models.deposit import DepositRequest
    from app.models.wallet import Wallet

    user_id, token = await register_user(client, email="itn4@example.com")
    with payfast_enabled():
        resp = await _initiate(client, token, "100.00")
        deposit_id = resp.json()["deposit_id"]
        itn = _make_itn(
            merchant_id=PAYFAST_MERCHANT_ID,
            m_payment_id=deposit_id,
            pf_payment_id="PF_004",
            amount_gross="100.00",
            payment_status="CANCELLED",
        )
        r = await _post_itn(client, itn)
    assert r.status_code == 200

    db_session.expire_all()
    dep_result = await db_session.execute(
        select(DepositRequest).where(DepositRequest.id == uuid.UUID(deposit_id))
    )
    assert dep_result.scalar_one().status.value == "failed"

    wal_result = await db_session.execute(
        select(Wallet).where(Wallet.user_id == uuid.UUID(user_id))
    )
    assert wal_result.scalar_one().available_balance == Decimal("0.00")


@pytest.mark.asyncio
async def test_itn_failed_status_fails_deposit(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    from app.models.deposit import DepositRequest

    _, token = await register_user(client, email="itn5@example.com")
    with payfast_enabled():
        resp = await _initiate(client, token, "100.00")
        deposit_id = resp.json()["deposit_id"]
        itn = _make_itn(
            merchant_id=PAYFAST_MERCHANT_ID,
            m_payment_id=deposit_id,
            pf_payment_id="PF_005",
            amount_gross="100.00",
            payment_status="FAILED",
        )
        await _post_itn(client, itn)

    db_session.expire_all()
    result = await db_session.execute(
        select(DepositRequest).where(DepositRequest.id == uuid.UUID(deposit_id))
    )
    assert result.scalar_one().status.value == "failed"


# ---------------------------------------------------------------------------
# D. Idempotency
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_duplicate_complete_itn_does_not_double_credit(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    from app.models.wallet import Wallet

    user_id, token = await register_user(client, email="itn6@example.com")
    with payfast_enabled():
        resp = await _initiate(client, token, "500.00")
        deposit_id = resp.json()["deposit_id"]
        r1 = await _complete_itn(client, deposit_id, "PF_006", "500.00")
        r2 = await _complete_itn(client, deposit_id, "PF_006", "500.00")  # duplicate
    assert r1.status_code == 200
    assert r2.status_code == 200  # must not crash

    db_session.expire_all()
    result = await db_session.execute(
        select(Wallet).where(Wallet.user_id == uuid.UUID(user_id))
    )
    wallet = result.scalar_one()
    # Credited exactly once
    assert wallet.available_balance == Decimal("500.00")


@pytest.mark.asyncio
async def test_complete_itn_on_already_completed_returns_200(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    _, token = await register_user(client, email="itn7@example.com")
    with payfast_enabled():
        resp = await _initiate(client, token, "100.00")
        deposit_id = resp.json()["deposit_id"]
        await _complete_itn(client, deposit_id, "PF_007", "100.00")
        # Second call — different pf_payment_id
        r = await _complete_itn(client, deposit_id, "PF_007_RETRY", "100.00")
    assert r.status_code == 200  # must not raise


# ---------------------------------------------------------------------------
# E. Security
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_itn_bad_signature_leaves_deposit_unchanged(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    from app.models.deposit import DepositRequest

    _, token = await register_user(client, email="itn8@example.com")
    with payfast_enabled():
        resp = await _initiate(client, token, "100.00")
        deposit_id = resp.json()["deposit_id"]
        itn = _make_itn(
            merchant_id=PAYFAST_MERCHANT_ID,
            m_payment_id=deposit_id,
            pf_payment_id="PF_008",
            amount_gross="100.00",
            payment_status="COMPLETE",
        )
        itn["signature"] = "bad_sig_000000000000000000000000"
        r = await _post_itn(client, itn)
    assert r.status_code == 200

    db_session.expire_all()
    result = await db_session.execute(
        select(DepositRequest).where(DepositRequest.id == uuid.UUID(deposit_id))
    )
    # Deposit still in processing — not completed
    assert result.scalar_one().status.value == "processing"


@pytest.mark.asyncio
async def test_itn_wrong_merchant_id_leaves_deposit_unchanged(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    from app.models.deposit import DepositRequest

    _, token = await register_user(client, email="itn9@example.com")
    with payfast_enabled():
        resp = await _initiate(client, token, "100.00")
        deposit_id = resp.json()["deposit_id"]
        # Sign with rogue merchant_id
        itn = _make_itn(
            merchant_id="ROGUE_MERCHANT",
            m_payment_id=deposit_id,
            pf_payment_id="PF_009",
            amount_gross="100.00",
            payment_status="COMPLETE",
        )
        r = await _post_itn(client, itn)
    assert r.status_code == 200

    db_session.expire_all()
    result = await db_session.execute(
        select(DepositRequest).where(DepositRequest.id == uuid.UUID(deposit_id))
    )
    assert result.scalar_one().status.value == "processing"


@pytest.mark.asyncio
async def test_itn_amount_mismatch_leaves_deposit_unchanged(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    from app.models.deposit import DepositRequest
    from app.models.wallet import Wallet

    user_id, token = await register_user(client, email="itn10@example.com")
    with payfast_enabled():
        resp = await _initiate(client, token, "100.00")
        deposit_id = resp.json()["deposit_id"]
        # Tampered amount — same merchant, bad amount
        itn = _make_itn(
            merchant_id=PAYFAST_MERCHANT_ID,
            m_payment_id=deposit_id,
            pf_payment_id="PF_010",
            amount_gross="9999.00",  # mismatch
            payment_status="COMPLETE",
        )
        r = await _post_itn(client, itn)
    assert r.status_code == 200

    db_session.expire_all()
    dep_result = await db_session.execute(
        select(DepositRequest).where(DepositRequest.id == uuid.UUID(deposit_id))
    )
    assert dep_result.scalar_one().status.value == "processing"

    wal_result = await db_session.execute(
        select(Wallet).where(Wallet.user_id == uuid.UUID(user_id))
    )
    assert wal_result.scalar_one().available_balance == Decimal("0.00")


@pytest.mark.asyncio
async def test_itn_unknown_deposit_returns_200(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    unknown_id = str(uuid.uuid4())
    with payfast_enabled():
        itn = _make_itn(
            merchant_id=PAYFAST_MERCHANT_ID,
            m_payment_id=unknown_id,
            pf_payment_id="PF_UNKNOWN",
            amount_gross="100.00",
            payment_status="COMPLETE",
        )
        r = await _post_itn(client, itn)
    assert r.status_code == 200


# ---------------------------------------------------------------------------
# F. Edge cases
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_itn_missing_m_payment_id_returns_200(client: AsyncClient) -> None:
    r = await client.post(
        "/api/v1/payments/webhooks/payfast",
        data={"payment_status": "COMPLETE", "signature": "irrelevant"},
    )
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_itn_malformed_m_payment_id_returns_200(client: AsyncClient) -> None:
    r = await client.post(
        "/api/v1/payments/webhooks/payfast",
        data={"m_payment_id": "not-a-uuid", "payment_status": "COMPLETE", "signature": "x"},
    )
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_itn_unknown_payment_status_leaves_deposit_unchanged(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    from app.models.deposit import DepositRequest

    _, token = await register_user(client, email="itn11@example.com")
    with payfast_enabled():
        resp = await _initiate(client, token, "100.00")
        deposit_id = resp.json()["deposit_id"]
        itn = _make_itn(
            merchant_id=PAYFAST_MERCHANT_ID,
            m_payment_id=deposit_id,
            pf_payment_id="PF_011",
            amount_gross="100.00",
            payment_status="UNKNOWN_STATUS",
        )
        r = await _post_itn(client, itn)
    assert r.status_code == 200

    db_session.expire_all()
    result = await db_session.execute(
        select(DepositRequest).where(DepositRequest.id == uuid.UUID(deposit_id))
    )
    assert result.scalar_one().status.value == "processing"


# ---------------------------------------------------------------------------
# G. User access control
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_user_can_view_own_deposit(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    _, token = await register_user(client, email="acc1@example.com")
    with payfast_enabled():
        resp = await _initiate(client, token, "200.00")
    deposit_id = resp.json()["deposit_id"]

    r = await client.get(
        f"/api/v1/wallet/deposits/{deposit_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200
    assert r.json()["id"] == deposit_id


@pytest.mark.asyncio
async def test_user_cannot_view_another_users_deposit(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    _, token1 = await register_user(client, email="acc2@example.com")
    _, token2 = await register_user(client, email="acc3@example.com")
    with payfast_enabled():
        resp = await _initiate(client, token1, "200.00")
    deposit_id = resp.json()["deposit_id"]

    r = await client.get(
        f"/api/v1/wallet/deposits/{deposit_id}",
        headers={"Authorization": f"Bearer {token2}"},
    )
    assert r.status_code == 403


# ---------------------------------------------------------------------------
# H. Admin reconciliation (verify)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_admin_verify_completes_deposit_and_credits_wallet(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    from app.models.enums import UserRole
    from app.models.user import User
    from app.models.wallet import Wallet
    from app.services.deposit_service import DepositService

    user_id, _ = await register_user(client, email="verify_user@example.com")
    admin_id, _ = await register_user(client, email="verify_admin@example.com", password="adminpass123")
    await make_admin(db_session, admin_id)
    await db_session.flush()

    # Create a pending deposit directly (skip PayFast redirect)
    svc = DepositService(db_session)
    deposit = await svc.create_deposit(
        user_id=uuid.UUID(user_id),
        amount=Decimal("250.00"),
        currency="ZAR",
        payment_provider="payfast",
    )
    await db_session.flush()

    # Login as admin to get token
    login_resp = await client.post(
        "/api/v1/auth/login",
        json={"email": "verify_admin@example.com", "password": "adminpass123"},
    )
    assert login_resp.status_code == 200
    admin_token = login_resp.json()["access_token"]

    r = await client.post(
        f"/api/v1/admin/deposits/{deposit.id}/verify",
        json={"pf_payment_id": "PF_MANUAL_001"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["status"] == "completed"
    assert data["provider_reference"] == "PF_MANUAL_001"

    db_session.expire_all()
    wal_result = await db_session.execute(
        select(Wallet).where(Wallet.user_id == uuid.UUID(user_id))
    )
    wallet = wal_result.scalar_one()
    assert wallet.available_balance == Decimal("250.00")
