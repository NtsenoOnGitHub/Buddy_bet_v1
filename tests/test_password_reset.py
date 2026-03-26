"""Integration tests for password reset flow.

POST /api/v1/auth/forgot-password
POST /api/v1/auth/reset-password
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from tests.conftest import register_user


class TestForgotPassword:
    """POST /auth/forgot-password"""

    async def test_forgot_password_returns_200_for_registered_email(
        self, client: AsyncClient
    ) -> None:
        """forgot-password always returns 200 regardless of whether email exists."""
        await register_user(client, email="reset_user@example.com")

        resp = await client.post(
            "/api/v1/auth/forgot-password",
            json={"email": "reset_user@example.com"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "message" in data

    async def test_forgot_password_returns_200_for_unknown_email(
        self, client: AsyncClient
    ) -> None:
        """Anti-enumeration: unknown email returns the same 200 response."""
        resp = await client.post(
            "/api/v1/auth/forgot-password",
            json={"email": "nobody_exists@example.com"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "message" in data
        # reset_token must NOT be present for unknown email
        assert data.get("reset_token") is None

    async def test_forgot_password_dev_mode_returns_reset_token(
        self, client: AsyncClient
    ) -> None:
        """In development mode the API returns the raw reset token."""
        await register_user(client, email="dev_token@example.com")

        resp = await client.post(
            "/api/v1/auth/forgot-password",
            json={"email": "dev_token@example.com"},
        )
        assert resp.status_code == 200
        data = resp.json()
        # In dev mode (APP_ENV=development) the token is present
        assert "reset_token" in data
        assert data["reset_token"] is not None
        assert len(data["reset_token"]) > 10  # non-trivial JWT

    async def test_forgot_password_invalid_email_format_returns_422(
        self, client: AsyncClient
    ) -> None:
        """A malformed email address is rejected at the schema level."""
        resp = await client.post(
            "/api/v1/auth/forgot-password",
            json={"email": "not-an-email"},
        )
        assert resp.status_code == 422


class TestResetPassword:
    """POST /auth/reset-password"""

    async def _get_reset_token(self, client: AsyncClient, email: str) -> str:
        """Register user, request reset, return the dev-mode token."""
        await register_user(client, email=email)
        resp = await client.post(
            "/api/v1/auth/forgot-password",
            json={"email": email},
        )
        return resp.json()["reset_token"]

    async def test_reset_password_with_valid_token_succeeds(
        self, client: AsyncClient
    ) -> None:
        """A valid reset token allows the password to be changed."""
        token = await self._get_reset_token(client, "rp_ok@example.com")

        resp = await client.post(
            "/api/v1/auth/reset-password",
            json={"token": token, "new_password": "NewPassword99!"},
        )
        assert resp.status_code == 204

    async def test_reset_password_then_login_with_new_password_works(
        self, client: AsyncClient
    ) -> None:
        """After a successful reset, the user can log in with the new password."""
        email = "rp_login_new@example.com"
        old_password = "OldPassword123"
        new_password = "BrandNewPass99!"

        await register_user(client, email=email, password=old_password)
        token = (
            await client.post(
                "/api/v1/auth/forgot-password",
                json={"email": email},
            )
        ).json()["reset_token"]

        # Reset the password
        reset_resp = await client.post(
            "/api/v1/auth/reset-password",
            json={"token": token, "new_password": new_password},
        )
        assert reset_resp.status_code == 204

        # New password works
        login_resp = await client.post(
            "/api/v1/auth/login",
            json={"email": email, "password": new_password},
        )
        assert login_resp.status_code == 200, login_resp.text
        assert "access_token" in login_resp.json()

    async def test_reset_password_old_password_no_longer_works(
        self, client: AsyncClient
    ) -> None:
        """After reset, the old password is rejected."""
        email = "rp_old_invalid@example.com"
        old_password = "OldPass123!"
        new_password = "FreshNew456!"

        await register_user(client, email=email, password=old_password)
        token = (
            await client.post(
                "/api/v1/auth/forgot-password",
                json={"email": email},
            )
        ).json()["reset_token"]

        await client.post(
            "/api/v1/auth/reset-password",
            json={"token": token, "new_password": new_password},
        )

        old_login = await client.post(
            "/api/v1/auth/login",
            json={"email": email, "password": old_password},
        )
        assert old_login.status_code == 401

    async def test_reset_password_invalid_token_returns_401(
        self, client: AsyncClient
    ) -> None:
        """A garbage token is rejected with 401."""
        resp = await client.post(
            "/api/v1/auth/reset-password",
            json={"token": "not.a.real.token", "new_password": "NewPass123!"},
        )
        assert resp.status_code == 401

    async def test_reset_password_access_token_rejected(
        self, client: AsyncClient
    ) -> None:
        """An access token (wrong type claim) must be rejected as a reset token."""
        _, access_token = await register_user(client, email="rp_type@example.com")

        resp = await client.post(
            "/api/v1/auth/reset-password",
            json={"token": access_token, "new_password": "ShouldFail99!"},
        )
        assert resp.status_code == 401

    async def test_reset_password_short_password_returns_422(
        self, client: AsyncClient
    ) -> None:
        """The new password must meet the minimum-length requirement."""
        token = await self._get_reset_token(client, "rp_short@example.com")

        resp = await client.post(
            "/api/v1/auth/reset-password",
            json={"token": token, "new_password": "short"},
        )
        assert resp.status_code == 422

    async def test_reset_password_missing_token_returns_422(
        self, client: AsyncClient
    ) -> None:
        """Omitting the token field is rejected at schema level."""
        resp = await client.post(
            "/api/v1/auth/reset-password",
            json={"new_password": "SomeNewPass99!"},
        )
        assert resp.status_code == 422
