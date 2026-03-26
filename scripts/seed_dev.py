#!/usr/bin/env python3
"""CLI script to seed development data (test user + sample matches).

Usage (from the project root):
    python scripts/seed_dev.py

The script is fully idempotent: safe to run multiple times.  Existing records
are detected and skipped; nothing is overwritten.

What gets seeded
----------------
Test user:
    email:    testuser@buddybet.com
    password: TestPass123!
    balance:  10 000.00 ZAR (available)

Sample matches (status=scheduled, always future dates):
    Arsenal vs Manchester City       — Premier League  (+7 days)
    Liverpool vs Chelsea             — Premier League  (+10 days)
    Barcelona vs Real Madrid         — La Liga         (+14 days)
    Bayern Munich vs Borussia Dortmund — Bundesliga    (+18 days)
    Paris Saint-Germain vs Marseille — Ligue 1         (+21 days)
"""

from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Ensure the project root is on sys.path so that `app.*` imports resolve
# when this script is executed directly (e.g. `python scripts/seed_dev.py`).
# ---------------------------------------------------------------------------
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db.seed import TEST_EMAIL, TEST_PASSWORD, seed_matches, seed_test_user  # noqa: E402
from app.db.session import AsyncSessionFactory  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
logger = logging.getLogger(__name__)


async def main() -> None:
    async with AsyncSessionFactory() as db:
        try:
            await seed_test_user(db)
            await seed_matches(db)
            await db.commit()
        except Exception:
            await db.rollback()
            logger.exception("Seed failed — transaction rolled back")
            sys.exit(1)

    logger.info("─" * 50)
    logger.info("Seed complete.")
    logger.info("Login: email=%s  password=%s", TEST_EMAIL, TEST_PASSWORD)


if __name__ == "__main__":
    asyncio.run(main())
