"""SQLAlchemy ORM model for the 'bet_events' table.

BetEvent is an immutable, append-only audit trail. One row per state transition
or admin/system action affecting a bet. fn_prevent_mutation() blocks UPDATE/DELETE.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import DateTime, Enum as SAEnum, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.enums import BetEventType


class BetEvent(Base):
    """Immutable audit trail row for every bet state transition."""

    __tablename__ = "bet_events"

    id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=func.gen_random_uuid(),
    )
    bet_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("bets.id"),
        nullable=False,
        index=True,
    )
    event_type: Mapped[BetEventType] = mapped_column(
        SAEnum(BetEventType, name="bet_event_type", create_type=False, native_enum=True),
        nullable=False,
    )
    actor_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=True,
    )
    # Human-readable actor descriptor. Always set.
    # e.g. 'USER', 'ADMIN', 'SETTLEMENT_ENGINE', 'EXPIRY_JOB', 'SYSTEM'
    actor_label: Mapped[str] = mapped_column(String(100), nullable=False)
    payload: Mapped[Optional[Any]] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        index=True,
    )

    # -----------------------------------------------------------------------
    # Relationships
    # -----------------------------------------------------------------------

    bet: Mapped["Bet"] = relationship(  # type: ignore[name-defined]  # noqa: F821
        "Bet",
        back_populates="events",
        lazy="select",
    )
    actor: Mapped[Optional["User"]] = relationship(  # type: ignore[name-defined]  # noqa: F821
        "User",
        foreign_keys=[actor_id],
        lazy="select",
    )

    def __repr__(self) -> str:
        return (
            f"<BetEvent id={self.id} bet_id={self.bet_id} "
            f"type={self.event_type} actor={self.actor_label!r}>"
        )
