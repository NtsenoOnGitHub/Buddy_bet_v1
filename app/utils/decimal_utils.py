"""Decimal arithmetic utilities for monetary calculations.

All monetary arithmetic in the application MUST go through these functions.
Never use float. Never use round(). Always use Decimal with explicit rounding.

Rounding rule: ROUND_HALF_UP to 2 decimal places (nearest cent).
Any sub-cent remainder is effectively credited to the platform because
payouts/refunds are rounded down and the platform receives the remainder.
This is the recommended default from the design spec (PO-06).
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from app.core.exceptions import ValidationError

# Precision constant — 2 decimal places for all monetary values
_CENT = Decimal("0.01")


def round_half_up(value: Decimal) -> Decimal:
    """Round a Decimal to 2 decimal places using ROUND_HALF_UP.

    Args:
        value: The Decimal to round.

    Returns:
        Decimal rounded to nearest cent (ROUND_HALF_UP).
    """
    return value.quantize(_CENT, rounding=ROUND_HALF_UP)


def safe_add(a: Decimal, b: Decimal) -> Decimal:
    """Add two Decimals and return the result rounded to 2 dp.

    Args:
        a: First operand.
        b: Second operand.

    Returns:
        a + b, rounded to nearest cent.
    """
    return round_half_up(a + b)


def safe_subtract(a: Decimal, b: Decimal) -> Decimal:
    """Subtract b from a and return the result rounded to 2 dp.

    Args:
        a: Minuend.
        b: Subtrahend.

    Returns:
        a - b, rounded to nearest cent.

    Note:
        Does NOT verify non-negativity. Call verify_non_negative separately
        if you need to enforce that the result is >= 0.
    """
    return round_half_up(a - b)


def safe_multiply(value: Decimal, rate: Decimal) -> Decimal:
    """Multiply value by rate and return the result rounded to 2 dp.

    Used for fee calculations: fee = stake * rate.

    Args:
        value: The base amount.
        rate: The multiplier (e.g. Decimal('0.10') for 10%).

    Returns:
        value * rate, rounded to nearest cent (ROUND_HALF_UP).
    """
    return round_half_up(value * rate)


def verify_non_negative(value: Decimal, field_name: str = "amount") -> None:
    """Assert that a Decimal value is >= 0.

    Args:
        value: The value to check.
        field_name: Name used in the error message.

    Raises:
        ValidationError: If value < 0.
    """
    if value < Decimal("0"):
        raise ValidationError(f"{field_name} must not be negative (got {value}).")


def to_decimal(value: object) -> Decimal:
    """Safely coerce an unknown value to Decimal.

    Accepts Decimal, int, float (not recommended), or str.

    Args:
        value: The value to convert.

    Returns:
        Decimal representation of value.

    Raises:
        ValidationError: If conversion fails.
    """
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except InvalidOperation as exc:
        raise ValidationError(f"Cannot convert {value!r} to Decimal.") from exc
