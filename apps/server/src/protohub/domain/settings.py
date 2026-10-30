from typing import Literal

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
