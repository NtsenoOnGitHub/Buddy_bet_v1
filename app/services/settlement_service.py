"""Settlement service — full implementation of the bet settlement engine.

The Settlement Engine is triggered after a match result is confirmed. For each
PENDING_SETTLEMENT bet it:
  1. Determines the settlement path from match outcome and user predictions.
  2. Computes fee and payout amounts using versioned fee rates.
  3. Executes all wallet mutations and ledger entries inside one transaction.
  4. Credits the platform account.
  5. Atomically transitions the bet status from PENDING_SETTLEMENT → SETTLED.
  6. Writes an immutable SETTLED bet_event for the audit trail.

Transaction ownership:
  The caller (e.g. a background job or admin endpoint) owns commit/rollback.
  settle_bet() only flushes; it never commits. If any step raises, the caller
  rolls back and the bet remains in PENDING_SETTLEMENT for retry.

Settlement path decision (spec Section 9.2):
  IF   creator_prediction  == match_outcome  → PATH A: creator_wins
  ELIF opponent_prediction == match_outcome  → PATH B: opponent_wins
  ELSE                                       → PATH C: no_winner

Idempotency guard (spec Section 9.7):
  Step 1 (early): verify bet.status == PENDING_SETTLEMENT immediately after
                  the SELECT FOR UPDATE.
  Step 2 (late):  execute UPDATE bets SET status='SETTLED'
                    WHERE id=? AND status='PENDING_SETTLEMENT'.
                  If rowcount == 0 a concurrent process already settled —
                  raise SettlementIdempotencyError. The caller should NOT
                  roll back the transaction in this case (no partial state
                  was written because the concurrent process already committed).
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional, Tuple

from sqlalchemy import update as sa_update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    InsufficientFundsError,
    NotFoundError,
    SettlementIdempotencyError,
    ValidationError,
)
from app.models.bet import Bet
from app.models.bet_event import BetEvent
from app.models.enums import (
    BetEventType,
    BetStatus,
    FeeType,
    FootballOutcome,
    PlatformEntryType,
    SettlementOutcome,
    SettlementPathType,
)
from app.repositories.bet_repository import BetRepository
from app.repositories.fee_config_repository import FeeConfigRepository
from app.repositories.match_repository import MatchRepository
from app.repositories.platform_repository import PlatformRepository
from app.repositories.wallet_repository import WalletRepository
from app.services.ledger_service import LedgerService
from app.services.wallet_service import WalletService
from app.utils.decimal_utils import (
    safe_add,
    safe_multiply,
    safe_subtract,
    verify_non_negative,
)

logger = logging.getLogger(__name__)


class SettlementService:
    """Executes the full settlement flow for a single bet.

    Each public method must be called within an open transaction. The caller
    is responsible for committing. If any step raises, the caller rolls back
    and the bet remains in PENDING_SETTLEMENT for retry.
    """

    def __init__(self, db: AsyncSession) -> None:
        self._db = db
        self._bet_repo = BetRepository(db)
        self._match_repo = MatchRepository(db)
        self._fee_repo = FeeConfigRepository(db)
        self._wallet_service = WalletService(db)
        self._wallet_repo = WalletRepository(db)
        self._ledger = LedgerService(db)
        self._platform_repo = PlatformRepository(db)

    # -----------------------------------------------------------------------
    # Public entry point
    # -----------------------------------------------------------------------

    async def settle_bet(self, bet_id: uuid.UUID) -> None:
        """Execute the complete settlement flow for a single bet.

        Must be called inside an open transaction. Caller owns commit/rollback.

        Steps (all within one transaction):
          1.  Fetch bet with SELECT FOR UPDATE.
          2.  Guard: bet.status == PENDING_SETTLEMENT (idempotency step 1).
          3.  Validate bet is fully matched (opponent + prediction not None).
          4.  Fetch confirmed match outcome (read-only, no lock).
          5.  Resolve applicable fee rates from fee_config at settlement time.
          6.  Determine settlement path via _determine_path().
          7.  Compute amounts via _compute_winner_amounts() or
              _compute_no_winner_amounts().
          8.  Lock wallets in ascending UUID order (deadlock prevention).
          9.  Execute balance mutations and write user ledger entries.
          10. Lock platform account (SELECT FOR UPDATE), credit fee, write
              platform ledger entry.
          11. Idempotency guard: UPDATE bets SET status='SETTLED'
                WHERE id=? AND status='PENDING_SETTLEMENT'.
              If rowcount == 0: raise SettlementIdempotencyError.
          12. Refresh bet ORM instance; write SETTLED bet_event.

        Args:
            bet_id: UUID of the bet to settle.

        Raises:
            SettlementIdempotencyError: bet.status != PENDING_SETTLEMENT, or
                                        the idempotency UPDATE matched 0 rows.
            NotFoundError:              Bet, match, wallet, platform account, or
                                        fee config row not found.
            ValidationError:            Match has no confirmed outcome, or the
                                        bet is not fully matched.
            InsufficientFundsError:     A wallet has insufficient locked balance.
        """
        # ------------------------------------------------------------------
        # 1. Fetch bet with SELECT FOR UPDATE
        # ------------------------------------------------------------------
        bet = await self._bet_repo.get_for_update(bet_id)

        # ------------------------------------------------------------------
        # 2. Idempotency guard step 1: must be PENDING_SETTLEMENT
        # ------------------------------------------------------------------
        if bet.status != BetStatus.PENDING_SETTLEMENT:
            raise SettlementIdempotencyError(
                f"Bet {bet_id} has status {bet.status.value!r}; "
                "expected PENDING_SETTLEMENT. "
                "It may have already been settled or is in an unexpected state."
            )

        # ------------------------------------------------------------------
        # 3. Validate the bet is fully matched
        # ------------------------------------------------------------------
        if bet.opponent_id is None or bet.opponent_prediction is None:
            raise ValidationError(
                f"Bet {bet_id} cannot be settled: opponent_id or "
                "opponent_prediction is None. Bet must be in MATCHED state."
            )

        # ------------------------------------------------------------------
        # 4. Fetch confirmed match outcome (immutable once set — no lock needed)
        # ------------------------------------------------------------------
        match = await self._match_repo.get_by_id_or_404(bet.match_id)
        if match.outcome is None:
            raise ValidationError(
                f"Match {bet.match_id} has no confirmed outcome; "
                f"cannot settle bet {bet_id}."
            )

        # ------------------------------------------------------------------
        # 5. Resolve fee rates effective at settlement time
        # ------------------------------------------------------------------
        now = datetime.now(tz=timezone.utc)

        winner_fee_rate = await self._fee_repo.get_active_rate(
            FeeType.WINNER_FEE, bet.currency, now
        )
        no_winner_fee_rate = await self._fee_repo.get_active_rate(
            FeeType.NO_WINNER_FEE, bet.currency, now
        )

        # ------------------------------------------------------------------
        # 6. Determine settlement path
        # ------------------------------------------------------------------
        outcome = self._determine_path(
            match.outcome, bet.creator_prediction, bet.opponent_prediction
        )

        logger.info(
            "Settling bet %s: outcome=%s winner_rate=%s no_winner_rate=%s",
            bet_id, outcome.value, winner_fee_rate, no_winner_fee_rate,
        )

        # ------------------------------------------------------------------
        # 7–9. Compute amounts, lock wallets, execute mutations + user ledger
        # ------------------------------------------------------------------
        winner_id: Optional[uuid.UUID] = None
        payout_amount: Decimal
        platform_fee_amount: Decimal
        applied_winner_rate: Optional[Decimal] = None
        applied_no_winner_rate: Optional[Decimal] = None

        if outcome in (SettlementOutcome.creator_wins, SettlementOutcome.opponent_wins):
            # ── Winner path ────────────────────────────────────────────────
            winner_payout, platform_fee = self._compute_winner_amounts(
                bet.stake_amount, winner_fee_rate
            )
            winner_id = (
                bet.creator_id
                if outcome == SettlementOutcome.creator_wins
                else bet.opponent_id
            )
            loser_id = (
                bet.opponent_id
                if outcome == SettlementOutcome.creator_wins
                else bet.creator_id
            )

            # transfer_locked_funds locks wallets in sorted order, mutates
            # balances, and writes all user ledger entries atomically.
            await self._wallet_service.transfer_locked_funds(
                winner_id=winner_id,
                loser_id=loser_id,
                amount=bet.stake_amount,
                fee=platform_fee,
                bet_id=bet.id,
                notes=f"Settlement: {outcome.value}",
            )

            payout_amount = winner_payout
            platform_fee_amount = platform_fee
            applied_winner_rate = winner_fee_rate

        else:
            # ── No-winner path ─────────────────────────────────────────────
            refund_per_user, fee_per_user = self._compute_no_winner_amounts(
                bet.stake_amount, no_winner_fee_rate
            )
            total_platform_fee = safe_add(fee_per_user, fee_per_user)

            await self._settle_no_winner(
                creator_id=bet.creator_id,
                opponent_id=bet.opponent_id,
                stake_amount=bet.stake_amount,
                fee_per_user=fee_per_user,
                refund_per_user=refund_per_user,
                bet_id=bet.id,
            )

            payout_amount = refund_per_user
            platform_fee_amount = total_platform_fee
            applied_no_winner_rate = no_winner_fee_rate

        # ------------------------------------------------------------------
        # 10. Credit platform account (SELECT FOR UPDATE) + platform ledger
        # ------------------------------------------------------------------
        platform_account = await self._platform_repo.get_for_currency_for_update(
            bet.currency
        )
        platform_account = await self._platform_repo.credit_fee(
            platform_account, platform_fee_amount
        )
        await self._platform_repo.write_ledger_entry(
            account=platform_account,
            amount=platform_fee_amount,
            bet_id=bet.id,
            entry_type=(
                PlatformEntryType.FEE_COLLECTION
                if outcome != SettlementOutcome.no_winner
                else PlatformEntryType.FEE_COLLECTION_NO_WINNER
            ),
            settlement_path=(
                SettlementPathType.winner
                if outcome != SettlementOutcome.no_winner
                else SettlementPathType.no_winner
            ),
        )

        # ------------------------------------------------------------------
        # 11. Idempotency guard step 2: atomic PENDING_SETTLEMENT → SETTLED
        #
        #     This UPDATE is the single source of truth for the status
        #     transition. The WHERE clause on status='PENDING_SETTLEMENT'
        #     ensures that if a concurrent process already committed a SETTLED
        #     status, this UPDATE matches 0 rows and we abort cleanly.
        # ------------------------------------------------------------------
        result = await self._db.execute(
            sa_update(Bet)
            .where(Bet.id == bet.id)
            .where(Bet.status == BetStatus.PENDING_SETTLEMENT)
            .values(
                status=BetStatus.SETTLED,
                settlement_outcome=outcome,
                winner_id=winner_id,
                payout_amount=payout_amount,
                platform_fee=platform_fee_amount,
                applied_winner_fee_rate=applied_winner_rate,
                applied_no_winner_fee_rate=applied_no_winner_rate,
                settled_at=now,
                updated_at=now,
            )
            .execution_options(synchronize_session=False)
        )
        if result.rowcount == 0:
            raise SettlementIdempotencyError(
                f"Bet {bet_id} was already settled by a concurrent process "
                "(idempotency UPDATE matched 0 rows)."
            )

        # Reload the ORM instance to reflect the raw UPDATE above.
        await self._db.refresh(bet)

        # ------------------------------------------------------------------
        # 12. Write SETTLED bet_event (immutable audit trail)
        # ------------------------------------------------------------------
        self._db.add(
            BetEvent(
                bet_id=bet.id,
                event_type=BetEventType.SETTLED,
                actor_id=None,
                actor_label="SETTLEMENT_ENGINE",
                payload={
                    "settlement_outcome": outcome.value,
                    "winner_id": str(winner_id) if winner_id else None,
                    "payout_amount": str(payout_amount),
                    "platform_fee": str(platform_fee_amount),
                    "applied_winner_fee_rate": str(applied_winner_rate) if applied_winner_rate else None,
                    "applied_no_winner_fee_rate": str(applied_no_winner_rate) if applied_no_winner_rate else None,
                },
            )
        )
        await self._db.flush()

        logger.info(
            "Bet %s settled successfully: outcome=%s winner=%s payout=%s fee=%s",
            bet_id,
            outcome.value,
            winner_id,
            payout_amount,
            platform_fee_amount,
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
        """Determine the settlement path from match outcome and user predictions.

        Decision logic (spec Section 9.2):
          IF   creator_prediction  == match_outcome  → creator_wins
          ELIF opponent_prediction == match_outcome  → opponent_wins
          ELSE                                       → no_winner

        It is structurally impossible for both users to win simultaneously
        because they must hold different predictions and only one outcome occurs.

        Args:
            match_outcome: The confirmed result of the match.
            creator_prediction: The prediction made by the bet creator (User A).
            opponent_prediction: The prediction made by the bet acceptor (User B).

        Returns:
            SettlementOutcome enum value (creator_wins, opponent_wins, no_winner).
        """
        if creator_prediction == match_outcome:
            return SettlementOutcome.creator_wins
        elif opponent_prediction == match_outcome:
            return SettlementOutcome.opponent_wins
        else:
            return SettlementOutcome.no_winner

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
            platform_fee  = round_half_up(total_pool × winner_fee_rate)
            winner_payout = total_pool − platform_fee

        Sum check: platform_fee + winner_payout == total_pool

        Sub-cent remainder is retained by the platform because winner_payout
        is total_pool minus the already-rounded fee (spec PO-06).

        Args:
            stake_amount:    Each user's individual stake (both stakes are equal).
            winner_fee_rate: Platform fee rate e.g. Decimal("0.1000") for 10%.

        Returns:
            Tuple of (winner_payout, platform_fee) as Decimal values.
        """
        total_pool = safe_add(stake_amount, stake_amount)          # 2 × stake
        platform_fee = safe_multiply(total_pool, winner_fee_rate)  # round half-up
        winner_payout = safe_subtract(total_pool, platform_fee)    # remainder to winner
        return winner_payout, platform_fee

    # -----------------------------------------------------------------------
    # No-winner path amounts (PATH C)
    # -----------------------------------------------------------------------

    def _compute_no_winner_amounts(
        self,
        stake_amount: Decimal,
        no_winner_fee_rate: Decimal,
    ) -> Tuple[Decimal, Decimal]:
        """Compute per-user refund and per-user fee for the no-winner path.

        Arithmetic (spec Section 9.4):
            fee_per_user    = round_half_up(stake_amount × no_winner_fee_rate)
            refund_per_user = stake_amount − fee_per_user

        Sum check per user: fee_per_user + refund_per_user == stake_amount
        Total platform fee: fee_per_user × 2

        Args:
            stake_amount:        Each user's individual stake.
            no_winner_fee_rate:  Platform fee rate e.g. Decimal("0.0500") for 5%.

        Returns:
            Tuple of (refund_per_user, fee_per_user) as Decimal values.
        """
        fee_per_user = safe_multiply(stake_amount, no_winner_fee_rate)   # round half-up
        refund_per_user = safe_subtract(stake_amount, fee_per_user)      # remainder to user
        return refund_per_user, fee_per_user

    # -----------------------------------------------------------------------
    # Internal: no-winner wallet mutations
    # -----------------------------------------------------------------------

    async def _settle_no_winner(
        self,
        creator_id: uuid.UUID,
        opponent_id: uuid.UUID,
        stake_amount: Decimal,
        fee_per_user: Decimal,
        refund_per_user: Decimal,
        bet_id: uuid.UUID,
    ) -> None:
        """Lock both wallets and execute no-winner balance mutations + user ledger.

        Balance movements per user:
          locked    -= stake_amount          (full locked stake consumed)
          available += refund_per_user       (95% stake refunded to available)
          (fee_per_user is implicitly retained by platform)

        Wallet lock order: ascending UUID string to prevent deadlocks under
        concurrent no-winner settlements.

        Ledger entries written via LedgerService.write_settlement_no_winner:
          Per user (creator then opponent):
            1. FEE_DEDUCT        | locked    | debit  | fee_per_user
            2. SETTLEMENT_DEDUCT | locked    | debit  | refund_per_user
            3. REFUND_CREDIT     | available | credit | refund_per_user

        Args:
            creator_id:      Bet creator user ID.
            opponent_id:     Bet opponent user ID.
            stake_amount:    Each user's locked stake.
            fee_per_user:    Platform fee portion per user.
            refund_per_user: Amount returned to each user's available balance.
            bet_id:          Settled bet UUID (ledger reference_id).
        """
        # Lock wallets in deterministic ascending UUID order to prevent deadlocks.
        ids_ordered = sorted([creator_id, opponent_id], key=str)
        wallets: dict[uuid.UUID, object] = {}
        for uid in ids_ordered:
            wallets[uid] = await self._wallet_repo.get_by_user_id_for_update(uid)

        creator_wallet = wallets[creator_id]
        opponent_wallet = wallets[opponent_id]

        # Validate both wallets have enough locked balance.
        for wallet, label in [
            (creator_wallet, "creator"),
            (opponent_wallet, "opponent"),
        ]:
            if wallet.locked_balance < stake_amount:
                raise InsufficientFundsError(
                    f"No-winner settlement: {label} locked_balance insufficient. "
                    f"Required: {stake_amount}, Locked: {wallet.locked_balance}."
                )

        # Compute new balances (no mutation yet — all-or-nothing).
        creator_new_locked = safe_subtract(creator_wallet.locked_balance, stake_amount)
        creator_new_available = safe_add(creator_wallet.available_balance, refund_per_user)
        opponent_new_locked = safe_subtract(opponent_wallet.locked_balance, stake_amount)
        opponent_new_available = safe_add(opponent_wallet.available_balance, refund_per_user)

        verify_non_negative(creator_new_locked, "creator locked_balance")
        verify_non_negative(creator_new_available, "creator available_balance")
        verify_non_negative(opponent_new_locked, "opponent locked_balance")
        verify_non_negative(opponent_new_available, "opponent available_balance")

        # Persist both balance updates before any ledger write.
        creator_wallet = await self._wallet_repo.update_balances(
            creator_wallet,
            available_balance=creator_new_available,
            locked_balance=creator_new_locked,
        )
        opponent_wallet = await self._wallet_repo.update_balances(
            opponent_wallet,
            available_balance=opponent_new_available,
            locked_balance=opponent_new_locked,
        )

        # Write user ledger entries (post-update snapshots are now on wallets).
        await self._ledger.write_settlement_no_winner(
            creator_wallet=creator_wallet,
            opponent_wallet=opponent_wallet,
            fee_per_user=fee_per_user,
            refund_per_user=refund_per_user,
            bet_id=bet_id,
            notes="No-winner settlement: fee deducted, remainder refunded",
        )
