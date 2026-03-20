"""Async SQLAlchemy engine and session factory.

The engine is created once at import time using settings from app.core.config.
All database access in the application must go through AsyncSessionFactory.
"""

from __future__ import annotations

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

engine: AsyncEngine = create_async_engine(
    settings.database_url_async,
    echo=settings.app_debug,          # Log SQL statements in debug mode
    pool_size=settings.db_pool_size,
    max_overflow=settings.db_max_overflow,
    pool_timeout=settings.db_pool_timeout,
    pool_recycle=settings.db_pool_recycle,
    pool_pre_ping=True,               # Validate connections before use
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
