import json
from urllib.parse import urlsplit
from uuid import UUID, uuid4

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker
from starlette.concurrency import run_in_threadpool
from starlette.exceptions import HTTPException

from protohub.domain.http_contract import new_app, route
from protohub.domain.models import (
    Action,
    CreateSandbox,
    Health,
    LoginRequest,
    LogoutResult,
    SandboxList,
    ShareList,
    SystemInfo,
    Template,
    TemplateList,
)
from protohub.domain.settings import Settings
from protohub.persistence.auth import AuthenticationRequired, SessionRepository
from protohub.persistence.database import create_session_factory
from protohub.persistence.models import SandboxRow
from protohub.persistence.repository import Conflict, NotFound, SandboxRepository


def error_response(request: Request, status: int, code: str, message: str) -> JSONResponse:
    request_id = getattr(request.state, "request_id", uuid4())
    return JSONResponse(
        status_code=status,
        content={"error": {"code": code, "message": message, "request_id": str(request_id)}},
        headers={"X-Request-ID": str(request_id), "Cache-Control": "no-store"},
    )


def allowed_host(raw: str, hosts: list[str]) -> bool:
    if not raw or any(character in raw for character in "/\\@,\r\n\t "):
        return False
    try:
        parsed = urlsplit("//" + raw)
        # Accessing port also rejects invalid port syntax and range.
        _ = parsed.port
        return (
            parsed.hostname in hosts
            and not parsed.username
            and not parsed.password
            and not parsed.path
            and not parsed.query
            and not parsed.fragment
            and not raw.endswith(":")
        )
    except ValueError:
        return False


def create_app(
    settings: Settings | None = None, session_factory: sessionmaker[Session] | None = None
):
    config = settings or Settings()
    factory = session_factory or create_session_factory(config.database_url)
    repository = SandboxRepository(factory, config)
    sessions = SessionRepository(factory)
    application = new_app()
    application.state.settings = config
    application.state.session_factory = factory
    application.state.repository = repository
    application.state.sessions = sessions
    application.add_middleware(
        CORSMiddleware,
        allow_origins=[config.console_origin],
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "DELETE"],
        allow_headers=["Content-Type", "X-ProtoHub-Client", "Authorization"],
    )

    @application.middleware("http")
    async def local_boundary(request: Request, call_next):
        request.state.request_id = uuid4()
        if not allowed_host(request.headers.get("host", ""), config.allowed_hosts):
            return error_response(request, 403, "host_rejected", "Host is not allowed")
        origin = request.headers.get("origin")
        if origin is not None and origin != config.console_origin:
            return error_response(request, 403, "origin_rejected", "Origin is not allowed")
        if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
            if request.headers.get("x-protohub-client") != "console":
                return error_response(request, 403, "client_rejected", "Client header is required")
            media = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
            if media != "application/json":
                return error_response(request, 400, "json_required", "JSON content is required")
            body = await request.body()
            if len(body) > 65536:
                return error_response(request, 422, "validation_error", "Request is too large")
            try:
                payload = json.loads(body)
            except (ValueError, UnicodeDecodeError):
                return error_response(request, 422, "validation_error", "Invalid JSON request")
            if not isinstance(payload, dict):
                return error_response(request, 422, "validation_error", "JSON object is required")
            accepts_fields = request.url.path in {"/api/v1/sandboxes", "/api/v1/auth/login"} or (
                request.method == "PUT" and request.url.path.endswith("/shares")
            )
            if not accepts_fields and payload:
                return error_response(request, 422, "validation_error", "Unknown action fields")
        public_paths = {"/api/v1/system", "/api/v1/templates", "/api/v1/auth/login"}
        if (
            request.url.path.startswith("/api/v1/")
            and request.url.path not in public_paths
            and request.method != "OPTIONS"
        ):
            if not config.dev_login_enabled:
                return error_response(
                    request, 401, "login_disabled", "Development login is disabled"
                )
            try:
                request.state.principal = await run_in_threadpool(
                    sessions.authenticate, request.headers.get("authorization")
                )
            except AuthenticationRequired:
                return error_response(
                    request, 401, "login_required", "Development login is required"
                )
            except SQLAlchemyError:
                return error_response(
                    request, 503, "dependency_unavailable", "Database is unavailable"
                )
        response = await call_next(request)
        if request.url.path.startswith("/api/v1/"):
            response.headers["Cache-Control"] = "no-store"
        response.headers["X-Request-ID"] = str(request.state.request_id)
        return response

    @application.exception_handler(NotFound)
    async def not_found(request: Request, exc: NotFound):
        return error_response(request, 404, "not_found", "Resource not found")

    @application.exception_handler(Conflict)
    async def conflict(request: Request, exc: Conflict):
        return error_response(request, 409, "state_conflict", str(exc))

    @application.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):
        return error_response(request, 422, "validation_error", "Request validation failed")

    @application.exception_handler(SQLAlchemyError)
    async def unavailable(request: Request, exc: SQLAlchemyError):
        return error_response(request, 503, "dependency_unavailable", "Database is unavailable")

    @application.exception_handler(HTTPException)
    async def http_error(request: Request, exc: HTTPException):
        return error_response(
            request, exc.status_code, f"http_{exc.status_code}", "Request could not be handled"
        )

    @application.exception_handler(Exception)
    async def internal_error(request: Request, exc: Exception):
        return error_response(request, 500, "internal_error", "Internal request failure")

    @route(application, "health")
    def health():
        return Health()

    @route(application, "ready")
    def ready():
        with factory() as session:
            session.execute(select(SandboxRow.id).limit(1))
        return Health()

    @route(application, "system")
    def system():
        constraints = [
            "Trusted templates only",
            "Localhost only",
            "No production authentication",
            "No hostile-code isolation",
        ]
        if config.runtime_mode == "mock":
            constraints.append("Mock runtime does not start applications")
        return SystemInfo(
            runtime_mode=config.runtime_mode,
            auth_mode="local-dev" if config.dev_login_enabled else "disabled",
            constraints=constraints,
        )

    @route(application, "templates")
    def templates():
        return TemplateList(items=[Template()])

    @route(application, "login")
    def login(payload: LoginRequest):
        if not config.dev_login_enabled:
            raise HTTPException(status_code=404)
        return sessions.login(payload.email)

    @route(application, "me")
    def me(request: Request):
        return request.state.principal

    @route(application, "logout")
    def logout(request: Request):
        sessions.logout(request.headers.get("authorization"))
        return LogoutResult()

    @route(application, "get_shares")
    def get_shares(sandbox_id: UUID, request: Request):
        return repository.get_shares(sandbox_id, request.state.principal.email)

    @route(application, "set_shares")
    def set_shares(sandbox_id: UUID, payload: ShareList, request: Request):
        return repository.set_shares(sandbox_id, payload, request.state.principal.email)

    @route(application, "create_sandbox")
    def create_sandbox(payload: CreateSandbox, request: Request):
        return repository.create(payload, request.state.principal.email)

    @route(application, "list_sandboxes")
    def list_sandboxes(request: Request):
        return SandboxList(items=repository.list(request.state.principal.email))

    @route(application, "get_sandbox")
    def get_sandbox(sandbox_id: UUID, request: Request):
        return repository.get(sandbox_id, request.state.principal.email)

    @route(application, "start_sandbox")
    def start_sandbox(sandbox_id: UUID, request: Request):
        return repository.request(sandbox_id, Action.START, request.state.principal.email)

    @route(application, "stop_sandbox")
    def stop_sandbox(sandbox_id: UUID, request: Request):
        return repository.request(sandbox_id, Action.STOP, request.state.principal.email)

    @route(application, "delete_sandbox")
    def delete_sandbox(sandbox_id: UUID, request: Request):
        return repository.request(sandbox_id, Action.DELETE, request.state.principal.email)

    @route(application, "get_operation")
    def get_operation(operation_id: UUID, request: Request):
        return repository.get_operation(operation_id, request.state.principal.email)

    return application


app = create_app()
