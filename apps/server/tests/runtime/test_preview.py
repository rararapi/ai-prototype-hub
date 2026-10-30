from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient

from protohub.domain.models import DesiredState, SandboxStatus
from protohub.domain.settings import Settings
from protohub.preview import create_app


@pytest.fixture
def setup_preview():
    sandbox = SimpleNamespace(
        id=uuid4(),
        generation=1,
        template_id="hello-web",
        desired_state=DesiredState.RUNNING,
        status=SandboxStatus.RUNNING,
    )
    repository = SimpleNamespace(get=lambda _: sandbox)
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, text="Hello ProtoHub", headers={"set-cookie": "private=value"})

    http = httpx.Client(transport=httpx.MockTransport(handler))
    client = TestClient(
        create_app(Settings(runtime_mode="real-kind"), repository, http),
        base_url="http://localhost",
    )
    return client, sandbox, requests


def test_fixed_upstream_strips_cookie_authorization_and_forwarded_headers(setup_preview):
    client, sandbox, requests = setup_preview
    response = client.get(
        f"/apps/{sandbox.id}/",
        headers={
            "Cookie": "session=private",
            "Authorization": "Bearer private",
            "X-Forwarded-Host": "attacker.invalid",
        },
    )
    assert response.status_code == 200 and response.text == "Hello ProtoHub"
    assert "set-cookie" not in response.headers
    assert requests[0].url.host == f"sandbox-{sandbox.id.hex}.protohub-samples.svc.cluster.local"
    assert "authorization" not in requests[0].headers and "cookie" not in requests[0].headers
    assert "x-forwarded-host" not in requests[0].headers


def test_unknown_host_methods_and_unsafe_paths_rejected(setup_preview):
    client, sandbox, requests = setup_preview
    assert (
        client.get(f"/apps/{sandbox.id}/", headers={"Host": "attacker.invalid"}).status_code == 403
    )
    assert client.post(f"/apps/{sandbox.id}/").status_code == 405
    for suffix in ("?url=http://example.invalid", "%2f%2fexample.invalid", "a//b", "a/%2e%2e/b"):
        assert client.get(f"/apps/{sandbox.id}/{suffix}").status_code == 400
    assert requests == []


@pytest.mark.parametrize("host", ["localhost#invalid", "localhost?invalid", "localhost:"])
def test_preview_rejects_malformed_host_authority(setup_preview, host):
    client, sandbox, requests = setup_preview
    assert client.get(f"/apps/{sandbox.id}/", headers={"Host": host}).status_code == 403
    assert requests == []


def test_mock_stopped_deleted_and_failed_have_no_route(setup_preview):
    client, sandbox, requests = setup_preview
    for status in (SandboxStatus.STOPPED, SandboxStatus.DELETED, SandboxStatus.FAILED):
        sandbox.status = status
        assert client.get(f"/apps/{sandbox.id}/").status_code == 404
    mock = TestClient(
        create_app(Settings(runtime_mode="mock"), SimpleNamespace(get=lambda _: sandbox)),
        base_url="http://localhost",
    )
    assert mock.get(f"/apps/{sandbox.id}/").status_code == 404
    assert requests == []


def test_redirects_rejected_without_following_and_head_supported(setup_preview):
    client, sandbox, requests = setup_preview
    assert client.head(f"/apps/{sandbox.id}/").status_code == 200
    assert client.head(f"/apps/{sandbox.id}/").content == b""
    http = httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(302, headers={"location": "http://example.invalid"})
        )
    )
    redirected = TestClient(
        create_app(
            Settings(runtime_mode="real-kind"), SimpleNamespace(get=lambda _: sandbox), http
        ),
        base_url="http://localhost",
    )
    response = redirected.get(f"/apps/{sandbox.id}/")
    assert response.status_code == 502 and "location" not in response.headers
