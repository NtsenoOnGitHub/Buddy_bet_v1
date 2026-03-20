"""SQLAlchemy ORM model for the 'fee_config' table.

Rows are versioned by effective_from and never deleted. The Settlement Engine
resolves the applicable rate by querying for the most recent row where
effective_from <= settled_at for a given (fee_type, currency) pair.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import DateTime, Enum as SAEnum, ForeignKey, Numeric, String, func
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.enums import FeeType


class FeeConfig(Base):
    """Versioned platform fee rate. Never updated or deleted."""

    __tablename__ = "fee_config"

    id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=func.gen_random_uuid(),
    )
    fee_type: Mapped[FeeType] = mapped_column(
        SAEnum(FeeType, name="fee_type", create_type=False, native_enum=True),
        nullable=False,
    )
    rate: Mapped[Decimal] = mapped_column(
        Numeric(5, 4),
        nullable=False,
    )
    currency: Mapped[str] = mapped_column(
        String(3),
        nullable=False,
    )
    effective_from: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    created_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    # -----------------------------------------------------------------------
    # Relationships
    # -----------------------------------------------------------------------

    creator: Mapped[Optional["User"]] = relationship(  # type: ignore[name-defined]  # noqa: F821
        "User",
        lazy="select",
        foreign_keys=[created_by],
    )

    def __repr__(self) -> str:
        return (
            f"<FeeConfig id={self.id} type={self.fee_type} "
            f"rate={self.rate} effective_from={self.effective_from}>"
        )
