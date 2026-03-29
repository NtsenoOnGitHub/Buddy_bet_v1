"""Async SQLAlchemy engine and session factory.

The engine is created once at import time using settings from app.core.config.
All database access in the application must go through AsyncSessionFactory.
"""

from __future__ import annotations

from sqlalchemy.pool import NullPool
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import get_settings

settings = get_settings()

# ---------------------------------------------------------------------------
# Async engine
# ---------------------------------------------------------------------------

# PgBouncer in transaction mode (Supabase pooler port 6543) closes the
# underlying connection after each transaction.  SQLAlchemy's internal pool
# tries to reuse those connections and gets ConnectionDoesNotExistError.
# Using NullPool disables SQLAlchemy-level pooling so every session acquires
# and releases a fresh connection — PgBouncer handles pooling instead.
_use_null_pool = settings.db_connect_args.get("statement_cache_size") == 0

if _use_null_pool:
    engine: AsyncEngine = create_async_engine(
        settings.database_url_async,
        echo=settings.app_debug,
        poolclass=NullPool,
        connect_args=settings.db_connect_args,
    )
else:
    engine = create_async_engine(
        settings.database_url_async,
        echo=settings.app_debug,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        pool_timeout=settings.db_pool_timeout,
        pool_recycle=settings.db_pool_recycle,
        pool_pre_ping=True,               # Validate connections before use
        connect_args=settings.db_connect_args,
    )

# ---------------------------------------------------------------------------
# Session factory
# ---------------------------------------------------------------------------

AsyncSessionFactory: async_sessionmaker[AsyncSession] = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,  # Keep object attributes accessible after commit
    autoflush=False,         # Explicit flush gives finer control in services
    autocommit=False,
)
