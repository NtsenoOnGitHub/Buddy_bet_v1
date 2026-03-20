"""Shared pytest fixtures for the Buddy Bet test suite.

TODO: Wire up a test database (e.g. a separate PostgreSQL test DB or
      an in-memory SQLite override) and replace the placeholder fixtures
      below with real async sessions and a test HTTP client.
"""

from __future__ import annotations

import pytest
import pytest_asyncio
from httpx import AsyncClient

# ---------------------------------------------------------------------------
# Async test configuration
# ---------------------------------------------------------------------------
# pytest-asyncio is configured in pyproject.toml with asyncio_mode = "auto"


# ---------------------------------------------------------------------------
# Placeholder fixtures — replace with real implementations
# ---------------------------------------------------------------------------

@pytest.fixture
def anyio_backend():
    return "asyncio"


# @pytest_asyncio.fixture
# async def db_session():
#     """Yield an AsyncSession connected to the test database."""
#     ...


# @pytest_asyncio.fixture
# async def client(db_session):
#     """Yield an AsyncClient wired to the FastAPI app with an overridden DB."""
#     from app.main import app
#     from app.core.dependencies import get_db
#
#     async def override_get_db():
#         yield db_session
#
#     app.dependency_overrides[get_db] = override_get_db
#     async with AsyncClient(app=app, base_url="http://test") as c:
#         yield c
#     app.dependency_overrides.clear()
