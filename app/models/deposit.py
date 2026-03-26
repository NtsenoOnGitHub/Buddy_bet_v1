"""DepositRequest ORM model.

Represents a user's intent to fund their wallet. Each request travels
through a status lifecycle:

    pending → processing → completed
                        ↘ failed
    pending → failed
    pending → cancelled

Balance is credited ONLY on completed. The admin (or a future payment
webhook) drives status transitions.

The model stores:
- payment_provider: name of the external provider (nullable for manual MVP)
- provider_reference: external transaction ID from the provider (unique, used
  for idempotent webhook processing)
- client_reference: user-supplied idempotency key (unique if provided)
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Optional

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.enums import DepositStatus


class DepositRequest(Base):
    __tablename__ = "deposit_requests"

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
    status: Mapped[DepositStatus] = mapped_column(
        sa.Enum(DepositStatus, name="deposit_status", create_type=False, native_enum=True),
        nullable=False,
        default=DepositStatus.pending,
        index=True,
    )
    # Payment provider metadata (populated later by webhook / admin)
    payment_provider: Mapped[Optional[str]] = mapped_column(
        sa.String(50), nullable=True
    )
    provider_reference: Mapped[Optional[str]] = mapped_column(
        sa.String(200),
        nullable=True,
        unique=True,  # prevents double-processing the same external event
    )
    # User-supplied idempotency key (unique if provided; NULLs are not unique)
    client_reference: Mapped[Optional[str]] = mapped_column(
        sa.String(200),
        nullable=True,
        unique=True,
    )
    notes: Mapped[Optional[str]] = mapped_column(sa.Text, nullable=True)

    # Timestamps
    requested_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    failed_at: Mapped[Optional[datetime]] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )

    # Indexes for common query patterns
    __table_args__ = (
        sa.Index("ix_deposit_requests_user_status", "user_id", "status"),
        sa.Index("ix_deposit_requests_requested_at", "requested_at"),
    )
