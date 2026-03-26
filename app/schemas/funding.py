"""Request and response schemas for the deposit and withdrawal flows.

All monetary values use DecimalStr — serialised as strings in JSON to avoid
float precision issues. Input accepts str / int / float / Decimal.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.enums import DepositStatus, WithdrawalStatus
from app.schemas.common import DecimalStr


# ---------------------------------------------------------------------------
# Deposit — user-facing
# ---------------------------------------------------------------------------


class CreateDepositRequest(BaseModel):
    """Body for POST /wallet/deposits."""

    amount: DecimalStr = Field(
        ...,
        description="Amount to deposit (must be positive). Serialised as decimal string.",
    )
    currency: str = Field(
        default="ZAR",
        max_length=3,
        description="ISO 4217 currency code. Defaults to ZAR.",
    )
    payment_provider: Optional[str] = Field(
        default=None,
        max_length=50,
        description="Name of the payment provider (e.g. 'stripe', 'payfast'). "
        "Omit for manual / test deposits.",
    )
    client_reference: Optional[str] = Field(
        default=None,
        max_length=200,
        description="Client-supplied idempotency key. Must be unique if provided.",
    )
    notes: Optional[str] = Field(
        default=None,
        description="Optional note for this deposit request.",
    )

    @field_validator("amount", mode="after")
    @classmethod
    def amount_must_be_positive(cls, v: Decimal) -> Decimal:
        if v <= Decimal("0"):
            raise ValueError("amount must be positive.")
        return v


class DepositResponse(BaseModel):
    """Single deposit request — returned by all deposit endpoints."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: uuid.UUID
    wallet_id: uuid.UUID
    amount: DecimalStr
    currency: str
    status: DepositStatus
    payment_provider: Optional[str] = None
    provider_reference: Optional[str] = None
    client_reference: Optional[str] = None
    notes: Optional[str] = None
    checkout_url: Optional[str] = None
    requested_at: datetime
    completed_at: Optional[datetime] = None
    failed_at: Optional[datetime] = None


# ---------------------------------------------------------------------------
# Deposit — PayFast initiation
# ---------------------------------------------------------------------------


class InitiateDepositRequest(BaseModel):
    """Body for POST /wallet/deposits/initiate."""

    amount: DecimalStr = Field(
        ...,
        description="Amount to deposit in ZAR (must be positive).",
    )
    email_address: Optional[str] = Field(
        default=None,
        description="User email pre-filled on the PayFast checkout page.",
    )
    name_first: Optional[str] = Field(
        default=None,
        max_length=100,
        description="User first name pre-filled on checkout.",
    )
    name_last: Optional[str] = Field(
        default=None,
        max_length=100,
        description="User last name pre-filled on checkout.",
    )

    @field_validator("amount", mode="after")
    @classmethod
    def amount_must_be_positive(cls, v: Decimal) -> Decimal:
        if v <= Decimal("0"):
            raise ValueError("amount must be positive.")
        return v


class InitiateDepositResponse(BaseModel):
    """Response for POST /wallet/deposits/initiate."""

    deposit_id: uuid.UUID
    checkout_url: str
    status: DepositStatus


# ---------------------------------------------------------------------------
# Deposit — admin actions
# ---------------------------------------------------------------------------


class AdminCompleteDepositRequest(BaseModel):
    """Body for POST /admin/deposits/{id}/complete."""

    provider_reference: Optional[str] = Field(
        default=None,
        max_length=200,
        description="External payment provider reference (e.g. Stripe payment intent ID). "
        "Must be unique if provided — used for idempotent webhook processing.",
    )
    notes: Optional[str] = Field(default=None, description="Admin completion note.")


class AdminFailDepositRequest(BaseModel):
    """Body for POST /admin/deposits/{id}/fail."""

    reason: Optional[str] = Field(default=None, description="Reason for failure.")


# ---------------------------------------------------------------------------
# Withdrawal — user-facing
# ---------------------------------------------------------------------------


class CreateWithdrawalRequest(BaseModel):
    """Body for POST /wallet/withdrawals."""

    amount: DecimalStr = Field(
        ...,
        description="Amount to withdraw (must be positive and <= available balance).",
    )
    currency: str = Field(default="ZAR", max_length=3)
    destination_account: str = Field(
        ...,
        max_length=200,
        description="Payout destination — bank account number, mobile number, etc.",
    )
    destination_type: Optional[str] = Field(
        default=None,
        max_length=50,
        description="Type of destination, e.g. 'bank_account' or 'mobile_money'.",
    )

    @field_validator("amount", mode="after")
    @classmethod
    def amount_must_be_positive(cls, v: Decimal) -> Decimal:
        if v <= Decimal("0"):
            raise ValueError("amount must be positive.")
        return v


class WithdrawalResponse(BaseModel):
    """Single withdrawal request — returned by all withdrawal endpoints."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: uuid.UUID
    wallet_id: uuid.UUID
    amount: DecimalStr
    currency: str
    status: WithdrawalStatus
    destination_account: Optional[str] = None
    destination_type: Optional[str] = None
    provider_reference: Optional[str] = None
    rejection_reason: Optional[str] = None
    requested_at: datetime
    approved_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    failed_at: Optional[datetime] = None


# ---------------------------------------------------------------------------
# Withdrawal — admin actions
# ---------------------------------------------------------------------------


class AdminRejectWithdrawalRequest(BaseModel):
    """Body for POST /admin/withdrawals/{id}/reject."""

    reason: Optional[str] = Field(default=None, description="Reason for rejection.")


class AdminFailWithdrawalRequest(BaseModel):
    """Body for POST /admin/withdrawals/{id}/fail."""

    reason: Optional[str] = Field(default=None, description="Reason for failure.")
