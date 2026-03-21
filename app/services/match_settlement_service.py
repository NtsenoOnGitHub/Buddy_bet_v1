"""Match settlement service — integration flow triggered when a match result
is confirmed.

Responsibilities
----------------
1. Confirm the match result: set outcome, scores, status=completed,
   result_confirmed_at — inside a dedicated transaction.
2. Move all MATCHED bets for that match to PENDING_SETTLEMENT — in the same
   transaction as step 1 so the two writes are atomic.
3. For each PENDING_SETTLEMENT bet: call SettlementService.settle_bet() and
   commit — one transaction per bet so a single failure does not block others.
4. Return a SettlementResult summary that the caller can log or return to the admin.

Transaction model
-----------------
- Step 1+2 share one transaction (match update + bet transitions).
- Each bet settlement is its own transaction (commit on success, rollback on
  any error including SettlementIdempotencyError to avoid leaking partial state).
- The caller (admin endpoint) provides a single AsyncSession whose transaction
  lifecycle is fully managed here.

Caller owns nothing — confirm_and_settle() handles all commits and rollbacks.
"""

from __future__ import annotations

import dataclasses
import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError, SettlementIdempotencyError, ValidationError
from app.models.bet import Bet
from app.models.bet_event import BetEvent
from app.models.enums import BetEventType, FootballOutcome, MatchStatus
from app.repositories.bet_repository import BetRepository
from app.repositories.match_repository import MatchRepository
from app.services.settlement_service import SettlementService

logger = logging.getLogger(__name__)


@dataclasses.dataclass
class SettlementResult:
    """Summary returned after a match settlement run."""

    match_id: uuid.UUID
    outcome: str
    bets_found: int
    bets_settled: int
    bets_already_settled: int
    bets_failed: int
    failed_bet_ids: list[uuid.UUID]
    failure_reasons: dict[uuid.UUID, str] = dataclasses.field(default_factory=dict)
    """Maps failed bet_id → error message for ops visibility."""


class MatchSettlementService:
    """Orchestrates confirming a match result and settling all associated bets."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db
        self._match_repo = MatchRepository(db)
        self._bet_repo = BetRepository(db)

    # -----------------------------------------------------------------------
    # Public entry point
    # -----------------------------------------------------------------------

    async def confirm_and_settle(
        self,
        match_id: uuid.UUID,
        outcome: FootballOutcome,
        home_score: int,
        away_score: int,
        confirmed_by: uuid.UUID,
    ) -> SettlementResult:
        """Confirm the match result and settle all eligible bets.

        Steps
        -----
        Transaction A (match + PENDING_SETTLEMENT transitions):
          1. Fetch match with SELECT FOR UPDATE.
          2. Validate: match must be in a settleable state.
          3. Update match: outcome, scores, status=completed, result_confirmed_at.
          4. Transition all MATCHED bets to PENDING_SETTLEMENT (SELECT FOR UPDATE).
          5. Write PENDING_SETTLEMENT bet_events.
          6. Commit transaction A.

        For each pending bet — Transaction B (one per bet):
          7. Call SettlementService.settle_bet(bet.id).
          8. Commit on success.
          9. On SettlementIdempotencyError: rollback + log (already settled).
         10. On any other error: rollback + record failure + continue.

        Args:
            match_id:     Match to confirm.
            outcome:      Confirmed FootballOutcome (home_win | away_win | draw).
            home_score:   Final home team score.
            away_score:   Final away team score.
            confirmed_by: Admin user ID (for audit trail).

        Returns:
            SettlementResult summary.

        Raises:
            NotFoundError:  Match does not exist.
            ValidationError: Match is already completed or has an outcome set.
        """
        # ------------------------------------------------------------------
        # Transaction A: confirm match + transition bets
        # ------------------------------------------------------------------
        try:
            match = await self._match_repo.get_for_update(match_id)

            if match.status == MatchStatus.completed:
                raise ValidationError(
                    f"Match {match_id} is already marked as completed."
                )
            if match.outcome is not None:
                raise ValidationError(
                    f"Match {match_id} already has a confirmed outcome: "
                    f"{match.outcome.value!r}."
                )

            now = datetime.now(tz=timezone.utc)
            match.outcome = outcome
            match.result_home_score = home_score
            match.result_away_score = away_score
            match.status = MatchStatus.completed
            match.result_confirmed_at = now
            self._db.add(match)
            await self._db.flush()

            # Transition MATCHED → PENDING_SETTLEMENT (one query, locked)
            pending_bets = await self._bet_repo.transition_matched_to_pending(match_id)

            # Write PENDING_SETTLEMENT audit event per bet
            for bet in pending_bets:
                self._db.add(
                    BetEvent(
                        bet_id=bet.id,
                        event_type=BetEventType.PENDING_SETTLEMENT,
                        actor_id=confirmed_by,
                        actor_label="SETTLEMENT_ENGINE",
                        payload={
                            "match_outcome": outcome.value,
                            "triggered_by": str(confirmed_by),
                        },
                    )
                )
            await self._db.flush()
            await self._db.commit()

            logger.info(
                "settlement.match.confirmed match_id=%s outcome=%s bets_queued=%d",
                match_id,
                outcome.value,
                len(pending_bets),
            )

        except Exception:
            await self._db.rollback()
            raise

        # ------------------------------------------------------------------
        # Transactions B…N: settle each bet independently
        # ------------------------------------------------------------------
        bet_ids = [b.id for b in pending_bets]
        settled = 0
        already_settled = 0
        failed: list[uuid.UUID] = []
        failure_reasons: dict[uuid.UUID, str] = {}

        for bet_id in bet_ids:
            try:
                settlement_svc = SettlementService(self._db)
                await settlement_svc.settle_bet(bet_id)
                await self._db.commit()
                settled += 1
                logger.info(
                    "settlement.bet.ok bet_id=%s match_id=%s",
                    bet_id, match_id,
                )

            except SettlementIdempotencyError as e:
                await self._db.rollback()
                already_settled += 1
                logger.warning(
                    "settlement.bet.already_settled bet_id=%s match_id=%s reason=%r",
                    bet_id, match_id, str(e),
                )

            except Exception as e:
                await self._db.rollback()
                reason = f"{type(e).__name__}: {e}"
                failed.append(bet_id)
                failure_reasons[bet_id] = reason
                logger.exception(
                    "settlement.bet.failed bet_id=%s match_id=%s reason=%r",
                    bet_id, match_id, reason,
                )

        logger.info(
            "settlement.run.complete match_id=%s outcome=%s "
            "found=%d settled=%d already_settled=%d failed=%d",
            match_id, outcome.value,
            len(bet_ids), settled, already_settled, len(failed),
        )

        return SettlementResult(
            match_id=match_id,
            outcome=outcome.value,
            bets_found=len(bet_ids),
            bets_settled=settled,
            bets_already_settled=already_settled,
            bets_failed=len(failed),
            failed_bet_ids=failed,
            failure_reasons=failure_reasons,
        )

    async def settle_single_bet(self, bet_id: uuid.UUID) -> Bet:
        """Manually trigger settlement for a single PENDING_SETTLEMENT bet.

        Called from the admin manual-settle endpoint. Caller does NOT commit —
        this method handles commit/rollback.

        Returns:
            The refreshed Bet instance after successful settlement.

        Raises:
            SettlementIdempotencyError: Bet is not in PENDING_SETTLEMENT.
            Any exception from SettlementService.settle_bet.
        """
        try:
            svc = SettlementService(self._db)
            bet = await svc.settle_bet(bet_id)
            await self._db.commit()
            return bet
        except Exception:
            await self._db.rollback()
            raise

    async def get_pending_settlement_bets(
        self,
        match_id: uuid.UUID | None = None,
    ) -> list[Bet]:
        """Return all bets currently stuck in PENDING_SETTLEMENT.

        Used by the admin ops visibility endpoint. Ordered oldest-first so ops
        can prioritise the most overdue bets.

        Args:
            match_id: When provided, restricts to a single match.
        """
        return await self._bet_repo.get_pending_settlement(match_id=match_id)
