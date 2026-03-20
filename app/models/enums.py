"""Python enum types mirroring every PostgreSQL enum in schema.sql.

IMPORTANT: These enum values must exactly match the PostgreSQL enum labels
defined in schema.sql. Any mismatch will cause runtime errors when reading
from or writing to the database.

All SQLAlchemy column definitions using these enums must pass:
    create_type=False  — the types already exist in the DB from schema.sql
    native_enum=True   — use the Postgres native enum type, not VARCHAR
"""

from __future__ import annotations

import enum


class UserStatus(str, enum.Enum):
    """Maps to PostgreSQL enum: user_status"""
    active = "active"
    suspended = "suspended"
    banned = "banned"


class UserRole(str, enum.Enum):
    """Maps to PostgreSQL enum: user_role"""
    user = "user"
    admin = "admin"


class FootballOutcome(str, enum.Enum):
    """Maps to PostgreSQL enum: football_outcome.

    Used for both match results and bet predictions.
    """
    home_win = "home_win"
    away_win = "away_win"
    draw = "draw"


class MatchStatus(str, enum.Enum):
    """Maps to PostgreSQL enum: match_status"""
    scheduled = "scheduled"
    live = "live"
    completed = "completed"
    postponed = "postponed"
    cancelled = "cancelled"
    abandoned = "abandoned"


class BetStatus(str, enum.Enum):
    """Maps to PostgreSQL enum: bet_status"""
    OPEN = "OPEN"
    MATCHED = "MATCHED"
    PENDING_SETTLEMENT = "PENDING_SETTLEMENT"
    SETTLED = "SETTLED"
    CANCELLED = "CANCELLED"
    VOIDED = "VOIDED"
    UNDER_REVIEW = "UNDER_REVIEW"


class SettlementOutcome(str, enum.Enum):
    """Maps to PostgreSQL enum: settlement_outcome"""
    creator_wins = "creator_wins"
    opponent_wins = "opponent_wins"
    no_winner = "no_winner"
    voided = "voided"


class LedgerEntryType(str, enum.Enum):
    """Maps to PostgreSQL enum: ledger_entry_type"""
    STAKE_LOCK = "STAKE_LOCK"
    STAKE_UNLOCK = "STAKE_UNLOCK"
    VOID_REFUND = "VOID_REFUND"
    SETTLEMENT_DEDUCT = "SETTLEMENT_DEDUCT"
    PAYOUT_CREDIT = "PAYOUT_CREDIT"
    REFUND_CREDIT = "REFUND_CREDIT"
    FEE_DEDUCT = "FEE_DEDUCT"
    DEPOSIT = "DEPOSIT"
    WITHDRAWAL = "WITHDRAWAL"


class BalanceField(str, enum.Enum):
    """Maps to PostgreSQL enum: balance_field"""
    available = "available"
    locked = "locked"


class LedgerDirection(str, enum.Enum):
    """Maps to PostgreSQL enum: ledger_direction"""
    credit = "credit"
    debit = "debit"


class LedgerReferenceType(str, enum.Enum):
    """Maps to PostgreSQL enum: ledger_reference_type"""
    bet = "bet"
    settlement = "settlement"
    void = "void"
    cancellation = "cancellation"
    deposit = "deposit"
    withdrawal = "withdrawal"


class PlatformEntryType(str, enum.Enum):
    """Maps to PostgreSQL enum: platform_entry_type"""
    FEE_COLLECTION = "FEE_COLLECTION"
    FEE_COLLECTION_NO_WINNER = "FEE_COLLECTION_NO_WINNER"


class SettlementPathType(str, enum.Enum):
    """Maps to PostgreSQL enum: settlement_path_type"""
    winner = "winner"
    no_winner = "no_winner"


class FeeType(str, enum.Enum):
    """Maps to PostgreSQL enum: fee_type"""
    WINNER_FEE = "WINNER_FEE"
    NO_WINNER_FEE = "NO_WINNER_FEE"


class BetEventType(str, enum.Enum):
    """Maps to PostgreSQL enum: bet_event_type"""
    CREATED = "CREATED"
    MATCHED = "MATCHED"
    PENDING_SETTLEMENT = "PENDING_SETTLEMENT"
    SETTLED = "SETTLED"
    CANCELLED = "CANCELLED"
    VOIDED = "VOIDED"
    UNDER_REVIEW = "UNDER_REVIEW"
    ADMIN_OVERRIDE = "ADMIN_OVERRIDE"
