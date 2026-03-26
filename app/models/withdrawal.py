"""WithdrawalRequest ORM model.

Represents a user's request to withdraw funds from their wallet. Lifecycle:

    pending → approved → completed
                       ↘ failed
    pending → rejected
    approved → rejected   (admin can reject after approval)
    pending/approved → failed

Funds are HELD (available → locked) on request creation.
Funds are DEBITED from locked on completion.
Funds are RELEASED (locked → available) on rejection or failure.

This ensures no balance disappears without a corresponding terminal state.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Optional

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.enums import WithdrawalStatus


class WithdrawalRequest(Base):
    __tablename__ = "withdrawal_requests"

    id: Mapped[uuid.UUID] = mapped_column(
        sa.dialects.postgresql.UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        sa.dialects.postgresql.UUID(as_uuid=True),
        sa.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    wallet_id: Mapped[uuid.UUID] = mapped_column(
        sa.dialects.postgresql.UUID(as_uuid=True),
        sa.ForeignKey("wallets.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    amount: Mapped[Decimal] = mapped_column(
        sa.Numeric(15, 2),
        nullable=False,
    )
    currency: Mapped[str] = mapped_column(
        sa.String(3),
        nullable=False,
        default="ZAR",
    )
    status: Mapped[WithdrawalStatus] = mapped_column(
        sa.Enum(WithdrawalStatus, name="withdrawal_status", create_type=False, native_enum=True),
        nullable=False,
        default=WithdrawalStatus.pending,
        index=True,
    )
    # Payout destination — free-text placeholder for MVP
    # (future: structured bank account / mobile money object)
    destination_account: Mapped[Optional[str]] = mapped_column(
        sa.String(200), nullable=True
    )
    destination_type: Mapped[Optional[str]] = mapped_column(
        sa.String(50), nullable=True  # e.g. "bank_account", "mobile_money"
    )
    # External provider reference — unique for idempotent webhook processing
    provider_reference: Mapped[Optional[str]] = mapped_column(
        sa.String(200), nullable=True, unique=True
    )
    rejection_reason: Mapped[Optional[str]] = mapped_column(sa.Text, nullable=True)

    # Timestamps
    requested_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
    )
    approved_at: Mapped[Optional[datetime]] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    failed_at: Mapped[Optional[datetime]] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        sa.Index("ix_withdrawal_requests_user_status", "user_id", "status"),
        sa.Index("ix_withdrawal_requests_requested_at", "requested_at"),
    )
