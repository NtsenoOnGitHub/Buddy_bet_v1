"""SQLAlchemy ORM model for the 'bets' table.

The Bet model tracks the full lifecycle from OPEN through SETTLED or VOIDED.
Settlement columns (winner_id, platform_fee, payout_amount, applied_*_fee_rate)
are NULL until the bet is settled.

All monetary columns use Numeric(15, 2). Never float.
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
from app.models.enums import (
    BetStatus,
    FootballOutcome,
    SettlementOutcome,
)


class Bet(Base):
    """Core betting record. One row per bet from creation through resolution."""

    __tablename__ = "bets"

    id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=func.gen_random_uuid(),
    )
    match_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("matches.id"),
        nullable=False,
    )
    creator_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=False,
        index=True,
    )
    opponent_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=True,
        index=True,
    )
    creator_prediction: Mapped[FootballOutcome] = mapped_column(
        SAEnum(FootballOutcome, name="football_outcome", create_type=False, native_enum=True),
        nullable=False,
    )
    opponent_prediction: Mapped[Optional[FootballOutcome]] = mapped_column(
        SAEnum(FootballOutcome, name="football_outcome", create_type=False, native_enum=True),
        nullable=True,
    )
    stake_amount: Mapped[Decimal] = mapped_column(
        Numeric(15, 2),
        nullable=False,
    )
    currency: Mapped[str] = mapped_column(
        String(3),
        nullable=False,
        default="ZAR",
        server_default="ZAR",
    )
    status: Mapped[BetStatus] = mapped_column(
        SAEnum(BetStatus, name="bet_status", create_type=False, native_enum=True),
        nullable=False,
        default=BetStatus.OPEN,
        server_default="OPEN",
        index=True,
    )
    settlement_outcome: Mapped[Optional[SettlementOutcome]] = mapped_column(
        SAEnum(
            SettlementOutcome,
            name="settlement_outcome",
            create_type=False,
            native_enum=True,
        ),
        nullable=True,
    )
    winner_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=True,
    )
    platform_fee: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(15, 2),
        nullable=True,
    )
    payout_amount: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(15, 2),
        nullable=True,
    )
    applied_winner_fee_rate: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(5, 4),
        nullable=True,
    )
    applied_no_winner_fee_rate: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(5, 4),
        nullable=True,
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    settled_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    # -----------------------------------------------------------------------
    # Relationships
    # -----------------------------------------------------------------------

    match: Mapped["Match"] = relationship(  # type: ignore[name-defined]  # noqa: F821
        "Match",
        back_populates="bets",
        lazy="select",
    )
    creator: Mapped["User"] = relationship(  # type: ignore[name-defined]  # noqa: F821
        "User",
        foreign_keys=[creator_id],
        lazy="select",
    )
    opponent: Mapped[Optional["User"]] = relationship(  # type: ignore[name-defined]  # noqa: F821
        "User",
        foreign_keys=[opponent_id],
        lazy="select",
    )
    winner: Mapped[Optional["User"]] = relationship(  # type: ignore[name-defined]  # noqa: F821
        "User",
        foreign_keys=[winner_id],
        lazy="select",
    )
    events: Mapped[list["BetEvent"]] = relationship(  # type: ignore[name-defined]  # noqa: F821
        "BetEvent",
        back_populates="bet",
        lazy="select",
        order_by="BetEvent.created_at",
    )

    def __repr__(self) -> str:
        return (
            f"<Bet id={self.id} status={self.status} "
            f"stake={self.stake_amount} creator={self.creator_id}>"
        )
