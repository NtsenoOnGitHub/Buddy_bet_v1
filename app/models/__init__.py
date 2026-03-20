"""Model package — import all ORM models so Alembic autogenerate finds them.

This file must import every model class. If a model is not imported here,
Alembic will not detect its table during `alembic revision --autogenerate`.

Import order respects FK dependencies (referenced tables before referencing).
"""

from app.models.user import User  # noqa: F401
from app.models.wallet import Wallet  # noqa: F401
from app.models.platform import PlatformAccount, PlatformLedgerEntry  # noqa: F401
from app.models.match import Match  # noqa: F401
from app.models.fee_config import FeeConfig  # noqa: F401
from app.models.bet import Bet  # noqa: F401
from app.models.ledger import LedgerEntry  # noqa: F401
from app.models.bet_event import BetEvent  # noqa: F401
from app.models.processed_event import ProcessedEvent  # noqa: F401

__all__ = [
    "User",
    "Wallet",
    "PlatformAccount",
    "PlatformLedgerEntry",
    "Match",
    "FeeConfig",
    "Bet",
    "LedgerEntry",
    "BetEvent",
    "ProcessedEvent",
]
