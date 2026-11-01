from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from protohub.api.main import create_app
from protohub.domain.models import CreateSandbox
from protohub.persistence.models import SessionRow, UserRow
from protohub.persistence.repository import SandboxRepository

HEADERS = {"X-ProtoHub-Client": "console", "Origin": "http://localhost:8080"}
PAYLOAD = {"name": "Private app", "template_id": "hello-web"}


def login(client, email="owner@example.test"):
    result = client.post("/api/v1/auth/login", json={"email": email}, headers=HEADERS)
    assert result.status_code == 200
    client.headers["Authorization"] = "Bearer " + result.json()["token"]
    return result


@pytest.fixture
def raw_client(factory, settings):
    with TestClient(create_app(settings, factory), base_url="http://localhost") as client:
        yield client


def create(client):
    response = client.post("/api/v1/sandboxes", json=PAYLOAD, headers=HEADERS)
    assert response.status_code == 201
    return response.json()


def shares(client, sandbox_id, emails):
    return client.put(
        f"/api/v1/sandboxes/{sandbox_id}/shares", json={"emails": emails}, headers=HEADERS
    )


def test_no_session_and_spoofed_identity_headers_do_not_grant_access(raw_client):
    for headers in ({}, {"X-User-Email": "owner@example.test"}, {"Authorization": "Bearer forged"}):
        response = raw_client.get("/api/v1/sandboxes", headers=headers)
        assert response.status_code == 401
        assert response.headers["Cache-Control"] == "no-store"
        assert response.json()["error"]["code"] == "login_required"
    assert raw_client.post("/api/v1/sandboxes", json=PAYLOAD, headers=HEADERS).status_code == 401
    assert raw_client.get("/api/v1/auth/me").status_code == 401


def test_login_normalizes_email_and_persists_only_hashed_tokens(raw_client, factory):
    result = login(raw_client, " Owner@Example.Test ")
    session = result.json()
    assert session["email"] == "owner@example.test"
    assert len(session["token"]) == 43
    assert result.headers["Cache-Control"] == "no-store"
    assert "set-cookie" not in result.headers
    assert raw_client.get("/api/v1/auth/me").json() == {"email": "owner@example.test"}
    with factory() as database:
        stored = database.scalar(select(SessionRow))
        assert stored.token_digest != session["token"]
        assert len(stored.token_digest) == 64
        assert database.get(UserRow, "owner@example.test") is not None
        duration = stored.expires_at - stored.created_at
        assert duration == timedelta(hours=24)
    login(raw_client, "owner@example.test")
    with factory() as database:
        assert len(list(database.scalars(select(UserRow)))) == 1
        assert len(list(database.scalars(select(SessionRow)))) == 2


@pytest.mark.parametrize(
    "email",
    [
        "",
        "not-an-email",
        "a@",
        "a@b",
        "a b@example.test",
        "a@example..test",
        "a\n@example.test",
        "a" * 255,
    ],
)
def test_login_rejects_invalid_email_without_echoing_input(raw_client, email):
    response = raw_client.post("/api/v1/auth/login", json={"email": email}, headers=HEADERS)
    assert response.status_code == 422
    assert response.json()["error"]["message"] == "Request validation failed"


def test_login_rejects_unknown_fields_and_origin_bypass(raw_client):
    assert (
        raw_client.post(
            "/api/v1/auth/login",
            json={"email": "owner@example.test", "admin": True},
            headers=HEADERS,
        ).status_code
        == 422
    )
    assert (
        raw_client.post("/api/v1/auth/login", json={"email": "owner@example.test"}).status_code
        == 403
    )
    assert (
        raw_client.post(
            "/api/v1/auth/login",
            json={"email": "owner@example.test"},
            headers={**HEADERS, "Origin": "http://attacker.invalid"},
        ).status_code
        == 403
    )


def test_expiry_is_enforced_at_boundary_and_logout_revokes(raw_client):
    now = datetime(2026, 11, 1, tzinfo=UTC)
    raw_client.app.state.sessions.clock = lambda: now
    first = login(raw_client).json()
    assert raw_client.get("/api/v1/auth/me").status_code == 200
    now += timedelta(hours=24)
    assert raw_client.get("/api/v1/auth/me").status_code == 401
    second = login(raw_client).json()
    assert first["token"] != second["token"]
    assert raw_client.post("/api/v1/auth/logout", json={}, headers=HEADERS).status_code == 200
    assert raw_client.get("/api/v1/sandboxes").status_code == 401


def test_email_login_is_disabled_in_production(factory, settings):
    settings.environment = "production"
    with TestClient(create_app(settings, factory), base_url="http://localhost") as client:
        assert client.get("/api/v1/system").json()["auth_mode"] == "disabled"
        assert (
            client.post(
                "/api/v1/auth/login", json={"email": "owner@example.test"}, headers=HEADERS
            ).status_code
            == 404
        )
        protected = client.get("/api/v1/sandboxes")
        assert protected.status_code == 401
        assert protected.json()["error"]["code"] == "login_disabled"


def test_visibility_shares_and_revocation_cover_details_and_operations(
    raw_client, factory, settings
):
    login(raw_client)
    sandbox = create(raw_client)
    sandbox_id = sandbox["id"]
    assert sandbox["owner_email"] == "owner@example.test"
    operation = raw_client.post(
        f"/api/v1/sandboxes/{sandbox_id}/start", json={}, headers=HEADERS
    ).json()
    assert shares(
        raw_client, sandbox_id, [" Reader@Example.Test ", "reader@example.test"]
    ).json() == {"emails": ["reader@example.test"]}
    assert raw_client.get(f"/api/v1/sandboxes/{sandbox_id}/shares").json() == {
        "emails": ["reader@example.test"]
    }
    login(raw_client, "reader@example.test")
    assert [item["id"] for item in raw_client.get("/api/v1/sandboxes").json()["items"]] == [
        sandbox_id
    ]
    assert raw_client.get(f"/api/v1/sandboxes/{sandbox_id}").status_code == 200
    assert raw_client.get(f"/api/v1/operations/{operation['id']}").status_code == 200
    own = create(raw_client)
    assert own["owner_email"] == "reader@example.test"
    for method, path in [
        ("POST", f"/api/v1/sandboxes/{sandbox_id}/start"),
        ("POST", f"/api/v1/sandboxes/{sandbox_id}/stop"),
        ("DELETE", f"/api/v1/sandboxes/{sandbox_id}"),
    ]:
        assert raw_client.request(method, path, json={}, headers=HEADERS).status_code == 404
    assert raw_client.get(f"/api/v1/sandboxes/{sandbox_id}/shares").status_code == 404
    assert shares(raw_client, sandbox_id, []).status_code == 404
    login(raw_client, "stranger@example.test")
    assert raw_client.get("/api/v1/sandboxes").json() == {"items": []}
    assert raw_client.get(f"/api/v1/sandboxes/{sandbox_id}").status_code == 404
    assert raw_client.get(f"/api/v1/operations/{operation['id']}").status_code == 404
    login(raw_client)
    assert shares(raw_client, sandbox_id, []).json() == {"emails": []}
    login(raw_client, "reader@example.test")
    assert [item["id"] for item in raw_client.get("/api/v1/sandboxes").json()["items"]] == [
        own["id"]
    ]
    assert raw_client.get(f"/api/v1/sandboxes/{sandbox_id}").status_code == 404
    assert raw_client.get(f"/api/v1/operations/{operation['id']}").status_code == 404
    # Internal worker-created/legacy rows are retained but never adopted by a login.
    legacy = SandboxRepository(factory, settings).create(
        CreateSandbox(name="Legacy", template_id="hello-web")
    )
    assert raw_client.get(f"/api/v1/sandboxes/{legacy.id}").status_code == 404
    with factory() as database:
        assert database.get(UserRow, "reader@example.test") is not None
    assert UUID(own["id"])


def test_owner_cannot_be_supplied_by_registration_and_share_validation(raw_client):
    login(raw_client)
    assert (
        raw_client.post(
            "/api/v1/sandboxes",
            json={**PAYLOAD, "owner_email": "stranger@example.test"},
            headers=HEADERS,
        ).status_code
        == 422
    )
    sandbox = create(raw_client)
    assert shares(raw_client, sandbox["id"], ["bad"]).status_code == 422
    assert (
        shares(
            raw_client, sandbox["id"], [f"reader{i}@example.test" for i in range(101)]
        ).status_code
        == 422
    )
    assert shares(raw_client, sandbox["id"], ["owner@example.test"]).json() == {"emails": []}
    assert (
        raw_client.post(
            f"/api/v1/sandboxes/{sandbox['id']}/stop",
            json={"owner_email": "other@example.test"},
            headers=HEADERS,
        ).status_code
        == 422
    )


@pytest.mark.parametrize("environment", ["local", "development", "test"])
def test_each_development_environment_allows_explicit_login(factory, settings, environment):
    settings.environment = environment
    with TestClient(create_app(settings, factory), base_url="http://localhost") as client:
        assert client.get("/api/v1/system").json()["auth_mode"] == "local-dev"
        login(client)
        assert client.get("/api/v1/auth/me").status_code == 200
