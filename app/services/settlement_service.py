"""Settlement service — stub with correct signatures and docstrings.

The Settlement Engine is triggered after a match result is confirmed. It reads
the match outcome, determines the settlement path per bet, computes all fee and
payout amounts, executes fund movements atomically, and records all outcomes.

This file contains stubs with complete signatures and docstrings per the spec.
Full implementation is tracked in the post-MVP settlement sprint.

Settlement path decision (spec Section 9.2):
  IF   creator_prediction  == match_outcome  → PATH A: Creator wins
  ELIF opponent_prediction == match_outcome  → PATH B: Opponent wins
  ELSE                                       → PATH C: No winner

Idempotency guard (spec Section 9.7):
  The final status update must be:
    UPDATE bets SET status='SETTLED' WHERE id=? AND status='PENDING_SETTLEMENT'
  If 0 rows affected: another process already settled — abort without rollback.
"""

from __future__ import annotations

import logging
import uuid
from decimal import Decimal
from typing import Tuple

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import FootballOutcome, SettlementOutcome

logger = logging.getLogger(__name__)


class SettlementService:
    """Executes the full settlement flow for a single bet.

    Each public method must be called within an open transaction. The caller
    is responsible for committing. If any step raises, the caller rolls back
    and the bet remains in PENDING_SETTLEMENT for retry.
    """

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    # -----------------------------------------------------------------------
    # Public entry point
    # -----------------------------------------------------------------------

    async def settle_bet(self, bet_id: uuid.UUID) -> None:
        """Execute the complete settlement flow for a single bet.

        TODO: Implement full settlement flow.

        Steps (all within one transaction):
          1. Fetch bet with SELECT FOR UPDATE.
          2. Verify bet.status == 'PENDING_SETTLEMENT' (idempotency guard step 1).
          3. Fetch the confirmed match outcome.
          4. Resolve applicable fee rates from fee_config.
          5. Determine settlement path via _determine_path().
          6. Compute amounts via _compute_winner_amounts() or _compute_no_winner_amounts().
          7. Lock both wallets (SELECT FOR UPDATE).
          8. Execute all balance mutations and ledger entries atomically.
          9. Credit platform account and write platform_ledger_entry.
         10. Update bet: status=SETTLED, settlement_outcome, winner_id, payout_amount,
             platform_fee, applied_*_fee_rate, settled_at.
         11. Idempotency guard step 2:
             UPDATE bets SET status='SETTLED' WHERE id=? AND status='PENDING_SETTLEMENT'
             If 0 rows affected: abort (already settled).
         12. Write SETTLED bet_event.

        Args:
            bet_id: The UUID of the bet to settle.

        Raises:
            SettlementIdempotencyError: If the bet has already been settled.
            NotFoundError: If the bet or match does not exist.
        """
        # TODO: Implement full settlement flow.
        # Reference spec Sections 9.3, 9.4, and 9.5 for ledger entry sequences.
        raise NotImplementedError(
            "settle_bet is not yet implemented. "
            "See settlement_service.py docstrings for the required sequence."
        )

    # -----------------------------------------------------------------------
    # Path determination
    # -----------------------------------------------------------------------

    def _determine_path(
        self,
        match_outcome: FootballOutcome,
        creator_prediction: FootballOutcome,
        opponent_prediction: FootballOutcome,
    ) -> SettlementOutcome:
        """Determine the settlement path from match outcome and predictions.

        Decision logic (spec Section 9.2):
          IF   creator_prediction  == match_outcome  → creator_wins
          ELIF opponent_prediction == match_outcome  → opponent_wins
          ELSE                                       → no_winner

        It is structurally impossible for both users to win simultaneously
        because they hold different predictions and only one outcome occurs.

        Args:
            match_outcome: The confirmed result of the match.
            creator_prediction: The prediction made by User A.
            opponent_prediction: The prediction made by User B.

        Returns:
            SettlementOutcome enum value.

        TODO: This method is a stub — the decision logic is described above.
        """
        # TODO: Implement path determination.
        raise NotImplementedError("_determine_path is not yet implemented.")

    # -----------------------------------------------------------------------
    # Winner path amounts (PATH A / B)
    # -----------------------------------------------------------------------

    def _compute_winner_amounts(
        self,
        stake_amount: Decimal,
        winner_fee_rate: Decimal,
    ) -> Tuple[Decimal, Decimal]:
        """Compute payout and platform fee for the winner settlement path.

        Arithmetic (spec Section 9.3):
            total_pool    = stake_amount × 2
            platform_fee  = total_pool × winner_fee_rate
            winner_payout = total_pool × (1 − winner_fee_rate)

        Sum check: platform_fee + winner_payout == total_pool

        Rounding: ROUND_HALF_UP to nearest cent (PO-06 default).
        Sub-cent remainder goes to platform (winner_payout is rounded down).

        Args:
            stake_amount: Each user's individual stake (both users stake the same amount).
            winner_fee_rate: Platform fee rate for the winner path (e.g. Decimal('0.10')).

        Returns:
            Tuple of (winner_payout, platform_fee) as Decimal values.

        TODO: Implement using decimal_utils.safe_multiply and round_half_up.
        """
        # TODO: Implement amount computation.
        raise NotImplementedError("_compute_winner_amounts is not yet implemented.")

    # -----------------------------------------------------------------------
    # No-winner path amounts (PATH C)
    # -----------------------------------------------------------------------

    def _compute_no_winner_amounts(
        self,
        stake_amount: Decimal,
        no_winner_fee_rate: Decimal,
    ) -> Tuple[Decimal, Decimal]:
        """Compute per-user refund and per-user fee for the no-winner settlement path.

        Arithmetic (spec Section 9.4):
            fee_per_user    = stake_amount × no_winner_fee_rate
            refund_per_user = stake_amount × (1 − no_winner_fee_rate)
            total_fee       = fee_per_user × 2

        Sum check: (fee_per_user + refund_per_user) × 2 == stake_amount × 2

        Rounding: ROUND_HALF_UP to nearest cent per user.

        Args:
            stake_amount: Each user's individual stake.
            no_winner_fee_rate: Platform fee rate for no-winner path (e.g. Decimal('0.05')).

        Returns:
            Tuple of (refund_per_user, fee_per_user) as Decimal values.

        TODO: Implement using decimal_utils.safe_multiply and round_half_up.
        """
        # TODO: Implement amount computation.
        raise NotImplementedError("_compute_no_winner_amounts is not yet implemented.")
