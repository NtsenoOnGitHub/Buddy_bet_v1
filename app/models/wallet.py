"""SQLAlchemy ORM model for the 'wallets' table.

Design notes:
- total_balance is NOT a stored column. It is always computed as
  available_balance + locked_balance and returned by the WalletResponse schema.
- The version column is an optimistic lock counter incremented on every update.
- All monetary columns use Numeric(15, 2) — never float.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, String, func
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Wallet(Base):
    """User wallet. Stores available_balance and locked_balance independently."""

    __tablename__ = "wallets"

    id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=func.gen_random_uuid(),
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=False,
        unique=True,
    )
    available_balance: Mapped[Decimal] = mapped_column(
        Numeric(15, 2),
        nullable=False,
        default=Decimal("0.00"),
        server_default="0.00",
    )
    locked_balance: Mapped[Decimal] = mapped_column(
        Numeric(15, 2),
        nullable=False,
        default=Decimal("0.00"),
        server_default="0.00",
    )
    currency: Mapped[str] = mapped_column(
        String(3),
        nullable=False,
        default="ZAR",
        server_default="ZAR",
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
    version: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )

    # -----------------------------------------------------------------------
    # Relationships
    # -----------------------------------------------------------------------

    user: Mapped["User"] = relationship(  # type: ignore[name-defined]  # noqa: F821
        "User",
        back_populates="wallet",
        lazy="select",
    )

    # -----------------------------------------------------------------------
    # Computed property (not stored — do not use for DB writes)
    # -----------------------------------------------------------------------

    @property
    def total_balance(self) -> Decimal:
        """Computed total balance = available + locked. Never stored in DB."""
        return self.available_balance + self.locked_balance

    def __repr__(self) -> str:
        return (
            f"<Wallet id={self.id} user_id={self.user_id} "
            f"available={self.available_balance} locked={self.locked_balance}>"
        )
