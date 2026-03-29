"""Payment provider webhook endpoints.

POST /payments/webhooks/payfast  — PayFast ITN (Instant Transaction Notification)

Security model
--------------
- No user authentication (PayFast posts server-to-server, not from a browser).
- Authenticity verified by MD5 signature over the full parameter set.
- Merchant ID matched against config to guard against cross-merchant replays.
- Amount matched against the stored DepositRequest to guard against tampering.
- Endpoint ALWAYS returns HTTP 200 so PayFast does not keep retrying — errors
  are logged and the deposit is left in its current state.

Idempotency
-----------
- Deposits in a terminal state (completed, failed, cancelled) are silently
  accepted and a 200 is returned. Double-delivery is safe.
- provider_reference (pf_payment_id) UNIQUE constraint prevents duplicate rows
  if the same event somehow drives two concurrent complete_deposit() calls.
"""

from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends, Request
from fastapi.responses import PlainTextResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.dependencies import get_db
from app.core.exceptions import ConflictError, NotFoundError
from app.models.enums import DepositStatus
from app.payments.payfast import verify_itn, verify_itn_signature, verify_itn_timestamp
from app.repositories.deposit_repository import DepositRepository
from app.services.deposit_service import DepositService

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post(
    "/webhooks/payfast",
    response_class=PlainTextResponse,
    status_code=200,
    include_in_schema=False,  # Internal endpoint — not shown in OpenAPI docs
)
async def payfast_itn(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> str:
    """Handle a PayFast Instant Transaction Notification (ITN).

    PayFast posts form-encoded data. This handler:
    1. Parses the raw form body.
    2. Verifies the ITN signature + merchant_id + amount_gross.
    3. Locates the internal DepositRequest via m_payment_id.
    4. Completes or fails the deposit based on payment_status.
    5. Returns "OK" (HTTP 200) in all cases to prevent retries.
    """
    settings = get_settings()

    # --- 1. Parse form body --------------------------------------------------
    try:
        form = await request.form()
        itn: dict[str, str] = {k: str(v) for k, v in form.multi_items()}
    except Exception as exc:
        logger.error("payfast_itn: failed to parse form body: %s", exc)
        return "OK"

    payment_status = itn.get("payment_status", "")
    m_payment_id = itn.get("m_payment_id", "")
    pf_payment_id = itn.get("pf_payment_id", "")

    logger.info(
        "payfast_itn: received m_payment_id=%s pf_payment_id=%s status=%s",
        m_payment_id,
        pf_payment_id,
        payment_status,
    )

    # --- 2. Locate deposit ---------------------------------------------------
    if not m_payment_id:
        logger.warning("payfast_itn: missing m_payment_id — ignoring")
        return "OK"

    try:
        deposit_id = uuid.UUID(m_payment_id)
    except ValueError:
        logger.warning("payfast_itn: invalid m_payment_id=%s — ignoring", m_payment_id)
        return "OK"

    deposit_repo = DepositRepository(db)
    try:
        deposit = await deposit_repo.get_by_id_or_404(deposit_id)
    except NotFoundError:
        logger.warning("payfast_itn: unknown deposit_id=%s — ignoring", deposit_id)
        return "OK"

    # --- 3a. Timestamp check (replay attack mitigation) ----------------------
    if not verify_itn_timestamp(itn):
        logger.warning(
            "payfast_itn: stale ITN rejected deposit=%s payment_date=%s",
            deposit_id,
            itn.get("payment_date"),
        )
        return "OK"

    # --- 3b. Verify signature + merchant_id (all ITNs) -----------------------
    # For COMPLETE ITNs we also verify amount_gross.
    # verify_itn() checks payment_status == "COMPLETE" internally, so we use
    # it only for COMPLETE; for CANCELLED/FAILED we verify sig + merchant only.
    from decimal import Decimal

    if payment_status == "COMPLETE":
        ok, reason = verify_itn(
            itn,
            expected_amount=Decimal(str(deposit.amount)),
        )
    else:
        # Verify signature and merchant_id for non-COMPLETE ITNs
        sig_ok = verify_itn_signature(
            itn, passphrase=settings.payfast_passphrase or None
        )
        merchant_ok = itn.get("merchant_id") == settings.payfast_merchant_id
        ok = sig_ok and merchant_ok
        if not ok:
            reason = "signature_mismatch" if not sig_ok else "merchant_id_mismatch"
        else:
            reason = ""

    if not ok:
        logger.error(
            "payfast_itn: verification failed deposit=%s reason=%s",
            deposit_id,
            reason,
        )
        return "OK"

    # --- 4. Process based on payment_status ----------------------------------
    deposit_svc = DepositService(db)

    if payment_status == "COMPLETE":
        # Guard: if already terminal, log and return 200 (idempotent)
        if deposit.status in {
            DepositStatus.completed,
            DepositStatus.failed,
            DepositStatus.cancelled,
        }:
            logger.info(
                "payfast_itn: deposit=%s already in terminal state=%s — skipping",
                deposit_id,
                deposit.status.value,
            )
            return "OK"

        try:
            await deposit_svc.complete_deposit(
                deposit_id=deposit_id,
                provider_reference=pf_payment_id or None,
                notes="PayFast ITN — COMPLETE",
            )
            logger.info(
                "payfast_itn: deposit=%s completed pf_payment_id=%s",
                deposit_id,
                pf_payment_id,
            )
        except ConflictError as exc:
            # Race condition — another request already completed it
            logger.info(
                "payfast_itn: deposit=%s conflict on complete (already done): %s",
                deposit_id,
                exc,
            )
        except Exception as exc:
            logger.exception(
                "payfast_itn: unexpected error completing deposit=%s: %s",
                deposit_id,
                exc,
            )

    elif payment_status in ("CANCELLED", "FAILED", "ERROR"):
        if deposit.status in {
            DepositStatus.completed,
            DepositStatus.failed,
            DepositStatus.cancelled,
        }:
            logger.info(
                "payfast_itn: deposit=%s already terminal, ignoring %s",
                deposit_id,
                payment_status,
            )
            return "OK"

        try:
            await deposit_svc.fail_deposit(
                deposit_id=deposit_id,
                reason=f"PayFast ITN — {payment_status}",
            )
            logger.info(
                "payfast_itn: deposit=%s failed payment_status=%s",
                deposit_id,
                payment_status,
            )
        except ConflictError as exc:
            logger.info(
                "payfast_itn: deposit=%s conflict on fail: %s",
                deposit_id,
                exc,
            )
        except Exception as exc:
            logger.exception(
                "payfast_itn: unexpected error failing deposit=%s: %s",
                deposit_id,
                exc,
            )
    else:
        logger.info(
            "payfast_itn: deposit=%s unhandled payment_status=%s — ignoring",
            deposit_id,
            payment_status,
        )

    return "OK"

