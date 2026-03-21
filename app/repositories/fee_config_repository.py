"""FeeConfig repository.

Resolves the active fee rate for a given (fee_type, currency) pair at a
specific point in time. Fee rows are versioned by effective_from and are
never updated or deleted — the most recent row with effective_from <= as_of
is the applicable rate.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.models.enums import FeeType
from app.models.fee_config import FeeConfig
from app.repositories.base import BaseRepository


class FeeConfigRepository(BaseRepository[FeeConfig]):
    """Data access layer for the fee_config table."""

    def __init__(self, db: AsyncSession) -> None:
        super().__init__(FeeConfig, db)

    async def get_active_rate(
        self,
        fee_type: FeeType,
        currency: str,
        as_of: datetime,
    ) -> Decimal:
        """Return the most recently effective fee rate for a given type and currency.

        Selects the row with the highest effective_from that is still <= as_of.
        This implements the versioned fee resolution required by spec Section 9.6.

        Args:
            fee_type: WINNER_FEE or NO_WINNER_FEE.
            currency: ISO 4217 currency code, e.g. "ZAR".
            as_of: Point-in-time for which the rate should be effective
                   (typically the settlement timestamp).

        Returns:
            The applicable Decimal fee rate (e.g. Decimal("0.1000") for 10%).

        Raises:
            NotFoundError: If no fee config row exists for the given parameters.
        """
        result = await self.db.execute(
            select(FeeConfig.rate)
            .where(FeeConfig.fee_type == fee_type)
            .where(FeeConfig.currency == currency)
            .where(FeeConfig.effective_from <= as_of)
            .order_by(FeeConfig.effective_from.desc())
            .limit(1)
        )
        rate: Optional[Decimal] = result.scalar_one_or_none()
        if rate is None:
            raise NotFoundError(
                f"No active fee config for fee_type={fee_type.value!r}, "
                f"currency={currency!r}, as_of={as_of.isoformat()}. "
                "Ensure fee_config rows are seeded before running settlement."
            )
        return rate
