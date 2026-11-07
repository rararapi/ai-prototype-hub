from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient

from protohub.domain.models import DesiredState, Principal, SandboxStatus
from protohub.domain.settings import Settings
from protohub.persistence.auth import AuthenticationRequired
from protohub.persistence.repository import NotFound
from protohub.preview import create_app


@pytest.fixture
def registered():
    sandbox = SimpleNamespace(
        id=uuid4(),
        generation=1,
        template_id="hello-web",
        desired_state=DesiredState.RUNNING,
        status=SandboxStatus.RUNNING,
    )
    members = {
        "owner": "owner@example.test",
        "reader": "reader@example.test",
        "outsider": "outsider@example.test",
    }
    visible = {members["owner"], members["reader"]}

    def authenticate(header, *, google):
        assert google is True
        if header not in {f"Bearer {key}" for key in members}:
            raise AuthenticationRequired
        return Principal(email=members[header.removeprefix("Bearer ")])

    def get(sandbox_id, principal):
        if sandbox_id != sandbox.id or principal not in visible:
            raise NotFound
        return sandbox

    upstream_requests = []

    def serve(request):
        upstream_requests.append(request)
        return httpx.Response(200, text="sample", headers={"Set-Cookie": "sample=upstream; Path=/"})

    # Match the configured environment read by preview, with no Google client secret in this pod.
    config = Settings(runtime_mode="real-kind", environment="production", google_login=True)
    client = TestClient(
        create_app(
            config,
            SimpleNamespace(get=get),
            httpx.Client(transport=httpx.MockTransport(serve)),
            SimpleNamespace(authenticate=authenticate),
        ),
        base_url="http://localhost",
    )
    return client, sandbox, visible, upstream_requests


@pytest.mark.parametrize("method", ["GET", "HEAD"])
@pytest.mark.parametrize("path", ["", "healthz", "asset.css"])
def test_all_google_sample_paths_require_a_current_visible_principal(registered, method, path):
    client, sandbox, visible, calls = registered
    url = f"/apps/{sandbox.id}/{path}"
    for token, status in [(None, 401), ("expired", 401), ("outsider", 404)]:
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        response = client.request(method, url, headers=headers)
        assert response.status_code == status and response.headers["cache-control"] == "no-store"
    assert calls == []
    for token in ("owner", "reader"):
        response = client.request(
            method,
            url,
            headers={
                "Authorization": f"Bearer {token}",
                "Cookie": "console=private",
                "Origin": "http://localhost:8080",
            },
        )
        assert response.status_code == 200
        assert response.headers["access-control-allow-origin"] == "http://localhost:8080"
        assert "set-cookie" not in response.headers
    assert len(calls) == 2
    assert all("cookie" not in r.headers and "authorization" not in r.headers for r in calls)
    visible.remove("reader@example.test")
    assert (
        client.request(method, url, headers={"Authorization": "Bearer reader"}).status_code == 404
    )
    assert len(calls) == 2


def test_registered_preview_exact_origin_and_preflight(registered):
    client, sandbox, _, calls = registered
    url = f"/apps/{sandbox.id}/"
    headers = {
        "Origin": "http://localhost:8080",
        "Access-Control-Request-Method": "GET",
        "Access-Control-Request-Headers": "authorization",
    }
    response = client.options(url, headers=headers)
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == headers["Origin"]
    assert "access-control-allow-credentials" not in response.headers
    for origin in ("http://localhost:9999", "null"):
        assert client.options(url, headers={**headers, "Origin": origin}).status_code == 403
        assert (
            client.get(url, headers={"Origin": origin, "Authorization": "Bearer owner"}).status_code
            == 403
        )
    assert calls == []
    assert client.get("/healthz").status_code == 200


def test_production_without_google_has_no_preview():
    repository = Mock()
    client = TestClient(
        create_app(Settings(environment="production", runtime_mode="real-kind"), repository),
        base_url="http://localhost",
    )
    assert client.get(f"/apps/{uuid4()}/").status_code == 403
    repository.get.assert_not_called()
