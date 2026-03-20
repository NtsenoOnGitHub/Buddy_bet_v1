"""Declarative Base for all SQLAlchemy ORM models.

Every model module must import Base from here so that Base.metadata contains
all table definitions. Alembic's env.py imports Base to drive autogenerate.
"""

from __future__ import annotations

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Shared declarative base.

    All ORM models inherit from this class. SQLAlchemy 2.0 uses the
    DeclarativeBase pattern — no need for declarative_base() call.
    """
    pass
