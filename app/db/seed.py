"""Database seed helpers for local development.

This module provides idempotent seed functions used by:
  - scripts/seed_dev.py  (manual CLI invocation)
  - app/main.py lifespan (automatic on startup when SEED_TEST_USER=true)

None of these functions should ever run in production — the caller is
responsible for checking app_env / SEED_TEST_USER before calling.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import NamedTuple

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.security import hash_password
from app.models.enums import MatchStatus
from app.models.match import Match
from app.repositories.match_repository import MatchRepository
from app.repositories.user_repository import UserRepository
from app.repositories.wallet_repository import WalletRepository

logger = logging.getLogger(__name__)
settings = get_settings()


# ---------------------------------------------------------------------------
# Test-user constants
# ---------------------------------------------------------------------------

TEST_EMAIL = "testuser@buddybet.com"
TEST_DISPLAY_NAME = "testuser"
TEST_PASSWORD = "TestPass123!"
TEST_INITIAL_BALANCE = Decimal("10000.00")


# ---------------------------------------------------------------------------
# Seed-match fixture definitions
# ---------------------------------------------------------------------------

class _MatchFixture(NamedTuple):
    """One seed-match definition."""
    external_id: str   # Stable DEV-prefixed key — used as the dedup handle
    home_team: str
    away_team: str
    competition: str
    days_from_now: int  # kickoff_at = now + this many days (always future)


_SEED_MATCHES: list[_MatchFixture] = [
    _MatchFixture(
        external_id="DEV-arsenal-vs-manchester-city",
        home_team="Arsenal",
        away_team="Manchester City",
        competition="Premier League",
        days_from_now=7,
    ),
    _MatchFixture(
        external_id="DEV-liverpool-vs-chelsea",
        home_team="Liverpool",
        away_team="Chelsea",
        competition="Premier League",
        days_from_now=10,
    ),
    _MatchFixture(
        external_id="DEV-barcelona-vs-real-madrid",
        home_team="Barcelona",
        away_team="Real Madrid",
        competition="La Liga",
        days_from_now=14,
    ),
    _MatchFixture(
        external_id="DEV-bayern-munich-vs-borussia-dortmund",
        home_team="Bayern Munich",
        away_team="Borussia Dortmund",
        competition="Bundesliga",
        days_from_now=18,
    ),
    _MatchFixture(
        external_id="DEV-psg-vs-marseille",
        home_team="Paris Saint-Germain",
        away_team="Marseille",
        competition="Ligue 1",
        days_from_now=21,
    ),
]


# ---------------------------------------------------------------------------
# Seed functions
# ---------------------------------------------------------------------------

async def seed_test_user(db: AsyncSession) -> None:
    """Create a funded test user.  Idempotent — safe to call multiple times.

    If the user already exists the function logs its current balance and
    returns immediately without touching the database.

    Args:
        db: An open AsyncSession.  The caller is responsible for committing
            or rolling back the outer transaction.
    """
    user_repo = UserRepository(db)
    wallet_repo = WalletRepository(db)

    # Guard: skip if user already exists
    existing = await user_repo.get_by_email(TEST_EMAIL)
    if existing is not None:
        wallet = await wallet_repo.get_by_user_id(existing.id)
        logger.info(
            "seed_test_user: user already exists — id=%s available_balance=%s ZAR",
            existing.id,
            wallet.available_balance if wallet else "no wallet",
        )
        return

    # Create user (password is bcrypt-hashed — plain text is never stored)
    user = await user_repo.create(
        email=TEST_EMAIL,
        display_name=TEST_DISPLAY_NAME,
        password_hash=hash_password(TEST_PASSWORD),
    )

    # Create wallet with initial balance.
    # We pass available_balance directly to BaseRepository.create so that
    # the row is inserted already funded.  This is intentional for seeding;
    # live deposits go through WalletService + ledger entries instead.
    await wallet_repo.create(
        user_id=user.id,
        currency=settings.platform_currency,
        available_balance=TEST_INITIAL_BALANCE,
    )

    logger.info(
        "seed_test_user: created — id=%s email=%s balance=%s %s",
        user.id,
        user.email,
        TEST_INITIAL_BALANCE,
        settings.platform_currency,
    )


async def seed_matches(db: AsyncSession) -> None:
    """Insert sample upcoming football matches for development testing.

    Idempotent — each match is keyed by its external_id.  If a match with
    that external_id already exists it is skipped; no duplicate is created.

    Kickoff times are computed as (now + N days) at runtime so the matches
    are always in the future regardless of when the script is run.

    All matches are inserted with status=scheduled, which is the only status
    that allows bet creation (see MatchRepository.get_available).

    Args:
        db: An open AsyncSession.  The caller is responsible for committing
            or rolling back the outer transaction.
    """
    match_repo = MatchRepository(db)
    now = datetime.now(tz=timezone.utc)
    created = 0
    skipped = 0

    for fixture in _SEED_MATCHES:
        # Dedup check: query by external_id (the DB unique constraint)
        result = await db.execute(
            select(Match).where(Match.external_id == fixture.external_id)
        )
        if result.scalar_one_or_none() is not None:
            logger.debug("seed_matches: skipping %s (already exists)", fixture.external_id)
            skipped += 1
            continue

        kickoff_at = now + timedelta(days=fixture.days_from_now)

        await match_repo.create(
            external_id=fixture.external_id,
            home_team=fixture.home_team,
            away_team=fixture.away_team,
            competition=fixture.competition,
            kickoff_at=kickoff_at,
            status=MatchStatus.scheduled,
        )

        logger.info(
            "seed_matches: created — %s vs %s (%s) kickoff=%s",
            fixture.home_team,
            fixture.away_team,
            fixture.competition,
            kickoff_at.strftime("%Y-%m-%d %H:%M UTC"),
        )
        created += 1

    logger.info(
        "seed_matches: done — %d created, %d already existed", created, skipped
    )
