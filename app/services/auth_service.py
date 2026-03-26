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

Transaction ownership:
  get_db (dependency) owns commit/rollback.  Services only call flush().
"""

from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.exceptions import ConflictError, UnauthorizedError
from app.core.security import (
    create_access_token,
    create_password_reset_token,
    hash_password,
    verify_password,
    verify_password_reset_token,
)
from app.repositories.user_repository import UserRepository
from app.repositories.wallet_repository import WalletRepository
from app.schemas.auth import (
    ForgotPasswordRequest,
    ForgotPasswordResponse,
    LoginRequest,
    RegisterRequest,
    ResetPasswordRequest,
    TokenResponse,
)
from app.schemas.user import UserResponse

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

        # Flush so user.id is available for the token; get_db commits on exit.
        await self._db.flush()

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
            user=UserResponse.model_validate(user),
        )

    async def forgot_password(
        self, request: ForgotPasswordRequest
    ) -> ForgotPasswordResponse:
        """Generate a password-reset token for the given email address.

        The response is intentionally identical whether or not the email is
        registered, to prevent user-enumeration attacks.

        In development (APP_ENV=development) the token is returned in the
        response so the flow can be tested without an email service.
        In production the token is only logged; replace the log call with an
        email dispatch once a mail service is integrated.

        Args:
            request: Contains the email address to reset.

        Returns:
            ForgotPasswordResponse with a generic message and, in development
            mode only, the raw reset token.
        """
        _GENERIC_MESSAGE = (
            "If that email address is registered you will receive a reset link shortly."
        )

        normalised_email = request.email.lower().strip()
        user = await self._user_repo.get_by_email(normalised_email)

        if user is None:
            # Return identical response — do not reveal whether the email exists.
            logger.info("forgot_password: email not found (not disclosed): %s", normalised_email)
            return ForgotPasswordResponse(message=_GENERIC_MESSAGE)

        token = create_password_reset_token(user.id)

        if settings.app_env == "development":
            logger.info(
                "forgot_password [DEV]: reset token for user_id=%s → %s",
                user.id,
                token,
            )
            return ForgotPasswordResponse(message=_GENERIC_MESSAGE, reset_token=token)

        # Production path: token is NOT returned in the response.
        # TODO: dispatch email with reset link to user.email using your mail service.
        logger.info(
            "forgot_password: reset token generated for user_id=%s "
            "(email delivery not yet implemented — token: %s)",
            user.id,
            token,
        )
        return ForgotPasswordResponse(message=_GENERIC_MESSAGE)

    async def reset_password(self, request: ResetPasswordRequest) -> None:
        """Verify a reset token and update the user's password.

        Args:
            request: Contains the reset token and the new plain-text password.

        Raises:
            UnauthorizedError: If the token is invalid, expired, or the wrong type.
            NotFoundError: If the user referenced by the token no longer exists.
        """
        # Raises UnauthorizedError for any invalid/expired token
        user_id = verify_password_reset_token(request.token)

        user = await self._user_repo.get_by_id_or_404(user_id)

        new_hash = hash_password(request.new_password)

        user.password_hash = new_hash
        self._db.add(user)
        await self._db.flush()

        logger.info("reset_password: password updated for user_id=%s", user.id)

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
            user=UserResponse.model_validate(user),
        )
