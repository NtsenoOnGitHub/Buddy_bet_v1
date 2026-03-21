"""Integration + unit tests for authentication endpoints.

POST /api/v1/auth/register
POST /api/v1/auth/login
GET  /api/v1/auth/me
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from tests.conftest import register_user


class TestRegister:
    """POST /auth/register"""

    async def test_register_returns_201_with_token(
        self, client: AsyncClient
    ) -> None:
        """A valid registration payload returns 201 with an access_token."""
        resp = await client.post(
            "/api/v1/auth/register",
            json={
                "email": "newuser@example.com",
                "password": "strongpass1",
                "display_name": "New User",
            },
        )
        assert resp.status_code == 201
        data = resp.json()
        assert "access_token" in data
        assert data["token_type"] == "bearer"
        assert "expires_in" in data

    async def test_register_response_includes_user_profile(
        self, client: AsyncClient
    ) -> None:
        """Register response embeds the user object so the frontend can bootstrap immediately."""
        resp = await client.post(
            "/api/v1/auth/register",
            json={
                "email": "profile_check@example.com",
                "password": "strongpass1",
                "display_name": "Profile User",
            },
        )
        assert resp.status_code == 201
        data = resp.json()
        assert "user" in data
        user = data["user"]
        assert user["email"] == "profile_check@example.com"
        assert user["display_name"] == "Profile User"
        assert user["role"] == "user"
        assert user["status"] == "active"
        assert "id" in user

    async def test_register_creates_zero_balance_wallet(
        self, client: AsyncClient
    ) -> None:
        """A newly registered user has available_balance = 0 and locked_balance = 0."""
        _uid, token = await register_user(
            client, email="wallet_check@example.com", display_name="Wallet User"
        )
        resp = await client.get(
            "/api/v1/wallet",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["available_balance"] == "0.00"
        assert data["locked_balance"] == "0.00"
        assert data["total_balance"] == "0.00"

    async def test_register_duplicate_email_returns_409(
        self, client: AsyncClient
    ) -> None:
        """Registering with an already-used email returns 409 Conflict."""
        payload = {
            "email": "duplicate@example.com",
            "password": "strongpass1",
            "display_name": "Dup User",
        }
        resp1 = await client.post("/api/v1/auth/register", json=payload)
        assert resp1.status_code == 201

        resp2 = await client.post("/api/v1/auth/register", json=payload)
        assert resp2.status_code == 409

    def test_register_schema_rejects_short_password(self) -> None:
        """RegisterRequest Pydantic schema rejects passwords shorter than 8 chars."""
        from app.schemas.auth import RegisterRequest

        with pytest.raises(Exception):
            RegisterRequest(
                email="user@example.com",
                display_name="Test User",
                password="short",
            )

    def test_register_schema_rejects_blank_display_name(self) -> None:
        """RegisterRequest Pydantic schema rejects an empty display_name."""
        from app.schemas.auth import RegisterRequest

        with pytest.raises(Exception):
            RegisterRequest(
                email="user@example.com",
                display_name="",
                password="strongpassword",
            )


class TestLogin:
    """POST /auth/login"""

    async def test_login_valid_credentials_returns_jwt(
        self, client: AsyncClient
    ) -> None:
        """Valid email + password returns 200 with access_token and user profile."""
        email, password = "login_ok@example.com", "goodpassword"
        await register_user(client, email=email, password=password)

        resp = await client.post(
            "/api/v1/auth/login",
            json={"email": email, "password": password},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "access_token" in data
        assert data["token_type"] == "bearer"
        assert "user" in data
        assert data["user"]["email"] == email

    async def test_login_wrong_password_returns_401(
        self, client: AsyncClient
    ) -> None:
        """Incorrect password returns 401 Unauthorized."""
        email = "wrong_pw@example.com"
        await register_user(client, email=email, password="correctpassword")

        resp = await client.post(
            "/api/v1/auth/login",
            json={"email": email, "password": "wrongpassword"},
        )
        assert resp.status_code == 401

    async def test_login_unknown_email_returns_401(
        self, client: AsyncClient
    ) -> None:
        """Unknown email returns 401 (same message — no email enumeration)."""
        resp = await client.post(
            "/api/v1/auth/login",
            json={"email": "nobody@example.com", "password": "irrelevant123"},
        )
        assert resp.status_code == 401


class TestGetMe:
    """GET /auth/me"""

    async def test_get_me_returns_current_user(
        self, client: AsyncClient
    ) -> None:
        """Authenticated GET /auth/me returns the current user's profile."""
        uid, token = await register_user(
            client, email="me_user@example.com", display_name="Me User"
        )
        resp = await client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == str(uid)
        assert data["email"] == "me_user@example.com"
        assert data["display_name"] == "Me User"
        assert data["role"] == "user"
        assert data["status"] == "active"

    async def test_get_me_unauthenticated_returns_401(
        self, client: AsyncClient
    ) -> None:
        """GET /auth/me without a token returns 401."""
        resp = await client.get("/api/v1/auth/me")
        assert resp.status_code == 401
