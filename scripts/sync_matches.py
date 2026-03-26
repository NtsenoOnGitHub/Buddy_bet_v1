"""CLI script — manually trigger match sync from the provider.

Usage::

    # Sync upcoming fixtures (default: 7 days ahead)
    python scripts/sync_matches.py upcoming

    # Sync recent results (default: 2 days back)
    python scripts/sync_matches.py results

    # Sync live fixtures
    python scripts/sync_matches.py live

    # All three in sequence
    python scripts/sync_matches.py all

    # Override defaults
    python scripts/sync_matches.py upcoming --days 14
    python scripts/sync_matches.py results --days 3

Prerequisites
-------------
1. Set SPORTS_PROVIDER_ENABLED=true in your .env
2. Set SPORTS_PROVIDER_API_KEY=<your-key> in your .env
3. Ensure the database is running and reachable

The script uses the same session factory as the application and follows
the same transaction model (commit on success, rollback on error).
"""

from __future__ import annotations

import argparse
import asyncio
import sys

# ---------------------------------------------------------------------------
# Bootstrap path so ``app.*`` imports resolve without installing the package
# ---------------------------------------------------------------------------
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


async def _run(mode: str, days: int | None) -> None:
    from app.core.config import get_settings
    from app.db.session import AsyncSessionFactory
    from app.integrations.providers.api_football import ApiFootballProvider
    from app.integrations.sync_service import MatchSyncService

    settings = get_settings()

    if not settings.sports_provider_enabled:
        print(
            "ERROR: SPORTS_PROVIDER_ENABLED is false.\n"
            "Set SPORTS_PROVIDER_ENABLED=true and SPORTS_PROVIDER_API_KEY "
            "in your .env to enable sync.",
            file=sys.stderr,
        )
        sys.exit(1)

    if not settings.sports_provider_api_key:
        print(
            "ERROR: SPORTS_PROVIDER_API_KEY is not set.", file=sys.stderr
        )
        sys.exit(1)

    async with AsyncSessionFactory() as session:
        try:
            async with ApiFootballProvider() as provider:
                svc = MatchSyncService(session, provider)

                if mode in ("upcoming", "all"):
                    d = days or settings.sports_provider_sync_days_ahead
                    result = await svc.sync_upcoming(days_ahead=d)
                    _print_result("upcoming", result)

                if mode in ("results", "all"):
                    d = days or settings.sports_provider_sync_days_back
                    result = await svc.sync_results(days_back=d)
                    _print_result("results", result)

                if mode in ("live", "all"):
                    result = await svc.sync_live()
                    _print_result("live", result)

            await session.commit()
        except Exception as exc:
            await session.rollback()
            print(f"ERROR: sync failed — {exc}", file=sys.stderr)
            sys.exit(1)


def _print_result(label: str, result: object) -> None:
    from app.integrations.sync_service import SyncResult

    assert isinstance(result, SyncResult)
    print(
        f"\n── Sync [{label}] ──────────────────────────────────────\n"
        f"  provider : {result.provider}\n"
        f"  run_at   : {result.run_at.isoformat()}\n"
        f"  fetched  : {result.fixtures_fetched}\n"
        f"  created  : {result.created}\n"
        f"  updated  : {result.updated}\n"
        f"  skipped  : {result.skipped}\n"
        f"  failed   : {result.failed}"
    )
    for err in result.errors:
        print(f"  ⚠  {err}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Buddy Bet — manual match sync CLI"
    )
    parser.add_argument(
        "mode",
        choices=["upcoming", "results", "live", "all"],
        help="Which sync operation to run.",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=None,
        metavar="N",
        help="Override day range (days_ahead for 'upcoming'; days_back for 'results').",
    )
    args = parser.parse_args()
    asyncio.run(_run(args.mode, args.days))


if __name__ == "__main__":
    main()
