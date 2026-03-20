"""Security utilities — JWT creation/verification and password hashing.

JWT payload schema:
    {
        "sub": "<user_id as string>",
        "role": "<user_role>",
        "exp": <unix timestamp>
    }
"""

from __future__ import annotations

import logging
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


def hash_password(plain_password: str) -> str:
    """Return a bcrypt hash of the given plain-text password."""
    return _pwd_context.hash(plain_password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Return True if the plain password matches the stored hash."""
    return _pwd_context.verify(plain_password, hashed_password)


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
