"""Custom exception hierarchy for the Buddy Bet application.

All application exceptions inherit from AppException which carries an HTTP
status code and a human-readable detail string. FastAPI exception handlers in
app.main convert these to consistent JSON responses:

    {"detail": "<message>"}

or for field-level validation:

    {"detail": [{"field": "<name>", "message": "<description>"}]}
"""

from __future__ import annotations

from typing import List


# ---------------------------------------------------------------------------
# Base
# ---------------------------------------------------------------------------

class AppException(Exception):
    """Base class for all application-level exceptions.

    Attributes:
        status_code: The HTTP status code to return to the client.
        detail: Human-readable error message.
    """

    status_code: int = 500
    detail: str = "An unexpected error occurred."

    def __init__(self, detail: str | None = None) -> None:
        if detail is not None:
            self.detail = detail
        super().__init__(self.detail)


# ---------------------------------------------------------------------------
# 400 Bad Request
# ---------------------------------------------------------------------------

class BadRequestError(AppException):
    status_code = 400
    detail = "Bad request."


# ---------------------------------------------------------------------------
# 401 Unauthorized
# ---------------------------------------------------------------------------

class UnauthorizedError(AppException):
    status_code = 401
    detail = "Authentication required."


# ---------------------------------------------------------------------------
# 403 Forbidden
# ---------------------------------------------------------------------------

class ForbiddenError(AppException):
    status_code = 403
    detail = "You do not have permission to perform this action."


# ---------------------------------------------------------------------------
# 404 Not Found
# ---------------------------------------------------------------------------

class NotFoundError(AppException):
    status_code = 404
    detail = "The requested resource was not found."


# ---------------------------------------------------------------------------
# 409 Conflict
# ---------------------------------------------------------------------------

class ConflictError(AppException):
    status_code = 409
    detail = "The request conflicts with the current state of the resource."


# ---------------------------------------------------------------------------
# 422 Unprocessable Entity
# ---------------------------------------------------------------------------

class ValidationError(AppException):
    """Application-level validation failure.

    Can carry either a plain string detail or a list of field-level errors.
    The exception handler in app.main will serialize whichever is present.
    """

    status_code = 422

    def __init__(
        self,
        detail: str | List[dict] | None = None,
    ) -> None:
        if isinstance(detail, list):
            self.detail = detail  # type: ignore[assignment]
            Exception.__init__(self, str(detail))
        else:
            super().__init__(detail)


# ---------------------------------------------------------------------------
# Domain-specific exceptions
# ---------------------------------------------------------------------------

class InsufficientFundsError(AppException):
    """Raised when a wallet operation would result in a negative balance."""

    status_code = 422
    detail = "Insufficient available balance for this operation."


class BetNotAvailableError(AppException):
    """Raised when an attempt is made to accept a bet that is no longer OPEN."""

    status_code = 409
    detail = "This bet is no longer available for acceptance."


class BetExpiredError(AppException):
    """Raised when a bet acceptance is attempted after the kickoff cutoff."""

    status_code = 409
    detail = "This bet has expired — the match kickoff time has passed."


class SelfBetError(AppException):
    """Raised when a user attempts to accept their own bet."""

    status_code = 422
    detail = "You cannot accept your own bet."


class PredictionConflictError(AppException):
    """Raised when opponent_prediction equals creator_prediction."""

    status_code = 422
    detail = "Your prediction must differ from the creator's prediction."


class MatchNotAvailableError(AppException):
    """Raised when a bet is created on a match not in 'scheduled' status."""

    status_code = 422
    detail = "This match is not available for betting."


class AccountIneligibleError(AppException):
    """Raised when a suspended or banned user attempts a betting operation."""

    status_code = 403
    detail = "Your account is not eligible to perform this action."


class SettlementIdempotencyError(AppException):
    """Raised when the settlement idempotency guard detects a duplicate."""

    status_code = 409
    detail = "This bet has already been settled."
