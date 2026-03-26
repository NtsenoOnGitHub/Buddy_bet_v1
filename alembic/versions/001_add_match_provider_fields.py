"""Add provider_name and last_synced_at to matches table.

Revision ID: 001
Revises:     (initial schema — no prior migration)
Create Date: 2026-03-26

Changes
-------
matches.provider_name   VARCHAR(50)  NULL  — name of the provider that ingested
                                            this fixture (e.g. "api_football").
                                            NULL for manually-created/seeded rows.
matches.last_synced_at  TIMESTAMPTZ  NULL  — timestamp of the most recent
                                            successful provider sync.
                                            NULL for rows never synced.

An index is added on provider_name to support efficient "list all matches from
provider X" queries by the sync service.

Rollback
--------
Both columns are nullable with no server default, so downgrade simply drops them.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# ---------------------------------------------------------------------------
# Alembic revision identifiers
# ---------------------------------------------------------------------------
revision: str = "001"
down_revision = None  # First migration — no prior revision
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "matches",
        sa.Column("provider_name", sa.String(50), nullable=True),
    )
    op.add_column(
        "matches",
        sa.Column(
            "last_synced_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_matches_provider_name",
        "matches",
        ["provider_name"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_matches_provider_name", table_name="matches")
    op.drop_column("matches", "last_synced_at")
    op.drop_column("matches", "provider_name")
