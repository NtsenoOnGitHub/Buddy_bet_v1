"""Add deposit and withdrawal request tables.

Revision ID: 002
Revises:     001
Create Date: 2026-03-26

Changes
-------
1. Extend ledger_entry_type enum with two new values:
     WITHDRAWAL_HOLD    — available → locked when withdrawal is requested
     WITHDRAWAL_RELEASE — locked → available on rejection / failure

2. Create enum deposit_status:
     pending, processing, completed, failed, cancelled

3. Create enum withdrawal_status:
     pending, approved, processing, completed, failed, rejected

4. Create table deposit_requests
     id, user_id, wallet_id, amount, currency, status,
     payment_provider, provider_reference (unique), client_reference (unique),
     notes, requested_at, completed_at, failed_at

5. Create table withdrawal_requests
     id, user_id, wallet_id, amount, currency, status,
     destination_account, destination_type, provider_reference (unique),
     rejection_reason, requested_at, approved_at, completed_at, failed_at

Rollback
--------
Downgrade drops both tables and their enum types.
Removing values from an existing PostgreSQL enum is not supported without
a full type recreation — the WITHDRAWAL_HOLD / WITHDRAWAL_RELEASE values
are left in place on downgrade (they are harmless when unused).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "002"
down_revision = "001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # 1. Extend ledger_entry_type with withdrawal lifecycle values.
    #    PostgreSQL 12+ allows ADD VALUE inside a transaction as long as
    #    the type is not otherwise modified in the same transaction.
    # ------------------------------------------------------------------
    op.execute(
        sa.text(
            "ALTER TYPE ledger_entry_type "
            "ADD VALUE IF NOT EXISTS 'WITHDRAWAL_HOLD'"
        )
    )
    op.execute(
        sa.text(
            "ALTER TYPE ledger_entry_type "
            "ADD VALUE IF NOT EXISTS 'WITHDRAWAL_RELEASE'"
        )
    )

    # ------------------------------------------------------------------
    # 2. Create deposit_status enum
    # ------------------------------------------------------------------
    op.execute(
        sa.text(
            "DO $$ BEGIN "
            "  IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'deposit_status') THEN "
            "    CREATE TYPE deposit_status AS ENUM "
            "      ('pending', 'processing', 'completed', 'failed', 'cancelled'); "
            "  END IF; "
            "END $$;"
        )
    )

    # ------------------------------------------------------------------
    # 3. Create withdrawal_status enum
    # ------------------------------------------------------------------
    op.execute(
        sa.text(
            "DO $$ BEGIN "
            "  IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'withdrawal_status') THEN "
            "    CREATE TYPE withdrawal_status AS ENUM "
            "      ('pending', 'approved', 'processing', 'completed', 'failed', 'rejected'); "
            "  END IF; "
            "END $$;"
        )
    )

    # ------------------------------------------------------------------
    # 4. Create deposit_requests table
    # ------------------------------------------------------------------
    op.create_table(
        "deposit_requests",
        sa.Column(
            "id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            primary_key=True,
        ),
        sa.Column(
            "user_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "wallet_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("wallets.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("amount", sa.Numeric(15, 2), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False, server_default="ZAR"),
        sa.Column(
            "status",
            sa.Enum(
                "pending",
                "processing",
                "completed",
                "failed",
                "cancelled",
                name="deposit_status",
                create_type=False,
            ),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("payment_provider", sa.String(50), nullable=True),
        sa.Column("provider_reference", sa.String(200), nullable=True),
        sa.Column("client_reference", sa.String(200), nullable=True),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column(
            "requested_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_deposit_requests_user_id", "deposit_requests", ["user_id"])
    op.create_index("ix_deposit_requests_wallet_id", "deposit_requests", ["wallet_id"])
    op.create_index("ix_deposit_requests_status", "deposit_requests", ["status"])
    op.create_index(
        "ix_deposit_requests_user_status",
        "deposit_requests",
        ["user_id", "status"],
    )
    op.create_index(
        "ix_deposit_requests_requested_at",
        "deposit_requests",
        ["requested_at"],
    )
    op.create_unique_constraint(
        "uq_deposit_requests_provider_reference",
        "deposit_requests",
        ["provider_reference"],
    )
    op.create_unique_constraint(
        "uq_deposit_requests_client_reference",
        "deposit_requests",
        ["client_reference"],
    )

    # ------------------------------------------------------------------
    # 5. Create withdrawal_requests table
    # ------------------------------------------------------------------
    op.create_table(
        "withdrawal_requests",
        sa.Column(
            "id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            primary_key=True,
        ),
        sa.Column(
            "user_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "wallet_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("wallets.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("amount", sa.Numeric(15, 2), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False, server_default="ZAR"),
        sa.Column(
            "status",
            sa.Enum(
                "pending",
                "approved",
                "processing",
                "completed",
                "failed",
                "rejected",
                name="withdrawal_status",
                create_type=False,
            ),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("destination_account", sa.String(200), nullable=True),
        sa.Column("destination_type", sa.String(50), nullable=True),
        sa.Column("provider_reference", sa.String(200), nullable=True),
        sa.Column("rejection_reason", sa.Text, nullable=True),
        sa.Column(
            "requested_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_withdrawal_requests_user_id", "withdrawal_requests", ["user_id"]
    )
    op.create_index(
        "ix_withdrawal_requests_wallet_id", "withdrawal_requests", ["wallet_id"]
    )
    op.create_index(
        "ix_withdrawal_requests_status", "withdrawal_requests", ["status"]
    )
    op.create_index(
        "ix_withdrawal_requests_user_status",
        "withdrawal_requests",
        ["user_id", "status"],
    )
    op.create_index(
        "ix_withdrawal_requests_requested_at",
        "withdrawal_requests",
        ["requested_at"],
    )
    op.create_unique_constraint(
        "uq_withdrawal_requests_provider_reference",
        "withdrawal_requests",
        ["provider_reference"],
    )


def downgrade() -> None:
    op.drop_table("withdrawal_requests")
    op.drop_table("deposit_requests")
    op.execute(sa.text("DROP TYPE IF EXISTS withdrawal_status"))
    op.execute(sa.text("DROP TYPE IF EXISTS deposit_status"))
    # Note: WITHDRAWAL_HOLD and WITHDRAWAL_RELEASE values are left in
    # ledger_entry_type — PostgreSQL does not support removing enum values.
