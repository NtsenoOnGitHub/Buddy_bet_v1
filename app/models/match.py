"""SQLAlchemy ORM model for the 'matches' table.

Matches are a local mirror of fixture data ingested from an external provider.
The outcome column drives settlement — it must be consistent with the scores.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Enum as SAEnum, Integer, String, func
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.enums import FootballOutcome, MatchStatus


class Match(Base):
    """Local mirror of football fixtures. outcome drives settlement."""

    __tablename__ = "matches"

    id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=func.gen_random_uuid(),
    )
    external_id: Mapped[str] = mapped_column(
        String(200),
        nullable=False,
        unique=True,
    )
    home_team: Mapped[str] = mapped_column(String(200), nullable=False)
    away_team: Mapped[str] = mapped_column(String(200), nullable=False)
    competition: Mapped[str] = mapped_column(String(200), nullable=False)
    kickoff_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        index=True,
    )
    status: Mapped[MatchStatus] = mapped_column(
        SAEnum(MatchStatus, name="match_status", create_type=False, native_enum=True),
        nullable=False,
        default=MatchStatus.scheduled,
        server_default="scheduled",
        index=True,
    )
    result_home_score: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    result_away_score: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    outcome: Mapped[Optional[FootballOutcome]] = mapped_column(
        SAEnum(FootballOutcome, name="football_outcome", create_type=False, native_enum=True),
        nullable=True,
    )
    result_confirmed_at: Mapped[Optional[datetime]] = mapped_column(
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

    bets: Mapped[list["Bet"]] = relationship(  # type: ignore[name-defined]  # noqa: F821
        "Bet",
        back_populates="match",
        lazy="select",
    )

    def __repr__(self) -> str:
        return (
            f"<Match id={self.id} "
            f"{self.home_team!r} vs {self.away_team!r} "
            f"kickoff={self.kickoff_at} status={self.status}>"
        )
