"""SQLAlchemy ORM model for the 'processed_events' table.

ProcessedEvent is the idempotency / deduplication log for incoming external
events (e.g. match result webhooks). Before processing any external event the
application checks this table. If the (event_source, external_event_id) pair
is already present, the event is discarded. If absent, the row is inserted
within the same transaction that triggers settlement.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ProcessedEvent(Base):
    """Deduplication record for incoming external events."""

    __tablename__ = "processed_events"

    __table_args__ = (
        UniqueConstraint(
            "event_source",
            "external_event_id",
            name="uq_processed_events_source_event",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=func.gen_random_uuid(),
    )
    event_source: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )
    external_event_id: Mapped[str] = mapped_column(
        String(500),
        nullable=False,
    )
    processed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    def __repr__(self) -> str:
        return (
            f"<ProcessedEvent id={self.id} "
            f"source={self.event_source!r} "
            f"external_id={self.external_event_id!r}>"
        )
