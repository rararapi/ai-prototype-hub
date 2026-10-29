from datetime import datetime
from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


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
    auth_mode: Literal["local-dev"] = "local-dev"
    constraints: list[str]


class Health(DTO):
    status: Literal["ok"] = "ok"
