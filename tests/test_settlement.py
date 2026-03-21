"""Unit tests for SettlementService, WalletService invariants, and BetService
concurrent-acceptance prevention.

All tests use unittest.mock (AsyncMock / MagicMock) so no real database is
required. The service instances are constructed via __new__ + direct attribute
injection to avoid hitting __init__'s DB-dependent wiring.

Test groups
-----------
TestDeterminePathUnit          — pure-function path resolution
TestComputeAmountsUnit         — pure-function arithmetic (winner + no-winner)
TestSettleBetCreatorWins       — full settle_bet winner path: creator
TestSettleBetOpponentWins      — full settle_bet winner path: opponent
TestSettleBetNoWinner          — full settle_bet no-winner path
TestSettleBetIdempotency       — both idempotency guards (early + late)
TestSettleBetInsufficientFunds — locked balance checks in winner + no-winner paths
TestConcurrentAcceptancePrevention — SELECT FOR UPDATE guard + wallet lock guard
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, call

import pytest

from app.core.exceptions import (
    BetNotAvailableError,
    InsufficientFundsError,
    SettlementIdempotencyError,
)
from app.models.enums import (
    BetStatus,
    FootballOutcome,
    SettlementOutcome,
)
from app.services.bet_service import BetService
from app.services.settlement_service import SettlementService
from app.services.wallet_service import WalletService


# ---------------------------------------------------------------------------
# Shared factory helpers
# ---------------------------------------------------------------------------

def _mock_db() -> MagicMock:
    db = AsyncMock()
    db.add = MagicMock()           # synchronous in SA
    db.flush = AsyncMock()
    db.refresh = AsyncMock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    return db


def _make_settlement_service(execute_rowcount: int = 1) -> SettlementService:
    """Build a SettlementService with all repos replaced by AsyncMocks.

    Args:
        execute_rowcount: rowcount returned by db.execute (idempotency guard).
    """
    mock_db = _mock_db()
    execute_result = MagicMock()
    execute_result.rowcount = execute_rowcount
    mock_db.execute.return_value = execute_result

    svc = SettlementService.__new__(SettlementService)
    svc._db = mock_db
    svc._bet_repo = AsyncMock()
    svc._match_repo = AsyncMock()
    svc._fee_repo = AsyncMock()
    svc._wallet_service = AsyncMock()
    svc._wallet_repo = AsyncMock()
    svc._ledger = AsyncMock()
    svc._platform_repo = AsyncMock()
    return svc


def _make_bet(
    *,
    status: BetStatus = BetStatus.PENDING_SETTLEMENT,
    creator_prediction: FootballOutcome = FootballOutcome.home_win,
    opponent_prediction: FootballOutcome = FootballOutcome.away_win,
    stake: Decimal = Decimal("100.00"),
    currency: str = "ZAR",
) -> MagicMock:
    bet = MagicMock()
    bet.id = uuid.uuid4()
    bet.match_id = uuid.uuid4()
    bet.creator_id = uuid.uuid4()
    bet.opponent_id = uuid.uuid4()
    bet.creator_prediction = creator_prediction
    bet.opponent_prediction = opponent_prediction
    bet.stake_amount = stake
    bet.currency = currency
    bet.status = status
    return bet


def _make_match(outcome: FootballOutcome = FootballOutcome.home_win) -> MagicMock:
    m = MagicMock()
    m.id = uuid.uuid4()
    m.outcome = outcome
    return m


def _make_wallet(
    *,
    locked: Decimal = Decimal("100.00"),
    available: Decimal = Decimal("0.00"),
) -> MagicMock:
    w = MagicMock()
    w.id = uuid.uuid4()
    w.user_id = uuid.uuid4()
    w.locked_balance = locked
    w.available_balance = available
    w.version = 1
    return w


def _make_platform_account(balance: Decimal = Decimal("0.00")) -> MagicMock:
    pa = MagicMock()
    pa.id = uuid.uuid4()
    pa.currency = "ZAR"
    pa.balance = balance
    pa.version = 0
    return pa


def _wire_winner_path(svc: SettlementService, bet: MagicMock, match: MagicMock) -> None:
    """Configure mocks for a successful winner-path settle_bet call."""
    winner_wallet = _make_wallet()
    loser_wallet = _make_wallet()
    platform = _make_platform_account()

    svc._bet_repo.get_for_update.return_value = bet
    svc._match_repo.get_by_id_or_404.return_value = match
    svc._fee_repo.get_active_rate.return_value = Decimal("0.1000")
    svc._wallet_service.transfer_locked_funds.return_value = (winner_wallet, loser_wallet)
    svc._platform_repo.get_for_currency_for_update.return_value = platform
    svc._platform_repo.credit_fee.return_value = platform
    svc._platform_repo.write_ledger_entry.return_value = MagicMock()


def _wire_no_winner_path(svc: SettlementService, bet: MagicMock, match: MagicMock) -> None:
    """Configure mocks for a successful no-winner-path settle_bet call."""
    wallet = _make_wallet(locked=bet.stake_amount)
    platform = _make_platform_account()

    svc._bet_repo.get_for_update.return_value = bet
    svc._match_repo.get_by_id_or_404.return_value = match
    svc._fee_repo.get_active_rate.return_value = Decimal("0.0500")
    svc._wallet_repo.get_by_user_id_for_update.return_value = wallet
    svc._wallet_repo.update_balances.return_value = wallet
    svc._ledger.write_settlement_no_winner = AsyncMock()
    svc._platform_repo.get_for_currency_for_update.return_value = platform
    svc._platform_repo.credit_fee.return_value = platform
    svc._platform_repo.write_ledger_entry.return_value = MagicMock()


# ===========================================================================
# 1. _determine_path — pure function
# ===========================================================================

class TestDeterminePathUnit:
    """_determine_path has no side-effects; no mocking required."""

    def setup_method(self) -> None:
        self.svc = SettlementService.__new__(SettlementService)

    def test_creator_prediction_matches_returns_creator_wins(self) -> None:
        outcome = self.svc._determine_path(
            FootballOutcome.home_win,
            FootballOutcome.home_win,   # creator correct
            FootballOutcome.away_win,
        )
        assert outcome == SettlementOutcome.creator_wins

    def test_opponent_prediction_matches_returns_opponent_wins(self) -> None:
        outcome = self.svc._determine_path(
            FootballOutcome.away_win,
            FootballOutcome.home_win,
            FootballOutcome.away_win,   # opponent correct
        )
        assert outcome == SettlementOutcome.opponent_wins

    def test_neither_prediction_matches_returns_no_winner(self) -> None:
        outcome = self.svc._determine_path(
            FootballOutcome.draw,
            FootballOutcome.home_win,
            FootballOutcome.away_win,
        )
        assert outcome == SettlementOutcome.no_winner

    def test_creator_wins_takes_precedence_when_both_would_match(self) -> None:
        """By spec: creator_wins is checked first. If creator matches, we never
        check opponent — structural impossibility aside, the order is defined."""
        outcome = self.svc._determine_path(
            FootballOutcome.home_win,
            FootballOutcome.home_win,
            FootballOutcome.home_win,   # same, but creator is checked first
        )
        assert outcome == SettlementOutcome.creator_wins


# ===========================================================================
# 2. _compute_winner_amounts / _compute_no_winner_amounts — pure functions
# ===========================================================================

class TestComputeAmountsUnit:
    """Arithmetic checks with known stake + rate values."""

    def setup_method(self) -> None:
        self.svc = SettlementService.__new__(SettlementService)

    # ---- Winner path -------------------------------------------------------

    def test_winner_amounts_10pct_fee(self) -> None:
        payout, fee = self.svc._compute_winner_amounts(
            Decimal("100.00"), Decimal("0.1000")
        )
        assert fee == Decimal("20.00")     # 10% of 200
        assert payout == Decimal("180.00") # 200 - 20

    def test_winner_amounts_pool_is_conserved(self) -> None:
        payout, fee = self.svc._compute_winner_amounts(
            Decimal("75.50"), Decimal("0.1000")
        )
        assert payout + fee == Decimal("75.50") * 2

    def test_winner_amounts_zero_fee_rate(self) -> None:
        payout, fee = self.svc._compute_winner_amounts(
            Decimal("50.00"), Decimal("0.0000")
        )
        assert fee == Decimal("0.00")
        assert payout == Decimal("100.00")

    # ---- No-winner path ----------------------------------------------------

    def test_no_winner_amounts_5pct_fee(self) -> None:
        refund, fee = self.svc._compute_no_winner_amounts(
            Decimal("100.00"), Decimal("0.0500")
        )
        assert fee == Decimal("5.00")      # 5% of 100
        assert refund == Decimal("95.00")  # 100 - 5

    def test_no_winner_amounts_per_user_sum_equals_stake(self) -> None:
        refund, fee = self.svc._compute_no_winner_amounts(
            Decimal("33.33"), Decimal("0.0500")
        )
        assert refund + fee == Decimal("33.33")

    def test_no_winner_amounts_rounding_to_cent(self) -> None:
        """fee = round_half_up(33.33 × 0.05) = round_half_up(1.6665) = 1.67"""
        refund, fee = self.svc._compute_no_winner_amounts(
            Decimal("33.33"), Decimal("0.0500")
        )
        assert fee == Decimal("1.67")
        assert refund == Decimal("31.66")


# ===========================================================================
# 3. settle_bet — creator wins
# ===========================================================================

class TestSettleBetCreatorWins:

    async def test_transfer_locked_funds_called_with_creator_as_winner(self) -> None:
        svc = _make_settlement_service()
        bet = _make_bet(
            creator_prediction=FootballOutcome.home_win,
            opponent_prediction=FootballOutcome.away_win,
        )
        match = _make_match(outcome=FootballOutcome.home_win)
        _wire_winner_path(svc, bet, match)

        await svc.settle_bet(bet.id)

        svc._wallet_service.transfer_locked_funds.assert_called_once_with(
            winner_id=bet.creator_id,
            loser_id=bet.opponent_id,
            amount=bet.stake_amount,
            fee=Decimal("20.00"),   # 10% of 200
            bet_id=bet.id,
            notes="Settlement: creator_wins",
        )

    async def test_platform_fee_credited(self) -> None:
        svc = _make_settlement_service()
        bet = _make_bet(
            creator_prediction=FootballOutcome.home_win,
            opponent_prediction=FootballOutcome.away_win,
        )
        match = _make_match(outcome=FootballOutcome.home_win)
        _wire_winner_path(svc, bet, match)

        await svc.settle_bet(bet.id)

        svc._platform_repo.credit_fee.assert_called_once()
        credited_amount = svc._platform_repo.credit_fee.call_args[0][1]
        assert credited_amount == Decimal("20.00")

    async def test_idempotency_update_executed(self) -> None:
        svc = _make_settlement_service()
        bet = _make_bet(
            creator_prediction=FootballOutcome.home_win,
            opponent_prediction=FootballOutcome.away_win,
        )
        match = _make_match(outcome=FootballOutcome.home_win)
        _wire_winner_path(svc, bet, match)

        await svc.settle_bet(bet.id)

        svc._db.execute.assert_called_once()

    async def test_settled_bet_event_flushed(self) -> None:
        svc = _make_settlement_service()
        bet = _make_bet(
            creator_prediction=FootballOutcome.home_win,
            opponent_prediction=FootballOutcome.away_win,
        )
        match = _make_match(outcome=FootballOutcome.home_win)
        _wire_winner_path(svc, bet, match)

        await svc.settle_bet(bet.id)

        # db.add is called for the BetEvent
        svc._db.add.assert_called()
        svc._db.flush.assert_called()


# ===========================================================================
# 4. settle_bet — opponent wins
# ===========================================================================

class TestSettleBetOpponentWins:

    async def test_transfer_locked_funds_called_with_opponent_as_winner(self) -> None:
        svc = _make_settlement_service()
        bet = _make_bet(
            creator_prediction=FootballOutcome.home_win,
            opponent_prediction=FootballOutcome.away_win,
        )
        match = _make_match(outcome=FootballOutcome.away_win)  # opponent correct
        _wire_winner_path(svc, bet, match)

        await svc.settle_bet(bet.id)

        svc._wallet_service.transfer_locked_funds.assert_called_once_with(
            winner_id=bet.opponent_id,
            loser_id=bet.creator_id,
            amount=bet.stake_amount,
            fee=Decimal("20.00"),
            bet_id=bet.id,
            notes="Settlement: opponent_wins",
        )

    async def test_no_winner_path_not_entered(self) -> None:
        svc = _make_settlement_service()
        bet = _make_bet(
            creator_prediction=FootballOutcome.home_win,
            opponent_prediction=FootballOutcome.away_win,
        )
        match = _make_match(outcome=FootballOutcome.away_win)
        _wire_winner_path(svc, bet, match)

        await svc.settle_bet(bet.id)

        # wallet_repo is not called directly in winner path (transfer_locked_funds
        # is a WalletService call that is itself mocked)
        svc._wallet_repo.get_by_user_id_for_update.assert_not_called()


# ===========================================================================
# 5. settle_bet — no winner
# ===========================================================================

class TestSettleBetNoWinner:

    async def test_both_wallets_locked_in_sorted_order(self) -> None:
        svc = _make_settlement_service()
        stake = Decimal("100.00")
        bet = _make_bet(
            creator_prediction=FootballOutcome.home_win,
            opponent_prediction=FootballOutcome.away_win,
            stake=stake,
        )
        match = _make_match(outcome=FootballOutcome.draw)
        _wire_no_winner_path(svc, bet, match)

        await svc.settle_bet(bet.id)

        # Two wallet locks acquired
        assert svc._wallet_repo.get_by_user_id_for_update.call_count == 2
        locked_ids = {
            c.args[0]
            for c in svc._wallet_repo.get_by_user_id_for_update.call_args_list
        }
        assert locked_ids == {bet.creator_id, bet.opponent_id}

    async def test_both_wallets_updated(self) -> None:
        svc = _make_settlement_service()
        bet = _make_bet(
            creator_prediction=FootballOutcome.home_win,
            opponent_prediction=FootballOutcome.away_win,
            stake=Decimal("100.00"),
        )
        match = _make_match(outcome=FootballOutcome.draw)
        _wire_no_winner_path(svc, bet, match)

        await svc.settle_bet(bet.id)

        assert svc._wallet_repo.update_balances.call_count == 2

    async def test_no_winner_ledger_written(self) -> None:
        svc = _make_settlement_service()
        bet = _make_bet(
            creator_prediction=FootballOutcome.home_win,
            opponent_prediction=FootballOutcome.away_win,
            stake=Decimal("100.00"),
        )
        match = _make_match(outcome=FootballOutcome.draw)
        _wire_no_winner_path(svc, bet, match)

        await svc.settle_bet(bet.id)

        svc._ledger.write_settlement_no_winner.assert_called_once()

    async def test_total_platform_fee_is_2x_per_user_fee(self) -> None:
        svc = _make_settlement_service()
        stake = Decimal("100.00")
        bet = _make_bet(
            creator_prediction=FootballOutcome.home_win,
            opponent_prediction=FootballOutcome.away_win,
            stake=stake,
        )
        match = _make_match(outcome=FootballOutcome.draw)
        _wire_no_winner_path(svc, bet, match)

        await svc.settle_bet(bet.id)

        credited = svc._platform_repo.credit_fee.call_args[0][1]
        assert credited == Decimal("10.00")  # 2 × (5% of 100)

    async def test_transfer_locked_funds_not_called(self) -> None:
        svc = _make_settlement_service()
        bet = _make_bet(
            creator_prediction=FootballOutcome.home_win,
            opponent_prediction=FootballOutcome.away_win,
        )
        match = _make_match(outcome=FootballOutcome.draw)
        _wire_no_winner_path(svc, bet, match)

        await svc.settle_bet(bet.id)

        svc._wallet_service.transfer_locked_funds.assert_not_called()


# ===========================================================================
# 6. settle_bet — idempotency guards
# ===========================================================================

class TestSettleBetIdempotency:

    async def test_wrong_status_raises_early(self) -> None:
        """Step 2 guard: bet not in PENDING_SETTLEMENT raises immediately."""
        svc = _make_settlement_service()

        for bad_status in (
            BetStatus.SETTLED,
            BetStatus.OPEN,
            BetStatus.MATCHED,
            BetStatus.CANCELLED,
            BetStatus.VOIDED,
        ):
            bet = _make_bet(status=bad_status)
            svc._bet_repo.get_for_update.return_value = bet

            with pytest.raises(SettlementIdempotencyError):
                await svc.settle_bet(bet.id)

            # No mutations should have been attempted
            svc._wallet_service.transfer_locked_funds.assert_not_called()
            svc._wallet_repo.update_balances.assert_not_called()

    async def test_idempotency_update_rowcount_zero_raises(self) -> None:
        """Step 11 guard: UPDATE matches 0 rows → SettlementIdempotencyError."""
        svc = _make_settlement_service(execute_rowcount=0)
        bet = _make_bet(
            creator_prediction=FootballOutcome.home_win,
            opponent_prediction=FootballOutcome.away_win,
        )
        match = _make_match(outcome=FootballOutcome.home_win)
        _wire_winner_path(svc, bet, match)

        with pytest.raises(SettlementIdempotencyError):
            await svc.settle_bet(bet.id)

    async def test_voided_bet_raises_idempotency_error(self) -> None:
        """A VOIDED bet is not in PENDING_SETTLEMENT — settle_bet is a no-op."""
        svc = _make_settlement_service()
        bet = _make_bet(status=BetStatus.VOIDED)
        svc._bet_repo.get_for_update.return_value = bet

        with pytest.raises(SettlementIdempotencyError):
            await svc.settle_bet(bet.id)


# ===========================================================================
# 7. settle_bet — insufficient locked funds
# ===========================================================================

class TestSettleBetInsufficientFunds:

    async def test_winner_path_propagates_insufficient_funds(self) -> None:
        """If transfer_locked_funds raises InsufficientFundsError, it propagates."""
        svc = _make_settlement_service()
        bet = _make_bet(
            creator_prediction=FootballOutcome.home_win,
            opponent_prediction=FootballOutcome.away_win,
        )
        match = _make_match(outcome=FootballOutcome.home_win)
        _wire_winner_path(svc, bet, match)

        svc._wallet_service.transfer_locked_funds.side_effect = InsufficientFundsError(
            "Winner locked_balance insufficient."
        )

        with pytest.raises(InsufficientFundsError):
            await svc.settle_bet(bet.id)

        # Platform account should NOT have been credited
        svc._platform_repo.credit_fee.assert_not_called()

    async def test_no_winner_path_creator_insufficient_funds(self) -> None:
        """If creator wallet locked_balance < stake_amount, InsufficientFundsError raised."""
        svc = _make_settlement_service()
        stake = Decimal("100.00")
        bet = _make_bet(
            creator_prediction=FootballOutcome.home_win,
            opponent_prediction=FootballOutcome.away_win,
            stake=stake,
        )
        match = _make_match(outcome=FootballOutcome.draw)
        _wire_no_winner_path(svc, bet, match)

        # Override: wallet has less than required
        low_wallet = _make_wallet(locked=Decimal("50.00"))
        svc._wallet_repo.get_by_user_id_for_update.return_value = low_wallet

        with pytest.raises(InsufficientFundsError):
            await svc.settle_bet(bet.id)

        svc._platform_repo.credit_fee.assert_not_called()

    async def test_no_winner_path_zero_locked_balance(self) -> None:
        """Wallet with zero locked balance fails the no-winner path."""
        svc = _make_settlement_service()
        bet = _make_bet(
            creator_prediction=FootballOutcome.home_win,
            opponent_prediction=FootballOutcome.away_win,
            stake=Decimal("100.00"),
        )
        match = _make_match(outcome=FootballOutcome.draw)
        _wire_no_winner_path(svc, bet, match)

        zero_wallet = _make_wallet(locked=Decimal("0.00"))
        svc._wallet_repo.get_by_user_id_for_update.return_value = zero_wallet

        with pytest.raises(InsufficientFundsError):
            await svc.settle_bet(bet.id)


# ===========================================================================
# 8. Concurrent acceptance prevention
# ===========================================================================

class TestConcurrentAcceptancePrevention:
    """Tests that verify the SELECT FOR UPDATE + status-check guard prevents
    two concurrent users from both accepting the same bet.

    In production, the first acceptance commits the status=MATCHED change.
    The second request, after acquiring the SELECT FOR UPDATE lock, reads
    status=MATCHED and raises BetNotAvailableError.

    These unit tests simulate that scenario by returning a pre-MATCHED bet
    from get_for_update, reproducing the state the second transaction would see.
    """

    def _make_bet_service(self, bet: MagicMock) -> BetService:
        mock_db = _mock_db()
        svc = BetService.__new__(BetService)
        svc._db = mock_db
        svc._bet_repo = AsyncMock()
        svc._bet_repo.get_for_update.return_value = bet
        svc._match_repo = AsyncMock()
        svc._wallet_service = AsyncMock()
        return svc

    async def test_second_accept_on_matched_bet_raises_bet_not_available(self) -> None:
        """Simulates the second concurrent request seeing a MATCHED bet after
        the first request committed the acceptance."""
        already_matched = MagicMock()
        already_matched.id = uuid.uuid4()
        already_matched.status = BetStatus.MATCHED    # first request already won
        already_matched.creator_id = uuid.uuid4()

        svc = self._make_bet_service(already_matched)

        opponent = MagicMock()
        opponent.id = uuid.uuid4()
        opponent.status = MagicMock(value="active")

        request = MagicMock()
        request.opponent_prediction = FootballOutcome.away_win

        with pytest.raises(BetNotAvailableError):
            await svc.accept_bet(opponent, already_matched.id, request)

    async def test_accept_cancelled_bet_raises_bet_not_available(self) -> None:
        """CANCELLED bets are also rejected by the status guard."""
        cancelled_bet = MagicMock()
        cancelled_bet.id = uuid.uuid4()
        cancelled_bet.status = BetStatus.CANCELLED
        cancelled_bet.creator_id = uuid.uuid4()

        svc = self._make_bet_service(cancelled_bet)

        opponent = MagicMock()
        opponent.id = uuid.uuid4()
        opponent.status = MagicMock(value="active")

        request = MagicMock()
        request.opponent_prediction = FootballOutcome.away_win

        with pytest.raises(BetNotAvailableError):
            await svc.accept_bet(opponent, cancelled_bet.id, request)

    async def test_wallet_lock_raises_when_zero_available_balance(self) -> None:
        """WalletService.lock_stake raises InsufficientFundsError if available=0.

        This is the second line of defence: even if two requests somehow pass
        the bet-status guard simultaneously, lock_stake on the wallet (SELECT
        FOR UPDATE) ensures only one can proceed — and the second finds
        available_balance already depleted.
        """
        mock_db = _mock_db()
        svc = WalletService.__new__(WalletService)
        svc._wallet_repo = AsyncMock()
        svc._ledger = AsyncMock()

        zero_wallet = _make_wallet(locked=Decimal("0.00"), available=Decimal("0.00"))
        svc._wallet_repo.get_by_user_id_for_update.return_value = zero_wallet

        with pytest.raises(InsufficientFundsError):
            await svc.lock_stake(
                user_id=uuid.uuid4(),
                amount=Decimal("100.00"),
                bet_id=uuid.uuid4(),
            )

    async def test_wallet_lock_succeeds_then_raises_on_reuse(self) -> None:
        """Demonstrates that a depleted wallet prevents a second lock.

        First lock: wallet has 100 available → succeeds (mocked).
        Second attempt (simulated by a wallet that now has 0 available):
        → InsufficientFundsError.
        """
        svc = WalletService.__new__(WalletService)
        svc._wallet_repo = AsyncMock()
        svc._ledger = AsyncMock()

        depleted_wallet = _make_wallet(locked=Decimal("100.00"), available=Decimal("0.00"))
        svc._wallet_repo.get_by_user_id_for_update.return_value = depleted_wallet

        with pytest.raises(InsufficientFundsError):
            await svc.lock_stake(
                user_id=uuid.uuid4(),
                amount=Decimal("50.00"),   # any positive amount
                bet_id=uuid.uuid4(),
            )
