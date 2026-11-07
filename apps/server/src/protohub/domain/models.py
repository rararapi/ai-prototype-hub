from datetime import datetime
from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class DesiredState(StrEnum):
    RUNNING = "running"
    STOPPED = "stopped"
    DELETED = "deleted"


class SandboxStatus(StrEnum):
    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    DELETING = "deleting"
    DELETED = "deleted"
    FAILED = "failed"


class OperationStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SUPERSEDED = "superseded"


class Action(StrEnum):
    START = "start"
    STOP = "stop"
    DELETE = "delete"


class DTO(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)


class Error(DTO):
    code: str
    message: str


class HttpErrorDetail(Error):
    request_id: UUID


class HttpError(DTO):
    error: HttpErrorDetail


class CreateSandbox(DTO):
    name: str = Field(min_length=1, max_length=64, pattern=r".*\S.*")
    template_id: Literal["hello-web"]
    ttl_seconds: int = Field(default=900, ge=60, le=3600, strict=True)


class Sandbox(DTO):
    owner_email: str | None = None
    id: UUID
    name: str
    template_id: Literal["hello-web"]
    desired_state: DesiredState
    status: SandboxStatus
    generation: int
    active_operation_id: UUID | None
    preview_url: str | None
    expires_at: datetime | None
    created_at: datetime
    updated_at: datetime
    error: Error | None


class Operation(DTO):
    id: UUID
    sandbox_id: UUID
    action: Action
    generation: int
    status: OperationStatus
    attempt_count: int
    created_at: datetime
    updated_at: datetime
    error: Error | None


class SandboxList(DTO):
    items: list[Sandbox]


class Template(DTO):
    id: Literal["hello-web"] = "hello-web"
    name: str = "Hello Web"
    description: str = "Trusted local HTTP sample"


class TemplateList(DTO):
    items: list[Template]


class SystemInfo(DTO):
    runtime_mode: Literal["mock", "real-kind"]
    auth_mode: Literal["local-dev", "google", "disabled"] = "local-dev"
    google_client_id: str | None = None
    preview_origin: str | None = None
    constraints: list[str]
    ai_enabled: bool = False
    ai_model: str | None = None


class Health(DTO):
    status: Literal["ok"] = "ok"


class LoginRequest(DTO):
    email: str = Field(min_length=3, max_length=254)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        import re

        value = value.strip().lower()
        pattern = (
            r"[a-z0-9.!#$%&'*+/=?^_`{|}~-]+@"
            r"[a-z0-9](?:[a-z0-9-]*[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]*[a-z0-9])?)+"
        )
        if not re.fullmatch(pattern, value):
            raise ValueError("Enter a valid email address")
        return value


class GoogleLoginRequest(DTO):
    code: str = Field(min_length=1, max_length=4096, pattern=r"^[!-~]+$")


class Principal(DTO):
    email: str


class LoginSession(DTO):
    token: str
    email: str
    expires_at: datetime


class LogoutResult(DTO):
    status: Literal["ok"] = "ok"


class ShareList(DTO):
    emails: list[str] = Field(default_factory=list, max_length=100)

    @field_validator("emails")
    @classmethod
    def normalize_emails(cls, values: list[str]) -> list[str]:
        return sorted({LoginRequest(email=value).email for value in values})


class AiBrief(DTO):
    model_config = ConfigDict(str_strip_whitespace=True)

    purpose: str = Field(min_length=1, max_length=300)
    audience: str = Field(min_length=1, max_length=300)
    success: str = Field(min_length=1, max_length=300)


class AiConfig(DTO):
    model_config = ConfigDict(str_strip_whitespace=True)

    template: Literal["hello-web", "management-dashboard"]
    title: str = Field(min_length=1, max_length=64)
    subtitle: str = Field(max_length=160)
    color: Literal["purple", "blue", "green"]
    trend: bool = Field(strict=True)
    departments: bool = Field(strict=True)
    cash_flow: bool = Field(strict=True)

    @model_validator(mode="after")
    def applicable_features(self) -> "AiConfig":
        if self.template == "hello-web" and (self.trend or self.departments or self.cash_flow):
            raise ValueError("Dashboard options require the management dashboard")
        return self


class AiUsage(DTO):
    input_tokens: int = Field(ge=0, strict=True)
    output_tokens: int = Field(ge=0, strict=True)


class AiApplication(DTO):
    id: UUID
    brief: AiBrief
    config: AiConfig
    summary: str = Field(max_length=1000)
    model: str
    status: Literal["draft", "ready"]
    revision: int = Field(ge=1)
    usage: AiUsage | None
    created_at: datetime
    updated_at: datetime


class AiApplicationList(DTO):
    items: list[AiApplication]


class AiCreateRequest(DTO):
    request_id: UUID
    brief: AiBrief
    config: AiConfig
    instruction: str = Field(default="", max_length=1000)


class AiReviseRequest(DTO):
    model_config = ConfigDict(str_strip_whitespace=True)

    request_id: UUID
    expected_revision: int = Field(ge=1, strict=True)
    instruction: str = Field(min_length=1, max_length=1000)


class AiConfirmRequest(DTO):
    expected_revision: int = Field(ge=1, strict=True)
