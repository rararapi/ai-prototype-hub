"""Coordinator-only contract authoring. Never run implicitly in verification."""

import json
from pathlib import Path
from uuid import UUID

from protohub.domain.http_contract import new_app, route
from protohub.domain.models import CreateSandbox

app = new_app()


def no_input():
    raise NotImplementedError


def create_sandbox(payload: CreateSandbox):
    raise NotImplementedError


def sandbox(sandbox_id: UUID):
    raise NotImplementedError


def operation(operation_id: UUID):
    raise NotImplementedError


for name in ("health", "ready", "system", "templates", "list_sandboxes"):
    route(app, name)(no_input)
route(app, "create_sandbox")(create_sandbox)
for name in ("get_sandbox", "start_sandbox", "stop_sandbox", "delete_sandbox"):
    route(app, name)(sandbox)
route(app, "get_operation")(operation)

if __name__ == "__main__":
    Path(__file__).with_name("openapi.yaml").write_text(
        json.dumps(app.openapi(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
