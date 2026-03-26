"""Match synchronisation service.

MatchSyncService ingests fixture data from a sports provider into the
internal matches table.  All app endpoints continue reading from the
internal table only — the sync layer is the only code that touches the
provider API.

Upsert semantics
----------------
For each :class:`~app.integrations.providers.base.ProviderMatchPayload`:

1. Look up the internal match by ``external_id``.
2. **Create** — if no match exists, insert a new row.
3. **Update** — if a match exists, apply changes to:
   - ``kickoff_at``       (rescheduled fixtures)
   - ``status``           (scheduled → live → completed / postponed / cancelled)
   - ``home_team``        (name corrections from provider)
   - ``away_team``        (name corrections from provider)
   - ``competition``      (name corrections from provider)
   - ``outcome``          (set when match finishes, only if not yet admin-confirmed)
   - ``result_home_score``
   - ``result_away_score``
4. **Skip** — if nothing meaningful changed (``last_synced_at`` is still updated).

Settlement safety
-----------------
Sync sets ``status``, ``outcome``, and scores when a provider marks a match
as finished.  It does **NOT** set ``result_confirmed_at``.  That field is
written exclusively by the admin ``confirm-result`` endpoint, which also
triggers settlement.  This keeps sync and money-movement fully decoupled.

Transaction ownership
---------------------
``MatchSyncService`` follows the same pattern as other application services:
``get_db`` (the FastAPI dependency) owns commit/rollback.  When called from
a CLI script or background job, the caller is responsible for the session
lifecycle.
"""

from __future__ import annotations

import dataclasses
import logging
from datetime import datetime, timezone
from typing import Literal, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.providers.base import BaseSportsProvider, ProviderMatchPayload
from app.models.enums import MatchStatus
from app.models.match import Match
from app.repositories.match_repository import MatchRepository

logger = logging.getLogger(__name__)

# Status transitions that the sync job is allowed to perform.
# Sync should never move a match backwards or out of a terminal state.
_ALLOWED_TRANSITIONS: dict[MatchStatus, set[MatchStatus]] = {
    MatchStatus.scheduled: {MatchStatus.live, MatchStatus.completed,
                             MatchStatus.postponed, MatchStatus.cancelled,
                             MatchStatus.abandoned},
    MatchStatus.live: {MatchStatus.completed, MatchStatus.postponed,
                       MatchStatus.cancelled, MatchStatus.abandoned},
    MatchStatus.postponed: {MatchStatus.scheduled},  # Rescheduled
    # Terminal states — sync never moves away from these
    MatchStatus.completed: set(),
    MatchStatus.cancelled: set(),
    MatchStatus.abandoned: set(),
}


@dataclasses.dataclass
class SyncResult:
    """Summary of a single sync run returned to the caller / logged."""

    provider: str
    run_at: datetime
    fixtures_fetched: int = 0
    created: int = 0
    updated: int = 0
    skipped: int = 0
    failed: int = 0
    errors: list[str] = dataclasses.field(default_factory=list)

    def log_summary(self) -> None:
        logger.info(
            "sync.complete provider=%s fetched=%d created=%d updated=%d "
            "skipped=%d failed=%d",
            self.provider,
            self.fixtures_fetched,
            self.created,
            self.updated,
            self.skipped,
            self.failed,
        )
        for err in self.errors:
            logger.warning("sync.error: %s", err)


class MatchSyncService:
    """Upserts provider fixture data into the internal matches table.

    Args:
        db:       An open async SQLAlchemy session.
        provider: A configured :class:`~app.integrations.providers.base.BaseSportsProvider`
                  instance.
    """

    def __init__(self, db: AsyncSession, provider: BaseSportsProvider) -> None:
        self._db = db
        self._provider = provider
        self._match_repo = MatchRepository(db)

    # ------------------------------------------------------------------
    # Public entry points
    # ------------------------------------------------------------------

    async def sync_upcoming(
        self,
        days_ahead: int = 7,
        league_ids: Optional[list[int]] = None,
    ) -> SyncResult:
        """Pull upcoming fixtures from the provider and upsert into the DB.

        Args:
            days_ahead:  How many days ahead to query.
            league_ids:  Specific league IDs; ``None`` uses provider defaults.

        Returns:
            :class:`SyncResult` summary.
        """
        result = SyncResult(
            provider=self._provider.provider_name,
            run_at=datetime.now(tz=timezone.utc),
        )

        logger.info(
            "sync.upcoming.start provider=%s days_ahead=%d",
            self._provider.provider_name,
            days_ahead,
        )

        try:
            payloads = await self._provider.fetch_upcoming_fixtures(
                days_ahead=days_ahead, league_ids=league_ids
            )
        except Exception as exc:
            msg = f"provider.fetch_upcoming failed: {exc}"
            logger.exception("sync.upcoming.fetch_error: %s", msg)
            result.errors.append(msg)
            result.log_summary()
            return result

        result.fixtures_fetched = len(payloads)
        await self._process_payloads(payloads, result)

        result.log_summary()
        return result

    async def sync_results(
        self,
        days_back: int = 2,
        league_ids: Optional[list[int]] = None,
    ) -> SyncResult:
        """Pull recently completed fixtures and update internal match records.

        This updates ``status``, ``outcome``, and scores for finished matches.
        It does **not** set ``result_confirmed_at`` — that is admin's job.

        Args:
            days_back:   How many days back to query.
            league_ids:  Specific league IDs; ``None`` uses provider defaults.

        Returns:
            :class:`SyncResult` summary.
        """
        result = SyncResult(
            provider=self._provider.provider_name,
            run_at=datetime.now(tz=timezone.utc),
        )

        logger.info(
            "sync.results.start provider=%s days_back=%d",
            self._provider.provider_name,
            days_back,
        )

        try:
            payloads = await self._provider.fetch_results(
                days_back=days_back, league_ids=league_ids
            )
        except Exception as exc:
            msg = f"provider.fetch_results failed: {exc}"
            logger.exception("sync.results.fetch_error: %s", msg)
            result.errors.append(msg)
            result.log_summary()
            return result

        result.fixtures_fetched = len(payloads)
        await self._process_payloads(payloads, result)

        result.log_summary()
        return result

    async def sync_live(
        self,
        league_ids: Optional[list[int]] = None,
    ) -> SyncResult:
        """Pull currently live fixtures and update their status to 'live'.

        Args:
            league_ids:  Specific league IDs; ``None`` uses provider defaults.

        Returns:
            :class:`SyncResult` summary.
        """
        result = SyncResult(
            provider=self._provider.provider_name,
            run_at=datetime.now(tz=timezone.utc),
        )

        logger.info(
            "sync.live.start provider=%s", self._provider.provider_name
        )

        try:
            payloads = await self._provider.fetch_live_fixtures(
                league_ids=league_ids
            )
        except Exception as exc:
            msg = f"provider.fetch_live failed: {exc}"
            logger.exception("sync.live.fetch_error: %s", msg)
            result.errors.append(msg)
            result.log_summary()
            return result

        result.fixtures_fetched = len(payloads)
        await self._process_payloads(payloads, result)

        result.log_summary()
        return result

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _process_payloads(
        self, payloads: list[ProviderMatchPayload], result: SyncResult
    ) -> None:
        """Upsert each payload and accumulate counts in *result*."""
        for payload in payloads:
            try:
                action = await self._upsert_fixture(payload)
                if action == "created":
                    result.created += 1
                elif action == "updated":
                    result.updated += 1
                else:
                    result.skipped += 1
            except Exception as exc:
                result.failed += 1
                msg = (
                    f"upsert failed for external_id={payload.external_id!r}: "
                    f"{type(exc).__name__}: {exc}"
                )
                result.errors.append(msg)
                logger.exception(
                    "sync.upsert_error external_id=%s", payload.external_id
                )

    async def _upsert_fixture(
        self, payload: ProviderMatchPayload
    ) -> Literal["created", "updated", "skipped"]:
        """Create or update a single internal match from a provider payload.

        Returns:
            ``"created"``  — new row inserted.
            ``"updated"``  — existing row had one or more fields changed.
            ``"skipped"``  — existing row; no meaningful changes detected.
        """
        now = datetime.now(tz=timezone.utc)
        existing = await self._match_repo.get_by_external_id(payload.external_id)

        if existing is None:
            return await self._create_fixture(payload, now)

        return await self._update_fixture(existing, payload, now)

    async def _create_fixture(
        self, payload: ProviderMatchPayload, now: datetime
    ) -> Literal["created"]:
        """Insert a new Match row from the provider payload."""
        match = Match(
            external_id=payload.external_id,
            provider_name=payload.provider_name,
            home_team=payload.home_team,
            away_team=payload.away_team,
            competition=payload.competition,
            kickoff_at=payload.kickoff_at,
            status=payload.internal_status,
            last_synced_at=now,
        )
        if payload.internal_outcome is not None:
            match.outcome = payload.internal_outcome
            match.result_home_score = payload.home_score
            match.result_away_score = payload.away_score

        self._db.add(match)
        await self._db.flush()

        logger.debug(
            "sync.created external_id=%s %s vs %s",
            payload.external_id,
            payload.home_team,
            payload.away_team,
        )
        return "created"

    async def _update_fixture(
        self,
        existing: Match,
        payload: ProviderMatchPayload,
        now: datetime,
    ) -> Literal["updated", "skipped"]:
        """Apply changes from the provider payload to an existing match row.

        Does not touch ``result_confirmed_at`` — that is admin-only.
        Does not downgrade status from terminal states.
        """
        changed = False

        # --- Team / competition name corrections -----------------------
        if existing.home_team != payload.home_team:
            existing.home_team = payload.home_team
            changed = True
        if existing.away_team != payload.away_team:
            existing.away_team = payload.away_team
            changed = True
        if existing.competition != payload.competition:
            existing.competition = payload.competition
            changed = True

        # --- Kickoff rescheduling --------------------------------------
        # Normalise both to UTC for comparison
        existing_ko = existing.kickoff_at
        if existing_ko.tzinfo is None:
            existing_ko = existing_ko.replace(tzinfo=timezone.utc)
        if abs((existing_ko - payload.kickoff_at).total_seconds()) > 60:
            existing.kickoff_at = payload.kickoff_at
            changed = True

        # --- Status transition -----------------------------------------
        if existing.status != payload.internal_status:
            allowed = _ALLOWED_TRANSITIONS.get(existing.status, set())
            if payload.internal_status in allowed:
                existing.status = payload.internal_status
                changed = True
            else:
                logger.debug(
                    "sync.status_skip external_id=%s current=%s proposed=%s",
                    payload.external_id,
                    existing.status,
                    payload.internal_status,
                )

        # --- Result (only when match is complete and not yet confirmed) --
        if (
            payload.internal_outcome is not None
            and existing.result_confirmed_at is None
        ):
            if existing.outcome != payload.internal_outcome:
                existing.outcome = payload.internal_outcome
                changed = True
            if existing.result_home_score != payload.home_score:
                existing.result_home_score = payload.home_score
                changed = True
            if existing.result_away_score != payload.away_score:
                existing.result_away_score = payload.away_score
                changed = True

        # Always update sync timestamp so we know the record was seen
        existing.last_synced_at = now
        self._db.add(existing)
        await self._db.flush()

        if changed:
            logger.debug(
                "sync.updated external_id=%s status=%s",
                payload.external_id,
                existing.status,
            )
            return "updated"

        return "skipped"
