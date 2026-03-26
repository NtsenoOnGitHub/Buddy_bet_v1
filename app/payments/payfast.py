"""PayFast payment gateway client.

Responsibilities
----------------
1. Build a signed checkout URL (hosted payment page redirect).
2. Verify an ITN (Instant Transaction Notification) signature.
3. Provide lightweight data classes — no I/O, fully unit-testable.

PayFast ITN flow
----------------
1. Backend calls ``build_checkout_params()`` to get a dict of POST params.
2. Frontend receives the checkout URL + params; redirects browser to PayFast.
3. User pays on PayFast-hosted page.
4. PayFast POSTs an ITN to ``PAYFAST_NOTIFY_URL`` (our webhook).
5. Webhook calls ``verify_itn_signature()`` + cross-checks merchant_id and
   amount_gross before crediting the wallet.

References
----------
- https://developers.payfast.co.za/docs
"""

from __future__ import annotations

import hashlib
import urllib.parse
from decimal import Decimal
from typing import Any

from app.core.config import get_settings


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _md5(data: str) -> str:
    return hashlib.md5(data.encode("utf-8")).hexdigest()


def _percent_encode(value: str) -> str:
    """URL-encode a value exactly as PayFast expects (upper-case %XX)."""
    return urllib.parse.quote_plus(value)


def _build_signature_string(params: dict[str, str], passphrase: str | None) -> str:
    """Return the MD5 pre-image string for the given parameter dict.

    Rules (from PayFast docs):
    - Alphabetical key order is NOT required — preserve insertion order.
    - Exclude the ``signature`` key itself.
    - URL-encode each value using percent-encoding (quote_plus).
    - Append ``&passphrase=<encoded>`` if passphrase is set.
    """
    parts: list[str] = []
    for key, value in params.items():
        if key == "signature":
            continue
        parts.append(f"{key}={_percent_encode(str(value))}")
    query_string = "&".join(parts)
    if passphrase:
        query_string += f"&passphrase={_percent_encode(passphrase)}"
    return query_string


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def build_checkout_params(
    *,
    deposit_id: str,
    amount: Decimal,
    item_name: str = "Buddy Bet Wallet Deposit",
    email_address: str | None = None,
    name_first: str | None = None,
    name_last: str | None = None,
) -> dict[str, str]:
    """Return an ordered dict of PayFast POST parameters including signature.

    ``deposit_id`` is used as ``m_payment_id`` so the ITN can be matched back
    to the internal ``DepositRequest`` row.

    The caller should POST these params to ``settings.payfast_checkout_url``
    (usually by redirecting the browser with a JS form-submit or by returning
    the checkout URL to the frontend).
    """
    settings = get_settings()

    params: dict[str, str] = {}

    # Merchant credentials
    params["merchant_id"] = settings.payfast_merchant_id
    params["merchant_key"] = settings.payfast_merchant_key

    # Return / notify URLs (backend-configured; never client-supplied)
    params["return_url"] = f"{settings.payfast_return_url}?deposit_id={deposit_id}"
    params["cancel_url"] = f"{settings.payfast_cancel_url}?deposit_id={deposit_id}"
    params["notify_url"] = settings.payfast_notify_url

    # Buyer information (optional but recommended)
    if name_first:
        params["name_first"] = name_first
    if name_last:
        params["name_last"] = name_last
    if email_address:
        params["email_address"] = email_address

    # Transaction details
    params["m_payment_id"] = deposit_id  # our internal reference
    params["amount"] = f"{amount:.2f}"
    params["item_name"] = item_name

    # Generate signature
    sig_string = _build_signature_string(params, settings.payfast_passphrase or None)
    params["signature"] = _md5(sig_string)

    return params


def build_checkout_url(params: dict[str, str]) -> str:
    """Return the full GET-style checkout URL (params as query string).

    PayFast accepts either a GET redirect or a browser form POST.  We use
    GET so the frontend only needs to do ``window.location.href = url``.
    """
    settings = get_settings()
    query_string = urllib.parse.urlencode(params)
    return f"{settings.payfast_checkout_url}?{query_string}"


def verify_itn_signature(
    itn_params: dict[str, Any],
    *,
    passphrase: str | None = None,
) -> bool:
    """Return True if the ITN ``signature`` field matches the computed hash.

    ``itn_params`` should be the raw POST body parsed as a flat dict of
    strings (e.g. ``dict(request.form)`` in Flask; ``await request.form()``
    in FastAPI → convert to plain dict).

    The ``signature`` key must be present in ``itn_params``; it is excluded
    from the hash computation as per PayFast spec.
    """
    received_sig = itn_params.get("signature", "")
    # Build the signature string from all params except 'signature'
    params_without_sig = {k: v for k, v in itn_params.items() if k != "signature"}
    sig_string = _build_signature_string(params_without_sig, passphrase)
    expected_sig = _md5(sig_string)
    return received_sig == expected_sig


def verify_itn(
    itn_params: dict[str, Any],
    *,
    expected_amount: Decimal,
) -> tuple[bool, str]:
    """Full ITN verification: signature + merchant_id + amount.

    Returns ``(True, "")`` on success or ``(False, reason)`` on failure.
    The caller should log ``reason`` and return HTTP 200 in both cases
    (PayFast will keep retrying on non-200 responses).
    """
    settings = get_settings()

    # 1. Signature
    if not verify_itn_signature(
        itn_params, passphrase=settings.payfast_passphrase or None
    ):
        return False, "signature_mismatch"

    # 2. Merchant ID
    if itn_params.get("merchant_id") != settings.payfast_merchant_id:
        return False, "merchant_id_mismatch"

    # 3. Amount
    try:
        gross = Decimal(str(itn_params.get("amount_gross", "0")))
    except Exception:
        return False, "invalid_amount_gross"

    if gross != expected_amount:
        return False, f"amount_mismatch: got {gross}, expected {expected_amount}"

    # 4. Payment status
    payment_status = itn_params.get("payment_status", "")
    if payment_status != "COMPLETE":
        return False, f"payment_status_not_complete: {payment_status}"

    return True, ""
