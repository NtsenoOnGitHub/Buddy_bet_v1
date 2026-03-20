"""Authentication schemas — register, login, and token responses."""

from __future__ import annotations

import uuid
from typing import Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


class RegisterRequest(BaseModel):
    """Request body for POST /auth/register."""

    model_config = ConfigDict(str_strip_whitespace=True)

    email: EmailStr = Field(..., description="User email address. Must be unique.")
    display_name: str = Field(
        ...,
        min_length=2,
        max_length=100,
        description="Public display name.",
    )
    password: str = Field(
        ...,
        min_length=8,
        max_length=128,
        description="Plain-text password (min 8 characters). Stored as bcrypt hash.",
    )
    phone_number: Optional[str] = Field(
        default=None,
        max_length=30,
        description="Optional phone number.",
    )

    @field_validator("password")
    @classmethod
    def password_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Password must not be blank.")
        return v


class LoginRequest(BaseModel):
    """Request body for POST /auth/login."""

    model_config = ConfigDict(str_strip_whitespace=True)

    email: EmailStr = Field(..., description="Registered email address.")
    password: str = Field(..., description="Plain-text password.")


class TokenResponse(BaseModel):
    """Response body for successful authentication."""

    model_config = ConfigDict(from_attributes=True)

    access_token: str = Field(..., description="JWT Bearer access token.")
    token_type: str = Field(default="bearer", description="Token scheme.")
    expires_in: int = Field(..., description="Token lifetime in seconds.")


class TokenPayload(BaseModel):
    """Internal representation of a decoded JWT payload."""

    sub: str = Field(..., description="User ID (UUID string).")
    role: str = Field(..., description="User role.")

    @property
    def user_id(self) -> uuid.UUID:
        return uuid.UUID(self.sub)
