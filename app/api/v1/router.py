"""API v1 router — aggregates all endpoint routers.

ROUTING NOTE (from spec Section 12):
  Static path segments (/bets/open, /bets/my) MUST be registered before
  the dynamic segment (/bets/{bet_id}) to prevent FastAPI from matching
  the static words as UUID values. This is handled by router registration
  order in include_router calls.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.api.v1.endpoints import admin, auth, bets, matches, wallet

api_router = APIRouter()

# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
api_router.include_router(
    auth.router,
    prefix="/auth",
    tags=["Authentication"],
)

# ---------------------------------------------------------------------------
# Matches
# ---------------------------------------------------------------------------
api_router.include_router(
    matches.router,
    prefix="/matches",
    tags=["Matches"],
)

# ---------------------------------------------------------------------------
# Bets — static routes (/open, /my) MUST come before dynamic (/bets/{id})
# ---------------------------------------------------------------------------
api_router.include_router(
    bets.router,
    prefix="/bets",
    tags=["Bets"],
)

# ---------------------------------------------------------------------------
# Wallet
# ---------------------------------------------------------------------------
api_router.include_router(
    wallet.router,
    prefix="/wallet",
    tags=["Wallet"],
)

# ---------------------------------------------------------------------------
# Admin — match result confirmation, manual settlement, bet voiding
# ---------------------------------------------------------------------------
api_router.include_router(
    admin.router,
    prefix="/admin",
    tags=["Admin"],
)
