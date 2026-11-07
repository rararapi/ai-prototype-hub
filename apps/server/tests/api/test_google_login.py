from urllib.parse import parse_qs

import httpx
import pytest
from fastapi.testclient import TestClient

from protohub.api import google
from protohub.api.main import create_app
from protohub.domain.settings import Settings

HEADERS = {
    "Origin": "http://localhost:8080",
    "X-ProtoHub-Client": "console",
    "X-Requested-With": "XmlHttpRequest",
}
ORIGIN = HEADERS["Origin"]
EMAIL = "member@gmail.com"
CLIENT_ID = "test_client.apps.googleusercontent.com"


@pytest.fixture
def managed(factory):
    config = Settings(
        google_login=True,
        google_client_id=CLIENT_ID,
        google_client_secret="test-value",
        database_url="sqlite://",
        environment="production",
    )
    with TestClient(create_app(config, factory), base_url="http://localhost") as client:
        yield client


def provider(
    monkeypatch,
    email=EMAIL,
    subject="12345",
    verified=True,
    hd=None,
    failure=None,
    provider_error="invalid_grant",
):
    original = httpx.Client
    calls = []

    def serve(request):
        calls.append(str(request.url))
        if str(request.url) == google.TOKEN_URL:
            assert request.method == "POST"
            assert parse_qs(request.content.decode()) == {
                "code": ["single-use"],
                "client_id": [CLIENT_ID],
                "client_secret": ["test-value"],
                "grant_type": ["authorization_code"],
                "redirect_uri": [ORIGIN],
            }
            if failure:
                return httpx.Response(failure, json={"error": provider_error, "detail": "private"})
            return httpx.Response(
                200, json={"access_token": "access-from-provider", "refresh_token": "discard"}
            )
        assert str(request.url) == google.USERINFO_URL and request.method == "GET"
        assert request.headers["Authorization"] == "Bearer access-from-provider"
        claims = {"email": email, "email_verified": verified, "sub": subject}
        if hd:
            claims["hd"] = hd
        return httpx.Response(200, json=claims)

    def mock_client(**kwargs):
        assert kwargs["trust_env"] is False and kwargs["follow_redirects"] is False
        return original(transport=httpx.MockTransport(serve), **kwargs)

    monkeypatch.setattr(google.httpx, "Client", mock_client)
    return calls


def sign_in(client, headers=None, payload=None):
    return client.post(
        "/api/v1/auth/google",
        json=payload or {"code": "single-use"},
        headers=HEADERS if headers is None else headers,
    )


def test_only_registered_google_account_can_use_api_and_revoke_live_session(managed, monkeypatch):
    calls = provider(monkeypatch)
    info = managed.get("/api/v1/system").json()
    assert info["auth_mode"] == "google" and info["google_client_id"] == CLIENT_ID
    assert info["preview_origin"] == "http://localhost:8081"
    assert "test-value" not in str(info)
    assert managed.get("/api/v1/templates").status_code == 401
    assert managed.get("/api/v1/sandboxes", headers={"X-Forwarded-Email": EMAIL}).status_code == 401
    assert (
        managed.post("/api/v1/auth/login", headers=HEADERS, json={"email": EMAIL}).status_code
        == 404
    )
    assert sign_in(managed).status_code == 403
    sessions = managed.app.state.sessions
    sessions.add_account(EMAIL)
    result = sign_in(managed)
    assert result.status_code == 200 and result.headers["Cache-Control"] == "no-store"
    assert not any(
        secret in result.text for secret in ("access-from-provider", "test-value", "discard")
    )
    managed.headers["Authorization"] = "Bearer " + result.json()["token"]
    assert managed.get("/api/v1/auth/me").json() == {"email": EMAIL}
    assert managed.get("/api/v1/templates").status_code == 200
    assert managed.get("/api/v1/sandboxes").status_code == 200
    sessions.remove_account(EMAIL)
    assert managed.get("/api/v1/sandboxes").status_code == 401
    assert calls == [google.TOKEN_URL, google.USERINFO_URL] * 2


@pytest.mark.parametrize("header", ["Origin", "X-Requested-With", "X-ProtoHub-Client"])
def test_missing_csrf_checks_reject_before_contacting_google(managed, monkeypatch, header):
    calls = provider(monkeypatch)
    headers = dict(HEADERS)
    del headers[header]
    assert sign_in(managed, headers=headers).status_code == 403
    assert (
        sign_in(managed, headers={**HEADERS, "Origin": "https://elsewhere.example"}).status_code
        == 403
    )
    assert sign_in(managed, payload={"code": "single-use", "email": EMAIL}).status_code == 422
    assert calls == []


@pytest.mark.parametrize(
    ("email", "verified", "hosted", "pinned", "status"),
    [
        ("owner@workspace.example", True, "workspace.example", False, 200),
        ("owner@third-party.example", True, None, False, 403),
        ("owner@third-party.example", True, None, True, 200),
        (EMAIL, False, None, True, 403),
        (EMAIL, "true", None, True, 403),
    ],
)
def test_provider_verified_address_binding(
    managed, monkeypatch, email, verified, hosted, pinned, status
):
    provider(monkeypatch, email=email, verified=verified, hd=hosted)
    managed.app.state.sessions.add_account(email, "12345" if pinned else None)
    assert sign_in(managed).status_code == status


@pytest.mark.parametrize(("provider_status", "expected"), [(400, 403), (500, 503), (302, 503)])
def test_provider_rejection_or_outage_does_not_issue_session(
    managed, monkeypatch, provider_status, expected
):
    provider(monkeypatch, failure=provider_status)
    managed.app.state.sessions.add_account(EMAIL)
    result = sign_in(managed)
    assert result.status_code == expected
    assert "private" not in result.text
    assert managed.get("/api/v1/auth/me").status_code == 401


def test_configuration_failure_is_service_unavailable_without_provider_secrets(
    managed, monkeypatch
):
    provider(monkeypatch, failure=401, provider_error="invalid_client")
    result = sign_in(managed)
    assert result.status_code == 503
    assert result.json()["error"]["code"] == "google_unavailable"
    assert "invalid_client" not in result.text and "private" not in result.text


def test_provider_missing_email_is_denied(managed, monkeypatch):
    provider(monkeypatch, email=None)
    result = sign_in(managed)
    assert result.status_code == 403


def test_incomplete_google_config_never_falls_back_to_email(factory):
    with TestClient(
        create_app(Settings(google_login=True), factory), base_url="http://localhost"
    ) as client:
        assert client.get("/api/v1/system").json()["auth_mode"] == "disabled"
        assert (
            client.post("/api/v1/auth/login", json={"email": EMAIL}, headers=HEADERS).status_code
            == 404
        )
        assert sign_in(client).status_code == 404
        assert client.get("/api/v1/sandboxes").status_code == 401
