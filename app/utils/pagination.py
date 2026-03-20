"""Pagination utilities for SQLAlchemy async queries.

The paginate() helper wraps a SELECT statement with a COUNT subquery and
applies OFFSET / LIMIT. It returns the results and the total row count so
the caller can construct a PaginatedResponse.
"""

from __future__ import annotations

from typing import Any, List, Tuple, Type, TypeVar

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.common import PageParams

T = TypeVar("T")


async def paginate(
    db: AsyncSession,
    query: Select,
    params: PageParams,
) -> Tuple[List[Any], int]:
    """Execute a paginated query and return (items, total_count).

    Args:
        db: The async database session.
        query: A SQLAlchemy select() statement WITHOUT limit/offset already applied.
        params: Pagination parameters (page, page_size).

    Returns:
        A tuple of (list of ORM instances, total row count before pagination).
    """
    # Count query — wraps the original as a subquery
    count_query = select(func.count()).select_from(query.subquery())
    total_result = await db.execute(count_query)
    total: int = total_result.scalar_one()

    # Paginated data query
    paginated_query = query.offset(params.offset).limit(params.limit)
    data_result = await db.execute(paginated_query)
    items = list(data_result.scalars().all())

    return items, total
