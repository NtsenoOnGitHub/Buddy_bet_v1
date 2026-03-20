"""Shared Pydantic v2 schema utilities.

DecimalStr:
    An annotated Decimal type that serialises as a string in JSON responses
    and accepts both string and numeric input. This prevents float imprecision
    in API payloads — all monetary values are represented as decimal strings.

PaginatedResponse:
    A generic paginated response envelope used by list endpoints.

PageParams:
    Query parameter model for pagination.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Annotated, Generic, List, TypeVar

from pydantic import BaseModel, ConfigDict, Field, field_serializer, field_validator
from pydantic import GetCoreSchemaHandler
from pydantic_core import core_schema


# ---------------------------------------------------------------------------
# DecimalStr — Decimal that serialises as a string
# ---------------------------------------------------------------------------

class _DecimalStrType:
    """Pydantic custom type: Decimal stored/computed as Decimal, serialised as str."""

    @classmethod
    def __get_pydantic_core_schema__(
        cls, source_type: object, handler: GetCoreSchemaHandler
    ) -> core_schema.CoreSchema:
        return core_schema.no_info_plain_validator_function(
            cls._validate,
            serialization=core_schema.plain_serializer_function_ser_schema(
                cls._serialize, info_arg=False
            ),
        )

    @staticmethod
    def _validate(v: object) -> Decimal:
        if isinstance(v, Decimal):
            return v
        if isinstance(v, (int, float, str)):
            try:
                return Decimal(str(v))
            except Exception:
                raise ValueError(f"Cannot convert {v!r} to Decimal")
        raise ValueError(f"Expected Decimal-compatible value, got {type(v).__name__}")

    @staticmethod
    def _serialize(v: Decimal) -> str:
        return str(v)


# Use this as the type annotation for monetary fields in response schemas.
DecimalStr = Annotated[Decimal, _DecimalStrType()]


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------

T = TypeVar("T")


class PaginatedResponse(BaseModel, Generic[T]):
    """Generic paginated response envelope.

    All list endpoints that support pagination return this shape:
        {
            "items": [...],
            "total": 42,
            "page": 1,
            "page_size": 20,
            "pages": 3
        }
    """

    model_config = ConfigDict(from_attributes=True)

    items: List[T]
    total: int
    page: int
    page_size: int
    pages: int

    @classmethod
    def create(
        cls,
        items: List[T],
        total: int,
        page: int,
        page_size: int,
    ) -> "PaginatedResponse[T]":
        pages = max(1, (total + page_size - 1) // page_size) if total > 0 else 0
        return cls(
            items=items,
            total=total,
            page=page,
            page_size=page_size,
            pages=pages,
        )


class PageParams(BaseModel):
    """Standard pagination query parameters."""

    model_config = ConfigDict(from_attributes=True)

    page: int = Field(default=1, ge=1, description="1-based page number")
    page_size: int = Field(default=20, ge=1, le=100, description="Results per page (max 100)")

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size

    @property
    def limit(self) -> int:
        return self.page_size
