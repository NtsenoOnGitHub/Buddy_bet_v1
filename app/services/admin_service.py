"""Admin service — manual administrative operations on bets.

Handles:
  - void_bet: void a bet in OPEN or MATCHED status, refunding all locked stakes.

This service is intentionally narrow. It covers only operations that bypass
the normal user-facing lifecycle (create → accept → settle).

Transaction ownership:
  get_db (dependency) owns commit/rollback.  Services only call flush().
"""

from __future__ import annotations

import logging
import uuid
from typing import List

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BetNotAvailableError, ValidationError
from app.models.bet_event import BetEvent
from app.models.enums import BetEventType, BetStatus, SettlementOutcome
from app.repositories.bet_repository import BetRepository
from app.services.wallet_service import WalletService

logger = logging.getLogger(__name__)


class AdminService:
    """Administrative operations that operate outside the normal bet lifecycle."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db
        self._bet_repo = BetRepository(db)
        self._wallet_service = WalletService(db)

    # -----------------------------------------------------------------------
    # Void bet
    # -----------------------------------------------------------------------

    async def void_bet(
        self,
        bet_id: uuid.UUID,
        admin_user_id: uuid.UUID,
        reason: str | None = None,
    ) -> List[uuid.UUID]:
        """Void a bet and refund all locked stakes to the affected users.

        Eligible statuses: OPEN (creator stake locked) or MATCHED (both stakes locked).
        Any other status raises BetNotAvailableError.

        Transaction model: get_db owns commit/rollback; this method only flushes.

        Void refund ledger entries:
          - OPEN:    VOID_REFUND for creator only.
          - MATCHED: VOID_REFUND for creator + opponent.

        Args:
            bet_id:        Bet to void.
            admin_user_id: Admin user performing the void (audit trail).
            reason:        Optional admin note stored in the BetEvent payload.

        Returns:
            List of user IDs whose stakes were refunded.

        Raises:
            BetNotAvailableError: Bet is not in OPEN or MATCHED status.
            NotFoundError:        Bet does not exist.
        """
        # SELECT FOR UPDATE: prevent concurrent status changes
        bet = await self._bet_repo.get_for_update(bet_id)

        if bet.status not in (BetStatus.OPEN, BetStatus.MATCHED):
            raise BetNotAvailableError(
                f"Bet {bet_id} cannot be voided from status "
                f"'{bet.status.value}'. Only OPEN or MATCHED bets may be voided."
            )

        refunded_users: list[uuid.UUID] = []
        notes = reason or "Admin void"

        # Refund creator stake (always locked if status is OPEN or MATCHED)
        await self._wallet_service.void_refund(
            user_id=bet.creator_id,
            amount=bet.stake_amount,
            bet_id=bet.id,
            notes=notes,
        )
        refunded_users.append(bet.creator_id)

        # Refund opponent stake (only locked if status is MATCHED)
        if bet.status == BetStatus.MATCHED and bet.opponent_id is not None:
            await self._wallet_service.void_refund(
                user_id=bet.opponent_id,
                amount=bet.stake_amount,
                bet_id=bet.id,
                notes=notes,
            )
            refunded_users.append(bet.opponent_id)

        # Transition bet to VOIDED
        bet.status = BetStatus.VOIDED
        bet.settlement_outcome = SettlementOutcome.voided
        self._db.add(bet)
        await self._db.flush()
        await self._db.refresh(bet)

        # Write VOIDED audit event
        self._db.add(
            BetEvent(
                bet_id=bet.id,
                event_type=BetEventType.VOIDED,
                actor_id=admin_user_id,
                actor_label="ADMIN",
                payload={
                    "voided_by": str(admin_user_id),
                    "reason": reason,
                    "refunded_user_ids": [str(u) for u in refunded_users],
                },
            )
        )
        await self._db.flush()

        logger.info(
            "Bet %s voided by admin %s; refunded users: %s",
            bet_id,
            admin_user_id,
            refunded_users,
        )
        return refunded_users
