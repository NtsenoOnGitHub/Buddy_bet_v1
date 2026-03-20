"""Wallet and ledger entry response schemas.

total_balance is a computed field: available_balance + locked_balance.
It is not stored in the database — it is computed at serialisation time.

All monetary values use DecimalStr to ensure they serialise as strings in JSON.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, computed_field

from app.models.enums import (
    BalanceField,
    LedgerDirection,
    LedgerEntryType,
    LedgerReferenceType,
)
from app.schemas.common import DecimalStr


class WalletResponse(BaseModel):
    """Wallet balances response for GET /wallet.

    total_balance is a computed field — not stored in the DB.
    All balance values serialise as decimal strings per BR requirements.
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: uuid.UUID
    available_balance: DecimalStr
    locked_balance: DecimalStr
    currency: str
    version: int
    updated_at: datetime

    @computed_field  # type: ignore[misc]
    @property
    def total_balance(self) -> str:
        """Computed: available_balance + locked_balance, serialised as string."""
        total = Decimal(str(self.available_balance)) + Decimal(str(self.locked_balance))
        return str(total)


class LedgerEntryResponse(BaseModel):
    """Single ledger entry row — used for GET /wallet/transactions."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: uuid.UUID
    wallet_id: uuid.UUID
    entry_type: LedgerEntryType
    balance_field: BalanceField
    direction: LedgerDirection
    amount: DecimalStr
    reference_type: LedgerReferenceType
    reference_id: uuid.UUID
    available_balance_after: DecimalStr
    locked_balance_after: DecimalStr
    notes: Optional[str] = None
    created_at: datetime
