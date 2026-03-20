"""SQLAlchemy ORM model for the 'ledger_entries' table.

Ledger entries are IMMUTABLE — the database triggers fn_prevent_mutation()
prevent any UPDATE or DELETE. The application layer must never attempt to
modify a LedgerEntry row; corrections are compensating entries only.

Each row represents a single atomic change to ONE balance field of ONE wallet.
Operations affecting both fields (e.g. STAKE_LOCK) produce TWO entries with
the same reference_id wrapped in the same transaction.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import DateTime, Enum as SAEnum, ForeignKey, Numeric, Text, func
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.enums import (
    BalanceField,
    LedgerDirection,
    LedgerEntryType,
    LedgerReferenceType,
)


class LedgerEntry(Base):
    """Immutable financial event log row. One per balance-field change."""

    __tablename__ = "ledger_entries"

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
        index=True,
    )
    wallet_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("wallets.id"),
        nullable=False,
        index=True,
    )
    entry_type: Mapped[LedgerEntryType] = mapped_column(
        SAEnum(
            LedgerEntryType,
            name="ledger_entry_type",
            create_type=False,
            native_enum=True,
        ),
        nullable=False,
    )
    balance_field: Mapped[BalanceField] = mapped_column(
        SAEnum(BalanceField, name="balance_field", create_type=False, native_enum=True),
        nullable=False,
    )
    direction: Mapped[LedgerDirection] = mapped_column(
        SAEnum(LedgerDirection, name="ledger_direction", create_type=False, native_enum=True),
        nullable=False,
    )
    amount: Mapped[Decimal] = mapped_column(
        Numeric(15, 2),
        nullable=False,
    )
    reference_type: Mapped[LedgerReferenceType] = mapped_column(
        SAEnum(
            LedgerReferenceType,
            name="ledger_reference_type",
            create_type=False,
            native_enum=True,
        ),
        nullable=False,
    )
    reference_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        nullable=False,
        index=True,
    )
    available_balance_after: Mapped[Decimal] = mapped_column(
        Numeric(15, 2),
        nullable=False,
    )
    locked_balance_after: Mapped[Decimal] = mapped_column(
        Numeric(15, 2),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # -----------------------------------------------------------------------
    # Relationships
    # -----------------------------------------------------------------------

    user: Mapped["User"] = relationship(  # type: ignore[name-defined]  # noqa: F821
        "User",
        foreign_keys=[user_id],
        lazy="select",
    )

    def __repr__(self) -> str:
        return (
            f"<LedgerEntry id={self.id} type={self.entry_type} "
            f"direction={self.direction} amount={self.amount} "
            f"balance_field={self.balance_field}>"
        )
