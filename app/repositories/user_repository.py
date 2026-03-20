"""User repository."""

from __future__ import annotations

from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.repositories.base import BaseRepository


class UserRepository(BaseRepository[User]):
    """Data access layer for the users table."""

    def __init__(self, db: AsyncSession) -> None:
        super().__init__(User, db)

    async def get_by_email(self, email: str) -> Optional[User]:
        """Return a user by email address (case-insensitive), or None."""
        result = await self.db.execute(
            select(User).where(User.email == email.lower().strip())
        )
        return result.scalar_one_or_none()

    async def create(  # type: ignore[override]
        self,
        email: str,
        display_name: str,
        password_hash: str,
        phone_number: Optional[str] = None,
    ) -> User:
        """Create and persist a new user record.

        Args:
            email: Unique email address (normalised to lowercase).
            display_name: User's chosen display name.
            password_hash: Bcrypt hash of the plain-text password.
            phone_number: Optional phone number.

        Returns:
            The newly created User instance.
        """
        return await super().create(
            email=email.lower().strip(),
            display_name=display_name.strip(),
            password_hash=password_hash,
            phone_number=phone_number,
        )
