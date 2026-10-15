from functools import lru_cache
from socket import gethostname
from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "FlowForge API"
    instance_id: str = Field(default_factory=gethostname, min_length=1, max_length=120)
    environment: str = "development"
    api_prefix: str = "/api/v1"
    cors_origins: list[str] = Field(default=["http://localhost:3000", "http://127.0.0.1:3000"])

    model_base_url: str = "http://localhost:8001/v1"
    model_name: str = "qwen3-4b-local"
    model_timeout_seconds: float = 120.0
    model_api_token: str = "local-model"
    model_response_format: str = "json_object"
    max_input_characters: int = 30_000
    max_attachment_bytes: int = 10_485_760
    database_url: str = "sqlite+aiosqlite:///./flowforge.db"
    redis_url: str | None = None
    realtime_channel_prefix: str = Field(default="flowforge", pattern=r"^[a-zA-Z0-9_-]{1,40}$")
    presence_ttl_seconds: int = Field(default=45, ge=15, le=300)
    embedded_worker_enabled: bool = True
    job_queue_name: str = Field(default="flowforge:jobs", min_length=3, max_length=120)
    job_poll_seconds: float = Field(default=0.5, ge=0.1, le=30)
    job_lease_seconds: int = Field(default=300, ge=60, le=3_600)
    job_max_attempts: int = Field(default=3, ge=1, le=10)
    job_result_retention_days: int = Field(default=7, ge=1, le=30)
    job_history_retention_days: int = Field(default=90, ge=31, le=730)
    maintenance_interval_seconds: int = Field(default=300, ge=10, le=86_400)
    attachment_upload_expiry_hours: int = Field(default=24, ge=1, le=168)
    artifact_retention_days: int = Field(default=7, ge=1, le=30)
    max_artifact_bytes: int = Field(default=52_428_800, ge=1_048_576, le=524_288_000)
    request_rate_limit: int = Field(default=180, ge=10, le=10_000)
    request_rate_window_seconds: int = Field(default=60, ge=1, le=3_600)
    rate_limit_trust_forwarded_for: bool = False
    metrics_api_key: str = "flowforge-local-metrics-key-change-before-production"
    storage_backend: Literal["local", "s3"] = "local"
    storage_local_path: str = ".flowforge-storage"
    storage_bucket: str = "flowforge-attachments"
    storage_endpoint_url: str | None = None
    storage_public_endpoint_url: str | None = None
    storage_region: str = "us-east-1"
    deployment_region: Literal[
        "us-central", "us-east", "us-west", "ca-central", "eu-central", "eu-west",
        "uk-south", "ap-southeast", "au-southeast",
    ] = "us-central"
    storage_access_key_id: str | None = None
    storage_secret_access_key: str | None = None
    storage_presign_seconds: int = Field(default=600, ge=60, le=3_600)
    storage_auto_create_bucket: bool = True
    attachment_scan_mode: Literal["disabled", "clamav"] = "disabled"
    clamav_host: str | None = None
    clamav_port: int = Field(default=3310, ge=1, le=65_535)
    clamav_timeout_seconds: float = Field(default=30.0, ge=1, le=300)
    auth_secret: str = "flowforge-local-development-secret-change-before-production"
    auth_session_days: int = 30
    auth_cookie_secure: bool = False
    internal_api_key: str = "flowforge-local-owner-key-change-before-production"
    frontend_url: str = "http://127.0.0.1:3000"
    invitation_expiry_days: int = 7
    email_delivery_mode: str = "console"
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_username: str | None = None
    smtp_password: str | None = None
    smtp_from_email: str = "FlowForge <no-reply@flowforge.local>"
    smtp_use_tls: bool = True

    @model_validator(mode="after")
    def validate_production_settings(self) -> "Settings":
        if self.environment.strip().lower() != "production":
            return self

        problems: list[str] = []
        if (
            len(self.auth_secret) < 32
            or "change-before-production" in self.auth_secret
            or self.auth_secret.startswith("replace-with")
        ):
            problems.append("FLOWFORGE_AUTH_SECRET must be a unique secret of at least 32 characters")
        if (
            len(self.internal_api_key) < 32
            or "change-before-production" in self.internal_api_key
            or self.internal_api_key.startswith("replace-with")
        ):
            problems.append("FLOWFORGE_INTERNAL_API_KEY must be a unique secret of at least 32 characters")
        if (
            len(self.metrics_api_key) < 32
            or "change-before-production" in self.metrics_api_key
            or self.metrics_api_key.startswith("replace-with")
        ):
            problems.append("FLOWFORGE_METRICS_API_KEY must be a unique secret of at least 32 characters")
        if (
            self.model_api_token == "local-model"
            or len(self.model_api_token) < 16
            or self.model_api_token.startswith("replace-with")
        ):
            problems.append("FLOWFORGE_MODEL_API_TOKEN must be replaced with a private token")
        if not self.auth_cookie_secure:
            problems.append("FLOWFORGE_AUTH_COOKIE_SECURE must be true")
        if not self.database_url.startswith("postgresql+asyncpg://"):
            problems.append("FLOWFORGE_DATABASE_URL must use PostgreSQL with the asyncpg driver")
        if (
            not self.redis_url
            or not self.redis_url.startswith(("redis://", "rediss://"))
            or "replace-with" in self.redis_url
        ):
            problems.append("FLOWFORGE_REDIS_URL must use a configured Redis connection URL")
        if self.embedded_worker_enabled:
            problems.append("FLOWFORGE_EMBEDDED_WORKER_ENABLED must be false in production")
        if self.storage_backend.lower() != "s3":
            problems.append("FLOWFORGE_STORAGE_BACKEND must be s3 in production")
        if not self.storage_bucket or self.storage_bucket.startswith("replace-with"):
            problems.append("FLOWFORGE_STORAGE_BUCKET must name a private object-storage bucket")
        if (
            not self.storage_public_endpoint_url
            or not self.storage_public_endpoint_url.startswith("https://")
        ):
            problems.append("FLOWFORGE_STORAGE_PUBLIC_ENDPOINT_URL must use HTTPS")
        if self.attachment_scan_mode.lower() != "clamav" or not self.clamav_host:
            problems.append("ClamAV attachment scanning must be configured in production")
        if not self.frontend_url.startswith("https://"):
            problems.append("FLOWFORGE_FRONTEND_URL must use HTTPS")
        if not self.cors_origins or any(not origin.startswith("https://") for origin in self.cors_origins):
            problems.append("FLOWFORGE_CORS_ORIGINS must contain only HTTPS origins")
        if self.email_delivery_mode.lower() != "smtp" or not self.smtp_host:
            problems.append("SMTP email delivery must be configured")
        if problems:
            raise ValueError("Invalid production configuration: " + "; ".join(problems))
        return self

    model_config = SettingsConfigDict(
        env_file=(".env", "backend/.env"),
        env_prefix="FLOWFORGE_",
        case_sensitive=False,
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
