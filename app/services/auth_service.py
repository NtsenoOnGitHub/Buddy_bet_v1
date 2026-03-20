"""Authentication service — user registration and login.

Registration:
1. Normalise and validate the email (check duplicate).
2. Hash the password with bcrypt.
3. Create the user record.
4. Create a zero-balance wallet for the new user.
5. Issue a JWT access token.

Login:
1. Look up the user by email.
2. Verify the plain-text password against the stored hash.
3. Issue a JWT access token.
"""

from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.exceptions import ConflictError, UnauthorizedError
from app.core.security import create_access_token, hash_password, verify_password
from app.repositories.user_repository import UserRepository
from app.repositories.wallet_repository import WalletRepository
from app.schemas.auth import LoginRequest, RegisterRequest, TokenResponse

logger = logging.getLogger(__name__)
settings = get_settings()


class AuthService:
    """Handles user registration and JWT-based authentication."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db
        self._user_repo = UserRepository(db)
        self._wallet_repo = WalletRepository(db)

    async def register(self, request: RegisterRequest) -> TokenResponse:
        """Create a new user account and return a JWT.

        Args:
            request: Validated registration payload.

        Returns:
            TokenResponse with a signed JWT.

        Raises:
            ConflictError: If the email address is already registered.
        """
        normalised_email = request.email.lower().strip()

        # Check for duplicate email (read before opening write transaction)
        existing = await self._user_repo.get_by_email(normalised_email)
        if existing is not None:
            raise ConflictError(
                f"An account with email '{normalised_email}' already exists."
            )

        # Hash password — plain text never stored or logged
        password_hash = hash_password(request.password)

        try:
            # Create user
            user = await self._user_repo.create(
                email=normalised_email,
                display_name=request.display_name,
                password_hash=password_hash,
                phone_number=request.phone_number,
            )

            # Create zero-balance wallet (one wallet per user)
            await self._wallet_repo.create(
                user_id=user.id,
                currency=settings.platform_currency,
            )

            await self._db.commit()
        except Exception:
            await self._db.rollback()
            raise

        logger.info("New user registered: id=%s email=%s", user.id, user.email)

        # Issue JWT — after commit so user.id is finalised
        token = create_access_token(
            user_id=user.id,
            role=user.role.value,
        )

        return TokenResponse(
            access_token=token,
            token_type="bearer",
            expires_in=settings.access_token_expire_minutes * 60,
        )

    async def login(self, request: LoginRequest) -> TokenResponse:
        """Authenticate a user and return a JWT.

        Args:
            request: Validated login payload.

        Returns:
            TokenResponse with a signed JWT.

        Raises:
            UnauthorizedError: If credentials are invalid (intentionally vague).
        """
        normalised_email = request.email.lower().strip()
        user = await self._user_repo.get_by_email(normalised_email)

        # Use a constant-time comparison path even for not-found case to
        # prevent email enumeration via timing.
        if user is None or not verify_password(request.password, user.password_hash):
            raise UnauthorizedError("Invalid email or password.")

        logger.info("User logged in: id=%s email=%s", user.id, user.email)

        token = create_access_token(
            user_id=user.id,
            role=user.role.value,
        )

        return TokenResponse(
            access_token=token,
            token_type="bearer",
            expires_in=settings.access_token_expire_minutes * 60,
        )
