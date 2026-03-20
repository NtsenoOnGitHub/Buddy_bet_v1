"""Placeholder tests for wallet endpoints.

GET /api/v1/wallet
GET /api/v1/wallet/transactions
"""

from __future__ import annotations

import pytest


class TestGetWallet:
    """GET /wallet"""

    @pytest.mark.skip(reason="Requires test database — not yet wired up")
    async def test_get_wallet_returns_balances(self) -> None:
        """Authenticated user receives their wallet with available and locked balances."""
        ...

    @pytest.mark.skip(reason="Requires test database — not yet wired up")
    async def test_get_wallet_unauthenticated_returns_401(self) -> None:
        """Request without a Bearer token returns 401."""
        ...

    @pytest.mark.skip(reason="Requires test database — not yet wired up")
    async def test_get_wallet_total_balance_is_sum(self) -> None:
        """total_balance in the response equals available_balance + locked_balance."""
        ...


class TestGetTransactions:
    """GET /wallet/transactions"""

    @pytest.mark.skip(reason="Requires test database — not yet wired up")
    async def test_transactions_returns_paginated_response(self) -> None:
        """Response shape includes items, total, page, page_size, pages."""
        ...

    @pytest.mark.skip(reason="Requires test database — not yet wired up")
    async def test_transactions_newest_first(self) -> None:
        """Ledger entries are returned in descending created_at order."""
        ...


class TestWalletService:
    """Unit tests for WalletService balance mutations (no HTTP layer)."""

    @pytest.mark.skip(reason="Requires test database — not yet wired up")
    async def test_lock_stake_moves_available_to_locked(self) -> None:
        """lock_stake reduces available_balance and increases locked_balance by the same amount."""
        ...

    @pytest.mark.skip(reason="Requires test database — not yet wired up")
    async def test_lock_stake_raises_when_insufficient_funds(self) -> None:
        """lock_stake raises InsufficientFundsError when available_balance < amount."""
        from app.core.exceptions import InsufficientFundsError
        ...

    @pytest.mark.skip(reason="Requires test database — not yet wired up")
    async def test_unlock_stake_moves_locked_to_available(self) -> None:
        """unlock_stake reduces locked_balance and increases available_balance."""
        ...
