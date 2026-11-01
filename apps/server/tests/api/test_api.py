from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from protohub.api.main import create_app
from protohub.domain.models import Action, SandboxStatus
from protohub.domain.ports import Observation
from protohub.persistence.models import OperationRow, SandboxRow

HEADERS = {"X-ProtoHub-Client": "console", "Origin": "http://localhost:8080"}
PAYLOAD = {"name": "First app", "template_id": "hello-web", "ttl_seconds": 60}


def login(client):
    response = client.post(
        "/api/v1/auth/login", json={"email": "owner@example.test"}, headers=HEADERS
    )
    assert response.status_code == 200
    client.headers["Authorization"] = "Bearer " + response.json()["token"]


def register(client, **overrides):
    response = client.post("/api/v1/sandboxes", json={**PAYLOAD, **overrides}, headers=HEADERS)
    assert response.status_code == 201
    return response.json()


def action(client, sandbox_id, operation):
    if operation == "delete":
        return client.request("DELETE", f"/api/v1/sandboxes/{sandbox_id}", json={}, headers=HEADERS)
    return client.post(f"/api/v1/sandboxes/{sandbox_id}/{operation}", json={}, headers=HEADERS)


def test_health_templates_mode_and_empty_list(client):
    assert client.get("/healthz").json() == {"status": "ok"}
    assert client.get("/readyz").status_code == 200
    assert client.get("/api/v1/sandboxes").json() == {"items": []}
    assert client.get("/api/v1/templates").json()["items"][0]["id"] == "hello-web"
    assert client.get("/api/v1/system").json()["runtime_mode"] == "mock"
    assert client.get("/api/v1/system").json()["auth_mode"] == "local-dev"


def test_register_only_persists_stopped(client, factory):
    sandbox = register(client)
    assert sandbox["status"] == "stopped"
    assert sandbox["desired_state"] == "stopped"
    assert sandbox["generation"] == 0
    assert sandbox["preview_url"] is None
    assert sandbox["expires_at"] is None
    assert sandbox["created_at"].endswith("Z")
    assert client.get(f"/api/v1/sandboxes/{sandbox['id']}").json() == sandbox
    with factory() as session:
        assert session.get(SandboxRow, UUID(sandbox["id"])) is not None
        assert session.query(OperationRow).count() == 0


@pytest.mark.parametrize(
    "overrides",
    [
        {"template_id": "arbitrary-image"},
        {"name": ""},
        {"name": "  "},
        {"name": "a" * 65},
        {"ttl_seconds": 59},
        {"ttl_seconds": 3601},
        {"ttl_seconds": True},
        {"ttl_seconds": "60"},
        {"image": "private.invalid/image"},
        {"env": {"TOKEN": "synthetic-sensitive-value"}},
    ],
)
def test_validation_sanitizes_and_rejects_unknown_fields(client, overrides):
    response = client.post("/api/v1/sandboxes", json={**PAYLOAD, **overrides}, headers=HEADERS)
    assert response.status_code == 422
    body = response.json()
    assert set(body) == {"error"}
    assert body["error"]["code"] == "validation_error"
    assert UUID(body["error"]["request_id"])
    assert "synthetic-sensitive-value" not in response.text


def test_start_is_async_and_duplicate_returns_same_operation(client, factory):
    sandbox = register(client)
    first = action(client, sandbox["id"], "start")
    second = action(client, sandbox["id"], "start")
    assert first.status_code == second.status_code == 202
    assert first.json()["status"] == "queued"
    assert first.json()["id"] == second.json()["id"]
    current = client.get(f"/api/v1/sandboxes/{sandbox['id']}").json()
    assert current["status"] == "starting"
    assert current["generation"] == 1
    assert current["preview_url"] is None
    with factory() as session:
        assert session.query(OperationRow).count() == 1


def test_new_stop_supersedes_start_and_delete_is_idempotent(client):
    sandbox = register(client)
    start = action(client, sandbox["id"], "start").json()
    stop = action(client, sandbox["id"], "stop").json()
    assert stop["generation"] == start["generation"] + 1
    assert client.get(f"/api/v1/operations/{start['id']}").json()["status"] == "superseded"
    deleted = action(client, sandbox["id"], "delete").json()
    assert action(client, sandbox["id"], "delete").json()["id"] == deleted["id"]
    assert client.get("/api/v1/sandboxes").json() == {"items": []}
    assert action(client, sandbox["id"], "start").status_code == 409
    assert action(client, sandbox["id"], "stop").status_code == 409
    assert client.get(f"/api/v1/sandboxes/{sandbox['id']}").status_code == 200


def test_two_apps_do_not_share_intent(client):
    first, second = register(client), register(client, name="Second app")
    action(client, first["id"], "delete")
    assert client.get(f"/api/v1/sandboxes/{second['id']}").json()["status"] == "stopped"


def test_404_uuid_validation_and_error_shape(client):
    for path, status in [
        (f"/api/v1/sandboxes/{uuid4()}", 404),
        (f"/api/v1/operations/{uuid4()}", 404),
        ("/api/v1/sandboxes/not-a-uuid", 422),
        ("/unknown", 404),
    ]:
        response = client.get(path)
        assert response.status_code == status
        assert UUID(response.json()["error"]["request_id"])


@pytest.mark.parametrize(
    "host",
    [
        "attacker.invalid",
        "localhost.attacker.invalid",
        "localhost@attacker.invalid",
        "localhost:bad",
        "localhost.",
    ],
)
def test_host_rejected_even_with_forwarded_host(client, host):
    response = client.get("/healthz", headers={"Host": host, "X-Forwarded-Host": "localhost"})
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "host_rejected"


def test_origin_custom_header_and_json_guards(client):
    assert client.post("/api/v1/sandboxes", json=PAYLOAD).status_code == 403
    assert (
        client.post(
            "/api/v1/sandboxes",
            json=PAYLOAD,
            headers={**HEADERS, "Origin": "http://attacker.invalid"},
        ).status_code
        == 403
    )
    assert client.post("/api/v1/sandboxes", content="name=a", headers=HEADERS).status_code == 400
    bad_json = client.post(
        "/api/v1/sandboxes", content="{", headers={**HEADERS, "Content-Type": "application/json"}
    )
    assert bad_json.status_code == 422
    assert client.post("/api/v1/sandboxes", json=[], headers=HEADERS).status_code == 422
    sandbox = register(client)
    assert (
        client.post(
            f"/api/v1/sandboxes/{sandbox['id']}/start", json={"url": "http://x"}, headers=HEADERS
        ).status_code
        == 422
    )


def test_cors_has_exact_origin(client):
    response = client.options(
        "/api/v1/sandboxes",
        headers={
            "Origin": "http://localhost:8080",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "X-ProtoHub-Client,Content-Type",
        },
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:8080"
    assert "access-control-allow-credentials" not in response.headers
    assert (
        client.options(
            "/api/v1/sandboxes", headers={"Origin": "null", "Access-Control-Request-Method": "POST"}
        ).status_code
        == 403
    )


def test_api_restart_keeps_records_and_readiness_fails_without_schema(factory, settings):
    with TestClient(create_app(settings, factory), base_url="http://localhost") as first:
        login(first)
        token_header = first.headers["Authorization"]
        sandbox = register(first)
    with TestClient(create_app(settings, factory), base_url="http://localhost") as second:
        second.headers["Authorization"] = token_header
        assert second.get(f"/api/v1/sandboxes/{sandbox['id']}").status_code == 200
    from protohub.persistence.database import create_session_factory

    empty_factory = create_session_factory("sqlite://")
    with TestClient(create_app(settings, empty_factory), base_url="http://localhost") as missing:
        response = missing.get("/readyz")
        assert response.status_code == 503
        assert "sqlite" not in response.text
        assert "Database is unavailable" in response.text
    empty_factory.kw["bind"].dispose()


def test_unexpected_error_is_sanitized(factory, settings, monkeypatch):
    app = create_app(settings, factory)

    def broken():
        raise RuntimeError("synthetic-sensitive-internal-detail")

    monkeypatch.setattr(app.state.repository, "list", broken)
    with TestClient(app, base_url="http://localhost", raise_server_exceptions=False) as client:
        login(client)
        response = client.get("/api/v1/sandboxes")
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "internal_error"
    assert "synthetic-sensitive-internal-detail" not in response.text


def test_mock_complete_never_exposes_preview(client, factory, settings):
    from protohub.persistence.jobs import SqlJobStore

    sandbox = register(client)
    action(client, sandbox["id"], "start")
    jobs = SqlJobStore(factory, settings)
    claim = jobs.claim("test")
    assert claim is not None and claim.action == Action.START
    assert jobs.complete(claim, Observation(SandboxStatus.RUNNING, "http://fake.invalid"))
    assert client.get(f"/api/v1/sandboxes/{sandbox['id']}").json()["preview_url"] is None


@pytest.mark.parametrize("host", ["localhost#invalid", "localhost?invalid", "localhost:"])
def test_host_must_be_a_bare_authority(client, host):
    assert client.get("/api/v1/system", headers={"Host": host}).status_code == 403
