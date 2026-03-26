"""Shared pytest fixtures for the Buddy Bet test suite.

Integration test infrastructure
--------------------------------
- Schema is created once per process via _init_db_once() (idempotent).
- Each test gets a transaction-isolated AsyncSession:
    join_transaction_mode="create_savepoint" means service-layer commit()
    calls only release savepoints; the outer connection transaction is rolled
    back at the end of every test, restoring the DB to its pre-test state.
- The FastAPI get_db dependency is overridden to yield the test session so
    all HTTP requests in a test share the same isolated transaction.

Requirements
------------
- A running PostgreSQL instance accessible at TEST_DATABASE_URL.
- Default: postgresql+asyncpg://buddy_bet_app:change_me@localhost:5432/buddy_bet_test
- Override with the TEST_DATABASE_URL environment variable.
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import AsyncGenerator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

# ---------------------------------------------------------------------------
# Test database URL
# ---------------------------------------------------------------------------

TEST_DB_URL: str = os.getenv(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://buddy_bet_app:change_me@localhost:5432/buddy_bet_test",
)

# ---------------------------------------------------------------------------
# PostgreSQL enum definitions — must match app/models/enums.py exactly
# ---------------------------------------------------------------------------

_PG_ENUMS: list[tuple[str, tuple[str, ...]]] = [
    ("user_status", ("active", "suspended", "banned")),
    ("user_role", ("user", "admin")),
    ("football_outcome", ("home_win", "away_win", "draw")),
    (
        "match_status",
        ("scheduled", "live", "completed", "postponed", "cancelled", "abandoned"),
    ),
    (
        "bet_status",
        (
            "OPEN",
            "MATCHED",
            "PENDING_SETTLEMENT",
            "SETTLED",
            "CANCELLED",
            "VOIDED",
            "UNDER_REVIEW",
        ),
    ),
    ("settlement_outcome", ("creator_wins", "opponent_wins", "no_winner", "voided")),
    (
        "ledger_entry_type",
        (
            "STAKE_LOCK",
            "STAKE_UNLOCK",
            "VOID_REFUND",
            "SETTLEMENT_DEDUCT",
            "PAYOUT_CREDIT",
            "REFUND_CREDIT",
            "FEE_DEDUCT",
            "DEPOSIT",
            "WITHDRAWAL",
        ),
    ),
    ("balance_field", ("available", "locked")),
    ("ledger_direction", ("credit", "debit")),
    (
        "ledger_reference_type",
        ("bet", "settlement", "void", "cancellation", "deposit", "withdrawal"),
    ),
    ("platform_entry_type", ("FEE_COLLECTION", "FEE_COLLECTION_NO_WINNER")),
    ("settlement_path_type", ("winner", "no_winner")),
    ("fee_type", ("WINNER_FEE", "NO_WINNER_FEE")),
    (
        "bet_event_type",
        (
            "CREATED",
            "MATCHED",
            "PENDING_SETTLEMENT",
            "SETTLED",
            "CANCELLED",
            "VOIDED",
            "UNDER_REVIEW",
            "ADMIN_OVERRIDE",
        ),
    ),
]

# Track whether the schema has been created for this process
_SCHEMA_INITIALIZED: bool = False

# Track if the DB is reachable (set to None = not yet checked)
_DB_AVAILABLE: bool | None = None


async def _check_db_reachable() -> bool:
    """Return True if the test DB is reachable; False otherwise."""
    global _DB_AVAILABLE
    if _DB_AVAILABLE is not None:
        return _DB_AVAILABLE
    try:
        engine = create_async_engine(TEST_DB_URL, echo=False)
        async with engine.connect():
            pass
        await engine.dispose()
        _DB_AVAILABLE = True
    except Exception:
        _DB_AVAILABLE = False
    return _DB_AVAILABLE


async def _init_db_once() -> None:
    """Create enum types, tables, and seed static data (idempotent, once per process).

    Uses IF NOT EXISTS / WHERE NOT EXISTS guards so it is safe to call on an
    already-initialised database.
    """
    global _SCHEMA_INITIALIZED
    if _SCHEMA_INITIALIZED:
        return

    engine = create_async_engine(TEST_DB_URL, echo=False)
    try:
        # --- Schema -----------------------------------------------------------
        async with engine.begin() as conn:
            for enum_name, values in _PG_ENUMS:
                vals = ", ".join(f"'{v}'" for v in values)
                await conn.execute(
                    text(
                        f"DO $$ BEGIN "
                        f"IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = '{enum_name}') THEN "
                        f"  CREATE TYPE {enum_name} AS ENUM ({vals}); "
                        f"END IF; "
                        f"END $$;"
                    )
                )

            import app.models  # noqa: F401 — registers all ORM models on Base.metadata

            from app.db.base import Base

            await conn.run_sync(Base.metadata.create_all)

        # --- Incremental schema migrations (idempotent ADD COLUMN IF NOT EXISTS) ---
        async with engine.begin() as conn:
            # Sprint 2: provider ingestion columns
            await conn.execute(
                text(
                    "ALTER TABLE matches "
                    "ADD COLUMN IF NOT EXISTS provider_name VARCHAR(50);"
                )
            )
            await conn.execute(
                text(
                    "ALTER TABLE matches "
                    "ADD COLUMN IF NOT EXISTS last_synced_at TIMESTAMPTZ;"
                )
            )
            await conn.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_matches_provider_name "
                    "ON matches (provider_name);"
                )
            )

        # --- Seed static data -------------------------------------------------
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO platform_accounts "
                    "  (id, account_code, name, currency, balance, version) "
                    "VALUES "
                    "  (gen_random_uuid(), 'PLATFORM_FEES_ZAR', 'Platform Fees ZAR', 'ZAR', 0.00, 0) "
                    "ON CONFLICT (account_code) DO NOTHING"
                )
            )
            await conn.execute(
                text(
                    "INSERT INTO fee_config (id, fee_type, currency, rate, effective_from) "
                    "SELECT gen_random_uuid(), 'WINNER_FEE', 'ZAR', 0.1000, "
                    "       '2024-01-01 00:00:00+00' "
                    "WHERE NOT EXISTS ("
                    "  SELECT 1 FROM fee_config WHERE fee_type = 'WINNER_FEE' AND currency = 'ZAR'"
                    ")"
                )
            )
            await conn.execute(
                text(
                    "INSERT INTO fee_config (id, fee_type, currency, rate, effective_from) "
                    "SELECT gen_random_uuid(), 'NO_WINNER_FEE', 'ZAR', 0.0500, "
                    "       '2024-01-01 00:00:00+00' "
                    "WHERE NOT EXISTS ("
                    "  SELECT 1 FROM fee_config WHERE fee_type = 'NO_WINNER_FEE' AND currency = 'ZAR'"
                    ")"
                )
            )

        _SCHEMA_INITIALIZED = True
    finally:
        await engine.dispose()


# ---------------------------------------------------------------------------
# Core fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    """Per-test async session with savepoint-based rollback isolation.

    join_transaction_mode="create_savepoint":
      - service.commit() only releases a SAVEPOINT (not the outer transaction)
      - conn.rollback() at teardown undoes everything the test wrote

    The fixture skips gracefully when the test DB is not reachable.
    Set TEST_DATABASE_URL to point at your test PostgreSQL instance.
    Run scripts/setup_test_db_simple.sql as the postgres superuser to create
    the role and DB, then set the correct password in TEST_DATABASE_URL.
    """
    if not await _check_db_reachable():
        pytest.skip(
            f"Test database not reachable at {TEST_DB_URL!r}. "
            "Run scripts/setup_test_db_simple.sql and set TEST_DATABASE_URL."
        )
    await _init_db_once()

    engine = create_async_engine(TEST_DB_URL, echo=False)
    try:
        async with engine.connect() as conn:
            await conn.begin()
            session = AsyncSession(
                bind=conn,
                join_transaction_mode="create_savepoint",
                expire_on_commit=False,
                autoflush=False,
                autocommit=False,
            )
            try:
                yield session
            finally:
                await session.close()
                await conn.rollback()
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def client(db_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    """AsyncClient bound to the FastAPI app with the test session injected."""
    from app.core.dependencies import get_db
    from app.main import app

    async def _override_get_db() -> AsyncGenerator[AsyncSession, None]:
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as c:
            yield c
    finally:
        app.dependency_overrides.pop(get_db, None)


# ---------------------------------------------------------------------------
# Helper functions — shared by multiple test modules
# ---------------------------------------------------------------------------


async def register_user(
    client: AsyncClient,
    *,
    email: str = "user@example.com",
    password: str = "testpass123",
    display_name: str = "Test User",
) -> tuple[str, str]:
    """POST /api/v1/auth/register and return (user_id, access_token).

    user_id is extracted from the JWT 'sub' claim since the register
    endpoint returns only TokenResponse (no user_id field).
    """
    resp = await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": password, "display_name": display_name},
    )
    assert resp.status_code == 201, f"register failed: {resp.text}"
    data = resp.json()
    token = data["access_token"]
    # Decode JWT to extract user_id from 'sub' claim
    from app.core.security import decode_access_token, extract_user_id

    payload = decode_access_token(token)
    user_id = str(extract_user_id(payload))
    return user_id, token


async def fund_wallet(
    session: AsyncSession,
    user_id: str,
    amount: Decimal,
) -> None:
    """Directly set a user's available_balance (bypasses service/ledger layer).

    Use this to seed funds for bet tests without going through the deposit flow.
    """
    from app.models.wallet import Wallet

    result = await session.execute(
        select(Wallet).where(Wallet.user_id == uuid.UUID(user_id))
    )
    wallet = result.scalar_one()
    wallet.available_balance = amount
    session.add(wallet)
    await session.flush()


async def create_match(
    session: AsyncSession,
    *,
    kickoff_hours_from_now: int = 2,
    external_id: str | None = None,
) -> str:
    """Insert a scheduled match and return its UUID string."""
    from app.models.enums import MatchStatus
    from app.models.match import Match

    match = Match(
        external_id=external_id or str(uuid.uuid4()),
        home_team="Arsenal",
        away_team="Chelsea",
        competition="Premier League",
        kickoff_at=datetime.now(tz=timezone.utc)
        + timedelta(hours=kickoff_hours_from_now),
        status=MatchStatus.scheduled,
    )
    session.add(match)
    await session.flush()
    await session.refresh(match)
    return str(match.id)


async def make_admin(session: AsyncSession, user_id: str) -> None:
    """Promote a user to admin role directly in the DB."""
    from app.models.enums import UserRole
    from app.models.user import User

    result = await session.execute(
        select(User).where(User.id == uuid.UUID(user_id))
    )
    user = result.scalar_one()
    user.role = UserRole.admin
    session.add(user)
    await session.flush()
