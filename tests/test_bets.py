"""Placeholder tests for bet endpoints and BetService business rules.

GET  /api/v1/bets/open
GET  /api/v1/bets/my
POST /api/v1/bets
POST /api/v1/bets/{id}/accept
POST /api/v1/bets/{id}/cancel
"""

from __future__ import annotations

import pytest


class TestCreateBet:
    """POST /bets"""

    @pytest.mark.skip(reason="Requires test database — not yet wired up")
    async def test_create_bet_locks_creator_stake(self) -> None:
        """Creating a bet moves stake_amount from available to locked on the creator's wallet."""
        ...

    @pytest.mark.skip(reason="Requires test database — not yet wired up")
    async def test_create_bet_below_minimum_returns_422(self) -> None:
        """stake_amount below MIN_STAKE_AMOUNT is rejected with 422."""
        ...

    @pytest.mark.skip(reason="Requires test database — not yet wired up")
    async def test_create_bet_above_maximum_returns_422(self) -> None:
        """stake_amount above MAX_STAKE_AMOUNT is rejected with 422."""
        ...

    @pytest.mark.skip(reason="Requires test database — not yet wired up")
    async def test_create_bet_on_non_scheduled_match_returns_422(self) -> None:
        """Bet creation on a non-scheduled match is rejected."""
        ...

    @pytest.mark.skip(reason="Requires test database — not yet wired up")
    async def test_create_bet_within_cutoff_window_returns_422(self) -> None:
        """Bet creation is blocked within BET_CREATION_CUTOFF_MINUTES of kickoff."""
        ...

    @pytest.mark.skip(reason="Requires test database — not yet wired up")
    async def test_create_bet_insufficient_funds_returns_422(self) -> None:
        """Creating a bet with more than available_balance raises InsufficientFundsError."""
        ...


class TestAcceptBet:
    """POST /bets/{id}/accept"""

    @pytest.mark.skip(reason="Requires test database — not yet wired up")
    async def test_accept_bet_transitions_to_matched(self) -> None:
        """Accepting an OPEN bet sets status to MATCHED and records opponent_id."""
        ...

    @pytest.mark.skip(reason="Requires test database — not yet wired up")
    async def test_accept_own_bet_returns_422(self) -> None:
        """BR-01: A user cannot accept their own bet."""
        ...

    @pytest.mark.skip(reason="Requires test database — not yet wired up")
    async def test_accept_bet_same_prediction_returns_422(self) -> None:
        """BR-06/07: opponent_prediction must differ from creator_prediction."""
        ...

    @pytest.mark.skip(reason="Requires test database — not yet wired up")
    async def test_accept_already_matched_bet_returns_409(self) -> None:
        """BR-02: A MATCHED bet cannot be accepted again."""
        ...

    @pytest.mark.skip(reason="Requires test database — not yet wired up")
    async def test_accept_expired_bet_returns_409(self) -> None:
        """BR-03: Accepting a bet after kickoff returns 409 BetExpiredError."""
        ...

    @pytest.mark.skip(reason="Requires test database — not yet wired up")
    async def test_accept_bet_locks_opponent_stake(self) -> None:
        """Accepting a bet locks the opponent's stake equal to the creator's stake."""
        ...


class TestCancelBet:
    """POST /bets/{id}/cancel"""

    @pytest.mark.skip(reason="Requires test database — not yet wired up")
    async def test_cancel_bet_unlocks_creator_stake(self) -> None:
        """Cancelling an OPEN bet moves stake from locked back to available."""
        ...

    @pytest.mark.skip(reason="Requires test database — not yet wired up")
    async def test_cancel_bet_by_non_creator_returns_403(self) -> None:
        """BR-13: Only the creator may cancel their own bet."""
        ...

    @pytest.mark.skip(reason="Requires test database — not yet wired up")
    async def test_cancel_matched_bet_returns_409(self) -> None:
        """BR-13: Only OPEN bets may be cancelled."""
        ...


class TestListBets:
    """GET /bets/open and GET /bets/my"""

    @pytest.mark.skip(reason="Requires test database — not yet wired up")
    async def test_open_bets_excludes_expired(self) -> None:
        """GET /bets/open only returns bets where expires_at > now."""
        ...

    @pytest.mark.skip(reason="Requires test database — not yet wired up")
    async def test_my_bets_includes_all_statuses(self) -> None:
        """GET /bets/my returns the user's bets across all statuses."""
        ...

    @pytest.mark.skip(reason="Requires test database — not yet wired up")
    async def test_my_bets_includes_as_opponent(self) -> None:
        """GET /bets/my includes bets where the user is the opponent."""
        ...
