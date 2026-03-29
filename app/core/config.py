"""Application configuration via Pydantic Settings v2.

All environment variables are read from the environment or a .env file.
The Settings object is a singleton — use get_settings() everywhere.
"""

from __future__ import annotations

import logging
import ssl
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

    # Set DB_SSL=require (or "true") to force SSL — automatically enabled
    # when the DATABASE_URL points to a Supabase host.
    db_ssl: str = "auto"  # auto | require | disable

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
    # Sports data provider (match ingestion)
    # -----------------------------------------------------------------------
    # Set SPORTS_PROVIDER_ENABLED=true and supply an API key to enable
    # live fixture ingestion.  The sync service will not run if this is false.
    #
    # Supported provider:  api_football  (https://www.api-football.com)
    # Free tier: 100 calls/day — plenty for scheduled sync runs.
    #
    # Required env vars (never commit real values):
    #   SPORTS_PROVIDER_API_KEY=<your-key>
    #   SPORTS_PROVIDER_ENABLED=true
    # -----------------------------------------------------------------------
    sports_provider: str = "api_football"
    sports_provider_enabled: bool = False
    sports_provider_api_key: str = ""
    sports_provider_base_url: str = "https://v3.football.api-sports.io"
    # Leagues to track (comma-separated IDs or Python list).
    # Defaults: Premier League(39), La Liga(140), Bundesliga(78),
    #           Serie A(135), Ligue 1(61), UEFA Champions League(2).
    sports_provider_league_ids: List[int] = [39, 140, 78, 135, 61, 2]
    # How many calendar days ahead to fetch upcoming fixtures
    sports_provider_sync_days_ahead: int = 7
    # How many calendar days back to fetch recent results
    sports_provider_sync_days_back: int = 2
    # HTTP request timeout (seconds)
    sports_provider_timeout_seconds: int = 30

    @field_validator("sports_provider_league_ids", mode="before")
    @classmethod
    def parse_league_ids(cls, v: object) -> List[int]:
        if isinstance(v, str):
            return [int(i.strip()) for i in v.split(",") if i.strip()]
        return v  # type: ignore[return-value]

    # -----------------------------------------------------------------------
    # PayFast payment gateway
    # -----------------------------------------------------------------------
    # Sign up at https://www.payfast.co.za/
    # Sandbox: https://sandbox.payfast.co.za/
    #
    # Required for deposit initiation (PAYFAST_ENABLED=true):
    #   PAYFAST_MERCHANT_ID=<your merchant id>
    #   PAYFAST_MERCHANT_KEY=<your merchant key>
    #   PAYFAST_PASSPHRASE=<your security passphrase (optional but recommended)>
    #
    # URL configuration (must be publicly reachable for webhooks in production):
    #   PAYFAST_RETURN_URL  — where PayFast sends the browser after payment
    #   PAYFAST_CANCEL_URL  — where PayFast sends the browser on cancellation
    #   PAYFAST_NOTIFY_URL  — backend ITN (webhook) endpoint called by PayFast
    # -----------------------------------------------------------------------
    payfast_enabled: bool = False
    payfast_sandbox: bool = True
    payfast_merchant_id: str = ""
    payfast_merchant_key: str = ""
    payfast_passphrase: str = ""
    payfast_return_url: str = "http://localhost:3000/wallet/deposit/return"
    payfast_cancel_url: str = "http://localhost:3000/wallet/deposit/cancel"
    payfast_notify_url: str = "http://localhost:8000/api/v1/payments/webhooks/payfast"

    @computed_field  # type: ignore[misc]
    @property
    def payfast_checkout_url(self) -> str:
        """PayFast hosted checkout endpoint (sandbox or production)."""
        if self.payfast_sandbox:
            return "https://sandbox.payfast.co.za/eng/process"
        return "https://www.payfast.co.za/eng/process"

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
            "CHANGE_ME_GENERATE_WITH_openssl_rand_-hex_32",
            "",
        }
        if self.app_env != "development" and self.secret_key in _insecure_placeholders:
            raise ValueError(
                f"SECRET_KEY is set to an insecure placeholder value while "
                f"APP_ENV='{self.app_env}'. "
                "Set a strong, randomly generated SECRET_KEY before deploying."
            )
        return self

    @model_validator(mode="after")
    def _enforce_https_in_production(self) -> "Settings":
        """Require HTTPS for all PayFast URLs when running in production."""
        if self.app_env != "production" or not self.payfast_enabled:
            return self
        url_fields = {
            "payfast_return_url": self.payfast_return_url,
            "payfast_cancel_url": self.payfast_cancel_url,
            "payfast_notify_url": self.payfast_notify_url,
        }
        for field_name, url in url_fields.items():
            if url and not url.startswith("https://"):
                raise ValueError(
                    f"{field_name} must use HTTPS in production (got: {url!r}). "
                    "PayFast will reject non-HTTPS callback URLs."
                )
        return self

    # -----------------------------------------------------------------------
    # Computed DSN properties
    # -----------------------------------------------------------------------

    @computed_field  # type: ignore[misc]
    @property
    def db_connect_args(self) -> dict:
        """asyncpg connect_args — adds SSL when required.

        SSL is forced when:
          • DB_SSL=require  (explicit opt-in), or
          • DB_SSL=auto and the DATABASE_URL contains a Supabase hostname.

        Pass DB_SSL=disable to suppress SSL for local plain-Postgres setups.
        """
        url = self.database_url or ""
        supabase_host = "supabase.co" in url or "supabase.com" in url
        if self.db_ssl == "disable":
            return {}
        url = self.database_url or ""
        transaction_pooler = supabase_host and ":6543/" in url
        if self.db_ssl == "require" or (self.db_ssl == "auto" and supabase_host):
            # Use an explicit SSLContext — more reliable than the string "require"
            # on Windows where asyncpg's string-based SSL handling can fail.
            ssl_ctx = ssl.create_default_context()
            ssl_ctx.check_hostname = False
            ssl_ctx.verify_mode = ssl.CERT_NONE
            args: dict = {"ssl": ssl_ctx}
            if transaction_pooler:
                args["statement_cache_size"] = 0
            return args
        return {}

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
