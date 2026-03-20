"""Generic base repository providing common CRUD operations.

All domain-specific repositories inherit from BaseRepository[T] where T is
the SQLAlchemy ORM model class. This avoids boilerplate while keeping
query construction close to the data layer.
"""

from __future__ import annotations

import uuid
from typing import Any, Generic, List, Optional, Tuple, Type, TypeVar

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.db.base import Base
from app.schemas.common import PageParams
from app.utils.pagination import paginate

T = TypeVar("T", bound=Base)


class BaseRepository(Generic[T]):
    """Generic async repository for a single ORM model class."""

    def __init__(self, model: Type[T], db: AsyncSession) -> None:
        self.model = model
        self.db = db

    async def get_by_id(self, record_id: uuid.UUID) -> Optional[T]:
        """Return a record by primary key, or None if not found."""
        result = await self.db.execute(
            select(self.model).where(self.model.id == record_id)  # type: ignore[attr-defined]
        )
        return result.scalar_one_or_none()

    async def get_by_id_or_404(self, record_id: uuid.UUID) -> T:
        """Return a record by primary key, raising NotFoundError if absent."""
        record = await self.get_by_id(record_id)
        if record is None:
            raise NotFoundError(
                f"{self.model.__name__} with id={record_id} was not found."
            )
        return record

    async def create(self, **kwargs: Any) -> T:
        """Create and persist a new record with the provided field values.

        The record is added to the session and flushed (not committed).
        The calling service is responsible for committing the transaction.
        """
        record = self.model(**kwargs)  # type: ignore[call-arg]
        self.db.add(record)
        await self.db.flush()
        await self.db.refresh(record)
        return record

    async def list(
        self,
        params: PageParams,
        *where_clauses: Any,
    ) -> Tuple[List[T], int]:
        """Return a paginated list of records matching the given where clauses.

        Args:
            params: Pagination parameters.
            *where_clauses: SQLAlchemy WHERE clause expressions.

        Returns:
            Tuple of (list of records, total count).
        """
        query = select(self.model)
        for clause in where_clauses:
            query = query.where(clause)
        return await paginate(self.db, query, params)
