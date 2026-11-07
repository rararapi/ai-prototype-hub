"""Coordinator-only contract authoring. Never run implicitly in verification."""

import json
from pathlib import Path
from uuid import UUID

from protohub.domain.http_contract import new_app, route
from protohub.domain.models import (
    AiConfirmRequest,
    AiCreateRequest,
    AiReviseRequest,
    CreateSandbox,
    GoogleLoginRequest,
    LoginRequest,
    ShareList,
)

app = new_app()


def no_input():
    raise NotImplementedError


def create_sandbox(payload: CreateSandbox):
    raise NotImplementedError


def sandbox(sandbox_id: UUID):
    raise NotImplementedError


def operation(operation_id: UUID):
    raise NotImplementedError


def login(payload: LoginRequest):
    raise NotImplementedError


def google_login(payload: GoogleLoginRequest):
    raise NotImplementedError


def shares(sandbox_id: UUID, payload: ShareList):
    raise NotImplementedError


for name in ("me", "logout", "health", "ready", "system", "templates", "list_sandboxes"):
    route(app, name)(no_input)
route(app, "create_sandbox")(create_sandbox)
for name in ("get_sandbox", "start_sandbox", "stop_sandbox", "delete_sandbox"):
    route(app, name)(sandbox)
route(app, "get_operation")(operation)
route(app, "login")(login)
route(app, "google_login")(google_login)
route(app, "get_shares")(sandbox)
route(app, "set_shares")(shares)


def ai_get(application_id: UUID):
    raise NotImplementedError


def ai_create(payload: AiCreateRequest):
    raise NotImplementedError


def ai_revise(application_id: UUID, payload: AiReviseRequest):
    raise NotImplementedError


def ai_confirm(application_id: UUID, payload: AiConfirmRequest):
    raise NotImplementedError


route(app, "ai_list")(no_input)
route(app, "ai_get")(ai_get)
route(app, "ai_create")(ai_create)
route(app, "ai_revise")(ai_revise)
route(app, "ai_confirm")(ai_confirm)
route(app, "ai_delete")(ai_get)

if __name__ == "__main__":
    Path(__file__).with_name("openapi.yaml").write_text(
        json.dumps(app.openapi(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
