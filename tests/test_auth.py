"""Placeholder tests for authentication endpoints.

POST /api/v1/auth/register
POST /api/v1/auth/login
"""

from __future__ import annotations

import pytest


class TestRegister:
    """POST /auth/register"""

    @pytest.mark.skip(reason="Requires test database — not yet wired up")
    async def test_register_returns_jwt(self) -> None:
        """A valid registration payload returns a 201 with an access token."""
        ...

    @pytest.mark.skip(reason="Requires test database — not yet wired up")
    async def test_register_duplicate_email_returns_409(self) -> None:
        """Registering with an already-used email returns 409 Conflict."""
        ...

    @pytest.mark.skip(reason="Requires test database — not yet wired up")
    async def test_register_creates_zero_balance_wallet(self) -> None:
        """A newly registered user has available_balance = 0 and locked_balance = 0."""
        ...

    def test_register_schema_rejects_short_password(self) -> None:
        """RegisterRequest Pydantic schema rejects passwords shorter than 8 chars."""
        from app.schemas.auth import RegisterRequest
        import pytest

        with pytest.raises(Exception):
            RegisterRequest(
                email="user@example.com",
                display_name="Test User",
                password="short",
            )

    def test_register_schema_rejects_blank_display_name(self) -> None:
        """RegisterRequest Pydantic schema rejects an empty display_name."""
        from app.schemas.auth import RegisterRequest
        import pytest

        with pytest.raises(Exception):
            RegisterRequest(
                email="user@example.com",
                display_name="",
                password="strongpassword",
            )


class TestLogin:
    """POST /auth/login"""

    @pytest.mark.skip(reason="Requires test database — not yet wired up")
    async def test_login_valid_credentials_returns_jwt(self) -> None:
        """Valid email + password returns 200 with access_token."""
        ...

    @pytest.mark.skip(reason="Requires test database — not yet wired up")
    async def test_login_wrong_password_returns_401(self) -> None:
        """Incorrect password returns 401 Unauthorized (intentionally vague message)."""
        ...

    @pytest.mark.skip(reason="Requires test database — not yet wired up")
    async def test_login_unknown_email_returns_401(self) -> None:
        """Unknown email returns 401 (same message as wrong password — no enumeration)."""
        ...
