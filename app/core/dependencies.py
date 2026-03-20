"""FastAPI dependency injection — database sessions and current user resolution."""

from __future__ import annotations

import logging
import uuid
from typing import AsyncGenerator, Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.security import decode_access_token, extract_user_id, extract_role
from app.core.exceptions import UnauthorizedError, ForbiddenError
from app.db.session import AsyncSessionFactory
from app.models.user import User
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# HTTP Bearer extractor — does not auto-error so we can support optional auth
# ---------------------------------------------------------------------------
_bearer_scheme = HTTPBearer(auto_error=False)


# ---------------------------------------------------------------------------
# Database session
# ---------------------------------------------------------------------------

async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Yield an async database session scoped to a single request.

    Transaction lifecycle is owned by the service layer for write operations.
    The session is closed (and any uncommitted transaction rolled back) when
    the async context manager exits.
    """
    async with AsyncSessionFactory() as session:
        yield session


# ---------------------------------------------------------------------------
# Token extraction helpers
# ---------------------------------------------------------------------------

def _extract_token(
    credentials: Optional[HTTPAuthorizationCredentials],
) -> Optional[str]:
    """Return the raw Bearer token string, or None if absent."""
    if credentials is None:
        return None
    if credentials.scheme.lower() != "bearer":
        return None
    return credentials.credentials


async def _load_user(user_id: uuid.UUID, db: AsyncSession) -> User:
    """Load a user by primary key, raising UnauthorizedError if not found."""
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise UnauthorizedError("User account not found.")
    return user


# ---------------------------------------------------------------------------
# get_current_user — mandatory auth
# ---------------------------------------------------------------------------

async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Resolve the currently authenticated user.

    Raises HTTP 401 if no valid Bearer token is supplied, or if the token's
    subject does not correspond to an existing user.
    """
    token = _extract_token(credentials)
    if not token:
        raise UnauthorizedError("Authentication credentials were not provided.")

    payload = decode_access_token(token)
    user_id = extract_user_id(payload)
    user = await _load_user(user_id, db)
    return user


# ---------------------------------------------------------------------------
# optional_current_user — auth optional (returns None if unauthenticated)
# ---------------------------------------------------------------------------

async def optional_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> Optional[User]:
    """Resolve the currently authenticated user, or return None.

    Does NOT raise if no credentials are provided. Used for endpoints that
    serve both authenticated and anonymous users with different behaviour.
    """
    token = _extract_token(credentials)
    if not token:
        return None
    try:
        payload = decode_access_token(token)
        user_id = extract_user_id(payload)
        return await _load_user(user_id, db)
    except UnauthorizedError:
        # Expected: invalid/expired token or user not found — treat as anonymous.
        return None
    # All other exceptions (DB errors, runtime failures) propagate normally.


# ---------------------------------------------------------------------------
# get_current_admin — mandatory auth + admin role check
# ---------------------------------------------------------------------------

async def get_current_admin(
    current_user: User = Depends(get_current_user),
) -> User:
    """Resolve the current user and assert they have the 'admin' role.

    Raises HTTP 403 if the authenticated user is not an admin.
    """
    if current_user.role.value != "admin":
        raise ForbiddenError("Administrator privileges required.")
    return current_user
