"""Authentication endpoints.

POST /auth/register — create a new user account and return a JWT + user profile.
POST /auth/login    — verify credentials and return a JWT + user profile.
GET  /auth/me       — return the current authenticated user's profile.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user, get_db
from app.models.user import User
from app.schemas.auth import (
    ForgotPasswordRequest,
    ForgotPasswordResponse,
    LoginRequest,
    RegisterRequest,
    ResetPasswordRequest,
    TokenResponse,
)
from app.schemas.user import UserResponse
from app.services.auth_service import AuthService

router = APIRouter()


@router.post(
    "/register",
    response_model=TokenResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new user account",
    description=(
        "Creates a new user account, initialises a zero-balance wallet, "
        "and returns a JWT access token together with the created user profile."
    ),
)
async def register(
    body: RegisterRequest,
    db: AsyncSession = Depends(get_db),
) -> TokenResponse:
    service = AuthService(db)
    return await service.register(body)


@router.post(
    "/login",
    response_model=TokenResponse,
    status_code=status.HTTP_200_OK,
    summary="Authenticate and receive a JWT",
    description=(
        "Verifies email and password. Returns a JWT access token together "
        "with the authenticated user profile on success."
    ),
)
async def login(
    body: LoginRequest,
    db: AsyncSession = Depends(get_db),
) -> TokenResponse:
    service = AuthService(db)
    return await service.login(body)


@router.post(
    "/forgot-password",
    response_model=ForgotPasswordResponse,
    status_code=status.HTTP_200_OK,
    summary="Request a password reset token",
    description=(
        "Generates a short-lived password reset token for the given email address. "
        "The response is identical whether or not the email is registered "
        "(prevents user enumeration). "
        "In development mode the token is returned directly in the response. "
        "In production the token would be delivered via email."
    ),
)
async def forgot_password(
    body: ForgotPasswordRequest,
    db: AsyncSession = Depends(get_db),
) -> ForgotPasswordResponse:
    service = AuthService(db)
    return await service.forgot_password(body)


@router.post(
    "/reset-password",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Reset password using a reset token",
    description=(
        "Verifies the reset token and updates the account's password. "
        "The token must have been obtained from /auth/forgot-password "
        "and expires after 15 minutes."
    ),
)
async def reset_password(
    body: ResetPasswordRequest,
    db: AsyncSession = Depends(get_db),
) -> None:
    service = AuthService(db)
    await service.reset_password(body)


@router.get(
    "/me",
    response_model=UserResponse,
    status_code=status.HTTP_200_OK,
    summary="Get current user profile",
    description=(
        "Returns the authenticated user's profile: id, email, display_name, "
        "role, status, and timestamps. Use this to re-hydrate the session after "
        "a page refresh without re-authenticating."
    ),
)
async def get_me(
    current_user: User = Depends(get_current_user),
) -> UserResponse:
    return UserResponse.model_validate(current_user)
