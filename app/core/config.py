"""Application configuration via Pydantic Settings v2.

All environment variables are read from the environment or a .env file.
The Settings object is a singleton — use get_settings() everywhere.
"""

from __future__ import annotations

import logging
from decimal import Decimal
from functools import lru_cache
from typing import List

from pydantic import field_validator, computed_field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # -----------------------------------------------------------------------
    # Application
    # -----------------------------------------------------------------------
    app_env: str = "development"
    app_debug: bool = True
    app_host: str = "0.0.0.0"
    app_port: int = 8000

    # -----------------------------------------------------------------------
    # Database components (used to build DSN)
    # -----------------------------------------------------------------------
    db_host: str = "localhost"
    db_port: int = 5432
    db_name: str = "buddy_bet"
    db_user: str = "buddy_bet_app"
    db_password: str = "change_me"

    # Optional override — if provided, supersedes the computed DSN.
    database_url: str | None = None

    # Pool settings
    db_pool_size: int = 10
    db_max_overflow: int = 20
    db_pool_timeout: int = 30
    db_pool_recycle: int = 1800

    # -----------------------------------------------------------------------
    # Security / JWT
    # -----------------------------------------------------------------------
    secret_key: str = "INSECURE_CHANGE_ME"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60
    password_reset_token_expire_minutes: int = 15

    # -----------------------------------------------------------------------
    # CORS
    # -----------------------------------------------------------------------
    cors_origins: List[str] = ["http://localhost:3000", "http://localhost:5173"]

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_cors_origins(cls, v: object) -> List[str]:
        if isinstance(v, str):
            return [origin.strip() for origin in v.split(",") if origin.strip()]
        return v  # type: ignore[return-value]

    # -----------------------------------------------------------------------
    # Platform constants
    # -----------------------------------------------------------------------
    platform_account_code: str = "PLATFORM_FEES_ZAR"
    platform_currency: str = "ZAR"
    min_stake_amount: Decimal = Decimal("10.00")
    max_stake_amount: Decimal = Decimal("10000.00")
    # Minutes before kickoff after which bet creation is blocked (PO-05)
    bet_creation_cutoff_minutes: int = 15

    # -----------------------------------------------------------------------
    # Development helpers
    # -----------------------------------------------------------------------
    # Set SEED_TEST_USER=true to auto-create a funded test user on startup.
    # Has no effect outside development (app_env != "development").
    seed_test_user: bool = False

    # -----------------------------------------------------------------------
    # Logging
    # -----------------------------------------------------------------------
    log_level: str = "INFO"

    # -----------------------------------------------------------------------
    # Startup guards
    # -----------------------------------------------------------------------

    @model_validator(mode="after")
    def _reject_insecure_secret_key_in_production(self) -> "Settings":
        """Fail fast if SECRET_KEY is an insecure placeholder outside development."""
        _insecure_placeholders = {
            "INSECURE_CHANGE_ME",
            "changeme",
            "change_me",
            "secret",
            "your-secret-key",
            "",
        }
        if self.app_env != "development" and self.secret_key in _insecure_placeholders:
            raise ValueError(
                f"SECRET_KEY is set to an insecure placeholder value while "
                f"APP_ENV='{self.app_env}'. "
                "Set a strong, randomly generated SECRET_KEY before deploying."
            )
        return self

    # -----------------------------------------------------------------------
    # Computed DSN properties
    # -----------------------------------------------------------------------

    @computed_field  # type: ignore[misc]
    @property
    def database_url_async(self) -> str:
        """Async DSN for SQLAlchemy asyncpg driver."""
        if self.database_url:
            # Replace sync driver prefix if someone supplies a sync URL
            url = self.database_url
            if url.startswith("postgresql://"):
                url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
            elif url.startswith("postgres://"):
                url = url.replace("postgres://", "postgresql+asyncpg://", 1)
            return url
        return (
            f"postgresql+asyncpg://{self.db_user}:{self.db_password}"
            f"@{self.db_host}:{self.db_port}/{self.db_name}"
        )

    @computed_field  # type: ignore[misc]
    @property
    def database_url_sync(self) -> str:
        """Sync DSN used by Alembic (psycopg2-style URL for env.py)."""
        if self.database_url:
            url = self.database_url
            if "+asyncpg" in url:
                url = url.replace("+asyncpg", "", 1)
            return url
        return (
            f"postgresql://{self.db_user}:{self.db_password}"
            f"@{self.db_host}:{self.db_port}/{self.db_name}"
        )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the singleton Settings instance."""
    settings = Settings()
    logging.basicConfig(level=getattr(logging, settings.log_level.upper(), logging.INFO))
    return settings
