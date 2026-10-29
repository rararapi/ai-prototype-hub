"""Shared HTTP metadata; behavior remains in the API adapter."""

from typing import Any

from fastapi import FastAPI

from protohub.domain.examples import EXAMPLES
from protohub.domain.models import (
    Health,
    HttpError,
    Operation,
    Sandbox,
    SandboxList,
    SystemInfo,
    TemplateList,
)

ROUTES: dict[str, tuple[str, str, Any, int]] = {
    "health": ("GET", "/healthz", Health, 200),
    "ready": ("GET", "/readyz", Health, 200),
    "system": ("GET", "/api/v1/system", SystemInfo, 200),
    "templates": ("GET", "/api/v1/templates", TemplateList, 200),
    "create_sandbox": ("POST", "/api/v1/sandboxes", Sandbox, 201),
    "list_sandboxes": ("GET", "/api/v1/sandboxes", SandboxList, 200),
    "get_sandbox": ("GET", "/api/v1/sandboxes/{sandbox_id}", Sandbox, 200),
    "start_sandbox": ("POST", "/api/v1/sandboxes/{sandbox_id}/start", Operation, 202),
    "stop_sandbox": ("POST", "/api/v1/sandboxes/{sandbox_id}/stop", Operation, 202),
    "delete_sandbox": ("DELETE", "/api/v1/sandboxes/{sandbox_id}", Operation, 202),
    "get_operation": ("GET", "/api/v1/operations/{operation_id}", Operation, 200),
}


def new_app() -> FastAPI:
    return FastAPI(title="ProtoHub", version="0.1.0", docs_url=None, redoc_url=None)


def route(app: FastAPI, name: str) -> Any:
    method, path, response_model, status = ROUTES[name]
    responses: dict[int | str, Any] = {}
    for code, message in {
        400: "Invalid request",
        403: "Local origin, host or client header rejected",
        404: "Resource not found",
        409: "State conflict",
        422: "Validation failed",
        503: "Dependency unavailable",
    }.items():
        responses[code] = {
            "model": HttpError,
            "description": message,
            "content": {
                "application/json": {
                    "example": {
                        "error": {
                            "code": "validation_error" if code == 422 else f"http_{code}",
                            "message": message,
                            "request_id": "00000000-0000-4000-8000-000000000001",
                        }
                    }
                }
            },
        }
    responses[status] = {"content": {"application/json": {"example": EXAMPLES[name]}}}
    extra = None
    if method in {"POST", "DELETE"}:
        extra = {
            "parameters": [
                {
                    "name": "X-ProtoHub-Client",
                    "in": "header",
                    "required": True,
                    "schema": {"type": "string", "enum": ["console"]},
                }
            ]
        }
    return app.api_route(
        path,
        methods=[method],
        response_model=response_model,
        status_code=status,
        operation_id=name,
        summary=name.replace("_", " ").title(),
        responses=responses,
        openapi_extra=extra,
    )
