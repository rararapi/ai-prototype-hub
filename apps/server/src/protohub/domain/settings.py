import re
from typing import Literal
from uuid import UUID

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="PROTOHUB_", extra="ignore")
    database_url: str = "postgresql+psycopg://protohub:local-dev@db/protohub"
    runtime_mode: Literal["mock", "real-kind"] = "mock"
    console_origin: str = "http://localhost:8080"
    preview_origin: str = "http://localhost:8081"
    allowed_hosts: list[str] = ["localhost", "127.0.0.1"]
    sample_namespace: str = "protohub-samples"
    sample_image: str = "protohub/hello-web:dev"
    lease_seconds: int = 30
    operation_timeout_seconds: int = 90
    poll_interval_seconds: float = 0.5
    max_attempts: int = 3

    environment: Literal["local", "development", "test", "production"] = "local"
    google_login: bool = False
    google_client_id: str | None = None
    google_client_secret: SecretStr | None = None
    llm_api_key: SecretStr | None = None

    ai_enabled: bool = False
    ai_model: str = Field(default="gemini-3.5-flash-lite", pattern=r"^gemini-[a-z0-9.-]{1,110}$")
    ai_vertex_project: str | None = Field(default=None, pattern=r"^[a-z][a-z0-9-]{4,61}[a-z0-9]$")
    ai_vertex_location: str = Field(default="global", pattern=r"^(global|[a-z]+-[a-z]+[0-9])$")
    ai_timeout_seconds: int = Field(default=20, ge=1, le=40)
    ai_max_output_tokens: int = Field(default=2048, ge=256, le=4096)
    ai_hourly_limit: int = Field(default=5, ge=1, le=100)
    ai_daily_limit: int = Field(default=10, ge=1, le=1000)
    ai_global_daily_limit: int = Field(default=30, ge=1, le=10000)

    @property
    def ai_ready(self) -> bool:
        return bool(self.ai_enabled and self.ai_vertex_project)

    @property
    def dev_login_enabled(self) -> bool:
        return not self.google_login and self.environment in {"local", "development", "test"}

    @property
    def google_ready(self) -> bool:
        return bool(
            self.google_login
            and len(self.google_client_id or "") <= 512
            and re.fullmatch(
                r"[a-zA-Z0-9_-]+\.apps\.googleusercontent\.com", self.google_client_id or ""
            )
            and self.google_client_secret
            and self.google_client_secret.get_secret_value().strip()
        )

    def resolve_llm_api_key(self, sandbox_id: UUID | None = None) -> SecretStr | None:
        """All apps use the server key; per-app overrides are a future extension."""
        return self.llm_api_key
