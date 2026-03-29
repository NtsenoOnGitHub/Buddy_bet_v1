"""Security utilities — JWT creation/verification and password hashing.

JWT payload schema:
    {
        "sub": "<user_id as string>",
        "role": "<user_role>",
        "exp": <unix timestamp>
    }
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from jose import JWTError, jwt
from passlib.context import CryptContext

from app.core.config import get_settings
from app.core.exceptions import UnauthorizedError

logger = logging.getLogger(__name__)
settings = get_settings()

# ---------------------------------------------------------------------------
# Password hashing
# ---------------------------------------------------------------------------

_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Pre-computed bcrypt hash of a dummy string — used in the not-found login
# path so the response time is indistinguishable from a real wrong-password
# attempt, preventing user-enumeration via timing.
_DUMMY_HASH: str = _pwd_context.hash("__dummy_timing_guard__")


def hash_password(plain_password: str) -> str:
    """Return a bcrypt hash of the given plain-text password."""
    return _pwd_context.hash(plain_password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Return True if the plain password matches the stored hash."""
    return _pwd_context.verify(plain_password, hashed_password)


# ---------------------------------------------------------------------------
# Login attempt tracker (brute-force / lockout)
# ---------------------------------------------------------------------------

class LoginAttemptTracker:
    """In-memory tracker for failed login attempts with rolling-window lockout.

    Limitations: state is per-process. For multi-instance deployments replace
    this with a Redis-backed implementation.
    """

    MAX_ATTEMPTS: int = 5
    WINDOW_SECONDS: int = 900  # 15-minute rolling window

    def __init__(self) -> None:
        self._attempts: dict[str, list[float]] = {}
        self._lock = asyncio.Lock()

    def _prune(self, email: str, now: float) -> list[float]:
        """Return only attempts within the current window (mutates in place)."""
        recent = [t for t in self._attempts.get(email, []) if now - t < self.WINDOW_SECONDS]
        self._attempts[email] = recent
        return recent

    async def is_locked(self, email: str) -> bool:
        """Return True if the email has exceeded the failure threshold."""
        async with self._lock:
            recent = self._prune(email, time.monotonic())
            return len(recent) >= self.MAX_ATTEMPTS

    async def record_failure(self, email: str) -> None:
        """Record a failed login attempt."""
        async with self._lock:
            now = time.monotonic()
            self._prune(email, now)
            self._attempts[email].append(now)

    async def clear(self, email: str) -> None:
        """Clear failed attempts after a successful login."""
        async with self._lock:
            self._attempts.pop(email, None)


# Module-level singleton — imported by auth_service.
login_attempt_tracker = LoginAttemptTracker()


# ---------------------------------------------------------------------------
# JWT
# ---------------------------------------------------------------------------

def create_access_token(
    user_id: uuid.UUID,
    role: str,
    expires_delta: Optional[timedelta] = None,
) -> str:
    """Create a signed JWT access token containing user_id and role.

    Args:
        user_id: The authenticated user's UUID.
        role: The user's role string ('user' or 'admin').
        expires_delta: Token lifetime. Defaults to ACCESS_TOKEN_EXPIRE_MINUTES.

    Returns:
        A signed JWT string.
    """
    if expires_delta is None:
        expires_delta = timedelta(minutes=settings.access_token_expire_minutes)

    now = datetime.now(tz=timezone.utc)
    expire = now + expires_delta

    payload = {
        "sub": str(user_id),
        "role": role,
        "iat": now,
        "exp": expire,
    }

    return jwt.encode(payload, settings.secret_key, algorithm=settings.jwt_algorithm)


def create_password_reset_token(user_id: uuid.UUID) -> str:
    """Create a short-lived signed JWT for password reset.

    The token contains a 'type: password_reset' claim so it cannot be used
    as an access token, and vice-versa.  Expiry is controlled by the
    PASSWORD_RESET_TOKEN_EXPIRE_MINUTES setting (default 15 minutes).

    Args:
        user_id: The UUID of the user requesting the reset.

    Returns:
        A signed JWT string.
    """
    now = datetime.now(tz=timezone.utc)
    expire = now + timedelta(minutes=settings.password_reset_token_expire_minutes)

    payload = {
        "sub":  str(user_id),
        "type": "password_reset",
        "iat":  now,
        "exp":  expire,
    }
    return jwt.encode(payload, settings.secret_key, algorithm=settings.jwt_algorithm)


def verify_password_reset_token(token: str) -> uuid.UUID:
    """Decode and verify a password-reset JWT.

    Raises:
        UnauthorizedError: If the token is invalid, expired, the wrong type,
                           or the subject is not a valid UUID.

    Returns:
        The user UUID extracted from the token's 'sub' claim.
    """
    try:
        payload = jwt.decode(
            token,
            settings.secret_key,
            algorithms=[settings.jwt_algorithm],
        )
    except JWTError as exc:
        logger.debug("Password reset token decode failed: %s", exc)
        raise UnauthorizedError("Invalid or expired password reset token.") from exc

    if payload.get("type") != "password_reset":
        raise UnauthorizedError("Invalid token type.")

    sub = payload.get("sub")
    if not sub:
        raise UnauthorizedError("Token missing subject claim.")
    try:
        return uuid.UUID(sub)
    except ValueError as exc:
        raise UnauthorizedError("Token subject is not a valid UUID.") from exc


def decode_access_token(token: str) -> dict:
    """Decode and verify a JWT access token.

    Raises:
        UnauthorizedError: If the token is invalid, expired, or malformed.

    Returns:
        The raw payload dictionary.
    """
    try:
        payload = jwt.decode(
            token,
            settings.secret_key,
            algorithms=[settings.jwt_algorithm],
        )
        return payload
    except JWTError as exc:
        logger.debug("JWT decode failed: %s", exc)
        raise UnauthorizedError("Invalid or expired token.") from exc


def extract_user_id(payload: dict) -> uuid.UUID:
    """Extract and parse the user UUID from a decoded JWT payload.

    Raises:
        UnauthorizedError: If the 'sub' claim is missing or not a valid UUID.
    """
    sub = payload.get("sub")
    if not sub:
        raise UnauthorizedError("Token payload missing 'sub' claim.")
    try:
        return uuid.UUID(sub)
    except ValueError as exc:
        raise UnauthorizedError("Token 'sub' claim is not a valid UUID.") from exc


def extract_role(payload: dict) -> str:
    """Extract the role from a decoded JWT payload.

    Raises:
        UnauthorizedError: If the 'role' claim is missing.
    """
    role = payload.get("role")
    if not role:
        raise UnauthorizedError("Token payload missing 'role' claim.")
    return str(role)
