"""SQLAlchemy ORM models for platform_accounts and platform_ledger_entries.

PlatformAccount is an internal fee-collection account — not user-facing.
PlatformLedgerEntry is immutable; fn_prevent_mutation() blocks UPDATE/DELETE.

At MVP, there is exactly one platform account per currency (PLATFORM_FEES_ZAR).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, Enum as SAEnum, ForeignKey, Integer, Numeric, String, func
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.enums import (
    LedgerDirection,
    LedgerReferenceType,
    PlatformEntryType,
    SettlementPathType,
)


class PlatformAccount(Base):
    """Internal fee-collection account. One row per currency at MVP."""

    __tablename__ = "platform_accounts"

    id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=func.gen_random_uuid(),
    )
    account_code: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        unique=True,
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    currency: Mapped[str] = mapped_column(
        String(3),
        nullable=False,
        unique=True,
    )
    balance: Mapped[Decimal] = mapped_column(
        Numeric(15, 2),
        nullable=False,
        default=Decimal("0.00"),
        server_default="0.00",
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

    ledger_entries: Mapped[list["PlatformLedgerEntry"]] = relationship(
        "PlatformLedgerEntry",
        back_populates="platform_account",
        lazy="select",
    )

    def __repr__(self) -> str:
        return (
            f"<PlatformAccount id={self.id} code={self.account_code!r} "
            f"balance={self.balance} currency={self.currency}>"
        )


class PlatformLedgerEntry(Base):
    """Immutable record of every fee credit received by a platform account."""

    __tablename__ = "platform_ledger_entries"

    id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=func.gen_random_uuid(),
    )
    platform_account_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("platform_accounts.id"),
        nullable=False,
        index=True,
    )
    entry_type: Mapped[PlatformEntryType] = mapped_column(
        SAEnum(
            PlatformEntryType,
            name="platform_entry_type",
            create_type=False,
            native_enum=True,
        ),
        nullable=False,
    )
    # direction is always 'credit' (enforced by DB CHECK constraint)
    direction: Mapped[LedgerDirection] = mapped_column(
        SAEnum(LedgerDirection, name="ledger_direction", create_type=False, native_enum=True),
        nullable=False,
        default=LedgerDirection.credit,
        server_default="credit",
    )
    amount: Mapped[Decimal] = mapped_column(
        Numeric(15, 2),
        nullable=False,
    )
    # reference_type is always 'settlement' (enforced by DB CHECK constraint)
    reference_type: Mapped[LedgerReferenceType] = mapped_column(
        SAEnum(
            LedgerReferenceType,
            name="ledger_reference_type",
            create_type=False,
            native_enum=True,
        ),
        nullable=False,
        default=LedgerReferenceType.settlement,
        server_default="settlement",
    )
    # reference_id is always a bets.id
    reference_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("bets.id"),
        nullable=False,
        index=True,
    )
    balance_after: Mapped[Decimal] = mapped_column(
        Numeric(15, 2),
        nullable=False,
    )
    settlement_path: Mapped[SettlementPathType] = mapped_column(
        SAEnum(
            SettlementPathType,
            name="settlement_path_type",
            create_type=False,
            native_enum=True,
        ),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    # -----------------------------------------------------------------------
    # Relationships
    # -----------------------------------------------------------------------

    platform_account: Mapped[PlatformAccount] = relationship(
        "PlatformAccount",
        back_populates="ledger_entries",
        lazy="select",
    )

    def __repr__(self) -> str:
        return (
            f"<PlatformLedgerEntry id={self.id} type={self.entry_type} "
            f"amount={self.amount} path={self.settlement_path}>"
        )
