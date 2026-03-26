"""Add checkout_url column to deposit_requests.

Revision ID: 003
Revises:     002
Create Date: 2026-03-26

Changes
-------
1. ALTER TABLE deposit_requests ADD COLUMN checkout_url TEXT;

Stores the PayFast hosted checkout URL on the DepositRequest row so the
frontend can retrieve it after creation without the backend having to
regenerate the signed URL.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "003"
down_revision = "002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "deposit_requests",
        sa.Column("checkout_url", sa.Text, nullable=True),
    )


def downgrade() -> None:
    op.drop_column("deposit_requests", "checkout_url")
