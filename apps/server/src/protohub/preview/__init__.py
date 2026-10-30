"""HTTP preview for the fixed sample only. No arbitrary upstreams or credentials."""

import re
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response

from protohub.domain.models import DesiredState, SandboxStatus
from protohub.domain.ports import RuntimeSpec
from protohub.domain.settings import Settings
from protohub.runtime.kubernetes import sample_url

MAX_RESPONSE = 1024 * 1024


def create_app(
    settings: Settings | None = None, repository: Any = None, http: httpx.Client | None = None
) -> FastAPI:
    settings = settings or Settings()
    if repository is None:
        from protohub.persistence.database import create_session_factory
        from protohub.persistence.repository import SandboxRepository

        repository = SandboxRepository(create_session_factory(settings.database_url), settings)
    upstream = http or httpx.Client(timeout=5, follow_redirects=False, trust_env=False)
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

    @app.middleware("http")
    async def boundary(request: Request, call_next: Any) -> Response:
        host = request.headers.get("host", "")
        try:
            parsed = urlsplit("http://" + host)
            allowed = parsed.hostname in settings.allowed_hosts and not parsed.username
            allowed = (
                allowed
                and not parsed.password
                and not parsed.path
                and not parsed.query
                and not parsed.fragment
                and not host.endswith(":")
            )
            _ = parsed.port
        except ValueError:
            allowed = False
        if not allowed or "@" in host or "\\" in host:
            return JSONResponse({"error": "preview_host_rejected"}, status_code=403)
        if request.method not in {"GET", "HEAD"}:
            return JSONResponse({"error": "preview_method_rejected"}, status_code=405)
        return await call_next(request)

    @app.api_route("/healthz", methods=["GET", "HEAD"])
    def health() -> Response:
        return Response("ok", media_type="text/plain")

    @app.api_route("/apps/{sandbox_id}/", methods=["GET", "HEAD"])
    @app.api_route("/apps/{sandbox_id}/{path:path}", methods=["GET", "HEAD"])
    def preview(request: Request, sandbox_id: UUID, path: str = "") -> Response:
        raw_path = request.scope.get("raw_path", b"")
        if (
            request.url.query
            or b"%" in raw_path
            or not re.fullmatch(r"[A-Za-z0-9_./-]*", path)
            or any(segment in {".", ".."} for segment in path.split("/"))
            or "//" in path
            or path.startswith("/")
        ):
            return JSONResponse({"error": "preview_path_rejected"}, status_code=400)
        if settings.runtime_mode != "real-kind":
            return JSONResponse({"error": "mock_has_no_preview"}, status_code=404)
        try:
            sandbox = repository.get(sandbox_id)
        except Exception:
            return JSONResponse({"error": "preview_not_available"}, status_code=404)
        if (
            sandbox.desired_state != DesiredState.RUNNING
            or sandbox.status != SandboxStatus.RUNNING
            or sandbox.template_id != "hello-web"
        ):
            return JSONResponse({"error": "preview_not_ready"}, status_code=404)
        url = sample_url(settings, RuntimeSpec(sandbox.id, sandbox.generation), "/" + path)
        try:
            # Rebuild request headers, never copy Cookie/Authorization/Host/X-Forwarded-*.
            with upstream.stream(request.method, url, headers={"Accept": "*/*"}) as result:
                if 300 <= result.status_code < 400:
                    return JSONResponse({"error": "preview_redirect_rejected"}, status_code=502)
                body = bytearray()
                for chunk in result.iter_bytes():
                    body.extend(chunk)
                    if len(body) > MAX_RESPONSE:
                        return JSONResponse(
                            {"error": "preview_response_too_large"}, status_code=502
                        )
                return Response(
                    bytes(body) if request.method == "GET" else b"",
                    status_code=result.status_code,
                    headers={
                        "Content-Type": result.headers.get("content-type", "text/plain"),
                        "Cache-Control": "no-store",
                        "X-Content-Type-Options": "nosniff",
                        "Referrer-Policy": "no-referrer",
                    },
                )
        except httpx.HTTPError:
            return JSONResponse({"error": "preview_upstream_unavailable"}, status_code=502)

    return app
