"""Alembic environment — async SQLAlchemy with asyncpg.

This module is invoked by Alembic during `alembic upgrade`, `alembic revision
--autogenerate`, and related commands. It wires the async engine from the
application's settings to Alembic's migration runner.

All models are imported via app.models so that Alembic's autogenerate can
detect every table. Do NOT remove the model import even if it appears unused.
"""

from __future__ import annotations

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

# ---------------------------------------------------------------------------
# Import application metadata and all models so Alembic can detect changes.
# ---------------------------------------------------------------------------
from app.db.base import Base  # noqa: F401 — provides target_metadata
import app.models  # noqa: F401 — registers all ORM classes with Base.metadata

# ---------------------------------------------------------------------------
# Alembic Config object — gives access to values in alembic.ini.
# ---------------------------------------------------------------------------
config = context.config

# ---------------------------------------------------------------------------
# Set the database URL from application settings at runtime.
# This overrides the (empty) sqlalchemy.url in alembic.ini.
# ---------------------------------------------------------------------------
from app.core.config import get_settings  # noqa: E402

settings = get_settings()
# Use the async URL for the async runner; offline mode uses the sync URL.
config.set_main_option("sqlalchemy.url", settings.database_url_async)

# ---------------------------------------------------------------------------
# Interpret the config file for Python logging.
# ---------------------------------------------------------------------------
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# ---------------------------------------------------------------------------
# Target metadata — used by autogenerate.
# ---------------------------------------------------------------------------
target_metadata = Base.metadata


# ---------------------------------------------------------------------------
# Run migrations in OFFLINE mode (no live DB connection required).
# ---------------------------------------------------------------------------
def run_migrations_offline() -> None:
    """Run migrations without a live database connection.

    Useful for generating SQL scripts without executing them.
    Uses the sync URL (no asyncpg driver required for offline mode).
    """
    url = settings.database_url_sync
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
    )

    with context.begin_transaction():
        context.run_migrations()


# ---------------------------------------------------------------------------
# Run migrations in ONLINE mode (async engine).
# ---------------------------------------------------------------------------
def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Create an async engine and run migrations via a synchronous connection."""
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    """Run migrations in online mode using asyncio."""
    asyncio.run(run_async_migrations())


# ---------------------------------------------------------------------------
# Entry point — Alembic calls this module directly.
# ---------------------------------------------------------------------------
if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
