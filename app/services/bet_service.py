"""Bet service — create, accept, cancel, and list bets.

Business rules enforced here:
  BR-01: A user cannot accept their own bet.
  BR-02: Only one opponent per bet (SELECT FOR UPDATE + status check).
  BR-03: Bets cannot be accepted at or after match kickoff.
  BR-04: Creator's stake locked at creation time.
  BR-05: Opponent's stake must equal creator's stake exactly.
  BR-06/07: opponent_prediction must differ from creator_prediction.
  BR-13: Only creator can cancel; only while OPEN.
  BR-14: Wallet balances never go negative (enforced via WalletService).

Concurrency safety:
  - Wallet lock: WalletService.lock_stake uses SELECT FOR UPDATE on wallet row.
  - Bet acceptance: BetRepository.get_for_update uses SELECT FOR UPDATE on bet row.
  - Both locks are held inside the SAME transaction, preventing all known races.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.exceptions import (
    AccountIneligibleError,
    BetExpiredError,
    BetNotAvailableError,
    ForbiddenError,
    MatchNotAvailableError,
    PredictionConflictError,
    SelfBetError,
    ValidationError,
)
from app.models.bet import Bet
from app.models.bet_event import BetEvent
from app.models.enums import BetEventType, BetStatus, MatchStatus
from app.models.user import User
from app.repositories.bet_repository import BetRepository
from app.repositories.match_repository import MatchRepository
from app.schemas.bet import (
    AcceptBetRequest,
    BetListResponse,
    BetResponse,
    CreateBetRequest,
)
from app.schemas.common import PageParams
from app.services.wallet_service import WalletService

logger = logging.getLogger(__name__)
settings = get_settings()


class BetService:
    """Business logic for bet lifecycle operations."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db
        self._bet_repo = BetRepository(db)
        self._match_repo = MatchRepository(db)
        self._wallet_service = WalletService(db)

    # -----------------------------------------------------------------------
    # Create Bet
    # -----------------------------------------------------------------------

    async def create_bet(self, creator: User, request: CreateBetRequest) -> BetResponse:
        """Create a new OPEN bet and lock the creator's stake.

        Transaction sequence:
          1. Validate account, match status, kickoff cutoff, stake limits.
          2. Persist the Bet row (status=OPEN) to obtain a real bet.id.
          3. Lock the creator's stake via WalletService (SELECT FOR UPDATE on wallet).
          4. Write CREATED bet_event.
          All steps share the same transaction — callers commit via get_db.

        Args:
            creator: The authenticated user creating the bet.
            request: Validated creation payload.

        Returns:
            BetResponse for the newly created bet.
        """
        # Account status check
        if creator.status.value != "active":
            raise AccountIneligibleError("Your account must be active to create bets.")

        # Validate match
        match = await self._match_repo.get_by_id_or_404(request.match_id)

        if match.status != MatchStatus.scheduled:
            raise MatchNotAvailableError(
                f"Match is not available for betting "
                f"(current status: '{match.status.value}'). "
                "Only 'scheduled' matches accept new bets."
            )

        now = datetime.now(tz=timezone.utc)
        cutoff_dt = match.kickoff_at - timedelta(minutes=settings.bet_creation_cutoff_minutes)
        if now >= cutoff_dt:
            raise MatchNotAvailableError(
                f"Bet creation is closed — the match kicks off within "
                f"{settings.bet_creation_cutoff_minutes} minutes."
            )

        # Stake validation
        stake = Decimal(str(request.stake_amount))
        if stake <= Decimal("0"):
            raise ValidationError("stake_amount must be greater than zero.")
        if stake < settings.min_stake_amount:
            raise ValidationError(
                f"stake_amount is below the minimum of {settings.min_stake_amount}."
            )
        if stake > settings.max_stake_amount:
            raise ValidationError(
                f"stake_amount exceeds the maximum of {settings.max_stake_amount}."
            )

        # Step 2: Persist the bet row to get a real bet.id
        # expires_at = match.kickoff_at (spec: bets.expires_at = matches.kickoff_at)
        bet = Bet(
            match_id=request.match_id,
            creator_id=creator.id,
            creator_prediction=request.creator_prediction,
            stake_amount=stake,
            currency=settings.platform_currency,
            status=BetStatus.OPEN,
            expires_at=match.kickoff_at,
        )
        self._db.add(bet)
        await self._db.flush()
        await self._db.refresh(bet)

        # Step 3: Lock creator's stake — uses real bet.id as ledger reference_id
        await self._wallet_service.lock_stake(
            user_id=creator.id,
            amount=stake,
            bet_id=bet.id,
            notes=f"Stake locked at bet creation (bet_id={bet.id})",
        )

        # Step 4: Write CREATED audit event
        await self._write_bet_event(
            bet_id=bet.id,
            event_type=BetEventType.CREATED,
            actor_id=creator.id,
            actor_label="USER",
            payload={
                "match_id": str(request.match_id),
                "creator_prediction": request.creator_prediction.value,
                "stake_amount": str(stake),
                "expires_at": match.kickoff_at.isoformat(),
            },
        )

        logger.info(
            "Bet created: bet_id=%s creator_id=%s stake=%s",
            bet.id,
            creator.id,
            stake,
        )

        return BetResponse.model_validate(bet)

    # -----------------------------------------------------------------------
    # Accept Bet
    # -----------------------------------------------------------------------

    async def accept_bet(
        self,
        opponent: User,
        bet_id: uuid.UUID,
        request: AcceptBetRequest,
    ) -> BetResponse:
        """Accept an OPEN bet as User B.

        Uses SELECT FOR UPDATE on the bet row to prevent the concurrent
        acceptance race condition (spec Section 4.1 / 11.1).

        Transaction sequence:
          1. SELECT FOR UPDATE on bet row.
          2. Validate: status=OPEN, not expired, not self-bet, prediction differs.
          3. Lock opponent's stake via WalletService (SELECT FOR UPDATE on wallet).
          4. Update bet: status=MATCHED, opponent_id, opponent_prediction.
          5. Write MATCHED bet_event.

        Args:
            opponent: The authenticated user accepting the bet.
            bet_id: UUID of the bet to accept.
            request: Contains opponent_prediction.

        Returns:
            Updated BetResponse with status=MATCHED.
        """
        # Account status check
        if opponent.status.value != "active":
            raise AccountIneligibleError("Your account must be active to accept bets.")

        # Step 1: SELECT FOR UPDATE on bet row
        bet = await self._bet_repo.get_for_update(bet_id)

        # Step 2a: BR-02 — status must be OPEN
        if bet.status != BetStatus.OPEN:
            raise BetNotAvailableError(
                f"Bet is no longer available "
                f"(current status: '{bet.status.value}'). "
                "It may have already been accepted, cancelled, or expired."
            )

        # Step 2b: BR-03 — not expired
        now = datetime.now(tz=timezone.utc)
        if now >= bet.expires_at:
            raise BetExpiredError(
                "This bet has expired — the match kickoff time has passed."
            )

        # Step 2c: BR-01 — cannot accept own bet
        if opponent.id == bet.creator_id:
            raise SelfBetError("You cannot accept your own bet.")

        # Step 2d: BR-06/07 — prediction must differ
        if request.opponent_prediction == bet.creator_prediction:
            raise PredictionConflictError(
                f"Your prediction '{request.opponent_prediction.value}' is the same as "
                f"the creator's prediction '{bet.creator_prediction.value}'. "
                "You must choose one of the two remaining outcomes."
            )

        # Step 3: Lock opponent's stake (validates funds; SELECT FOR UPDATE on wallet)
        await self._wallet_service.lock_stake(
            user_id=opponent.id,
            amount=bet.stake_amount,
            bet_id=bet.id,
            notes=f"Stake locked at bet acceptance (bet_id={bet.id})",
        )

        # Step 4: Transition bet to MATCHED
        bet.opponent_id = opponent.id
        bet.opponent_prediction = request.opponent_prediction
        bet.status = BetStatus.MATCHED

        self._db.add(bet)
        await self._db.flush()
        await self._db.refresh(bet)

        # Step 5: Write MATCHED audit event
        await self._write_bet_event(
            bet_id=bet.id,
            event_type=BetEventType.MATCHED,
            actor_id=opponent.id,
            actor_label="USER",
            payload={
                "opponent_id": str(opponent.id),
                "opponent_prediction": request.opponent_prediction.value,
                "stake_amount": str(bet.stake_amount),
            },
        )

        logger.info(
            "Bet matched: bet_id=%s opponent_id=%s", bet.id, opponent.id
        )

        return BetResponse.model_validate(bet)

    # -----------------------------------------------------------------------
    # Cancel Bet
    # -----------------------------------------------------------------------

    async def cancel_bet(self, requester: User, bet_id: uuid.UUID) -> BetResponse:
        """Cancel an OPEN bet (creator only).

        Unlocks the creator's stake back to available_balance.

        Args:
            requester: The authenticated user requesting cancellation.
            bet_id: UUID of the bet to cancel.

        Returns:
            Updated BetResponse with status=CANCELLED.

        Raises:
            ForbiddenError: If the requester is not the creator.
            BetNotAvailableError: If the bet is not in OPEN status.
        """
        bet = await self._bet_repo.get_by_id_or_404(bet_id)

        # BR-13: Only the creator may cancel
        if bet.creator_id != requester.id:
            raise ForbiddenError(
                "Only the creator of a bet can cancel it."
            )

        # BR-13: Only while OPEN
        if bet.status != BetStatus.OPEN:
            raise BetNotAvailableError(
                f"Cannot cancel a bet in '{bet.status.value}' status. "
                "Only OPEN bets may be cancelled by the creator."
            )

        # Unlock creator's stake
        await self._wallet_service.unlock_stake(
            user_id=bet.creator_id,
            amount=bet.stake_amount,
            bet_id=bet.id,
            notes=f"Stake unlocked at cancellation (bet_id={bet.id})",
        )

        # Transition to CANCELLED
        bet.status = BetStatus.CANCELLED
        self._db.add(bet)
        await self._db.flush()
        await self._db.refresh(bet)

        # Write CANCELLED audit event
        await self._write_bet_event(
            bet_id=bet.id,
            event_type=BetEventType.CANCELLED,
            actor_id=requester.id,
            actor_label="USER",
            payload={"cancelled_by": str(requester.id)},
        )

        logger.info(
            "Bet cancelled: bet_id=%s by user_id=%s", bet.id, requester.id
        )

        return BetResponse.model_validate(bet)

    # -----------------------------------------------------------------------
    # List / Feed
    # -----------------------------------------------------------------------

    async def get_open_bets(self, params: PageParams) -> BetListResponse:
        """Return paginated OPEN bets that have not yet expired (public feed)."""
        bets, total = await self._bet_repo.get_open_bets(params)
        items = [BetResponse.model_validate(b) for b in bets]
        return BetListResponse.create(
            items=items,
            total=total,
            page=params.page,
            page_size=params.page_size,
        )

    async def get_user_bets(
        self, user_id: uuid.UUID, params: PageParams
    ) -> BetListResponse:
        """Return all bets for a user (as creator or opponent), newest first."""
        bets, total = await self._bet_repo.get_user_bets(user_id, params)
        items = [BetResponse.model_validate(b) for b in bets]
        return BetListResponse.create(
            items=items,
            total=total,
            page=params.page,
            page_size=params.page_size,
        )

    # -----------------------------------------------------------------------
    # Internal helpers
    # -----------------------------------------------------------------------

    async def _write_bet_event(
        self,
        bet_id: uuid.UUID,
        event_type: BetEventType,
        actor_id: uuid.UUID | None,
        actor_label: str,
        payload: dict | None = None,
    ) -> None:
        """Persist an immutable bet_events audit row."""
        event = BetEvent(
            bet_id=bet_id,
            event_type=event_type,
            actor_id=actor_id,
            actor_label=actor_label,
            payload=payload,
        )
        self._db.add(event)
        await self._db.flush()
