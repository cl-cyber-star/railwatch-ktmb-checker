"""Environment-based configuration."""

from __future__ import annotations

from pydantic import AnyHttpUrl, Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Validated configuration loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    api_url: AnyHttpUrl = Field(alias="RAILWATCH_API_URL")
    checker_secret: SecretStr = Field(alias="RAILWATCH_CHECKER_SECRET")
    sites_authorization: SecretStr = Field(alias="OAI_SITES_AUTHORIZATION")
    ktmb_storage_state_b64: SecretStr | None = Field(
        default=None,
        alias="KTMB_STORAGE_STATE_B64",
    )
    session_api_path: str = Field(
        default="/api/checker/session",
        alias="RAILWATCH_SESSION_API_PATH",
    )
    http_timeout_seconds: float = Field(
        default=30.0,
        alias="RAILWATCH_HTTP_TIMEOUT_SECONDS",
        gt=0,
        le=120,
    )

    @field_validator("session_api_path")
    @classmethod
    def validate_session_path(cls, value: str) -> str:
        if not value.startswith("/") or value.startswith("//"):
            raise ValueError("must be an absolute URL path beginning with one slash")
        return value.rstrip("/") or "/"

    @property
    def api_base_url(self) -> str:
        return str(self.api_url).rstrip("/")

    @property
    def api_headers(self) -> dict[str, str]:
        return {
            "authorization": f"Bearer {self.checker_secret.get_secret_value()}",
            "content-type": "application/json",
            "OAI-Sites-Authorization": (f"Bearer {self.sites_authorization.get_secret_value()}"),
        }
