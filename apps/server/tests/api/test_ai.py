"""Deterministic Gemini transport, API ownership and generation-state regressions."""

import json
from dataclasses import replace
from datetime import timedelta
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from protohub.ai.gemini import GeminiGenerator, GeminiUnavailable, GeneratedPlan, access_token
from protohub.api.main import create_app
from protohub.domain.models import AiBrief, AiConfig, AiCreateRequest, AiReviseRequest, AiUsage
from protohub.domain.settings import Settings
from protohub.persistence.ai import AiGenerationFailed, AiQuotaExceeded, AiRepository
from protohub.persistence.auth import SessionRepository
from protohub.persistence.models import AiApplicationRow, AiGenerationRow
from protohub.persistence.repository import Conflict, NotFound

OWNER = "owner@example.test"
OTHER = "other@example.test"
WRITE = {"X-ProtoHub-Client": "console"}


def make_config(template="management-dashboard", **changes):
    return AiConfig(
        template=template,
        title="Monthly review",
        subtitle="Sample figures",
        color="purple",
        trend=False,
        departments=False,
        cash_flow=False,
        **changes,
    )


def make_request(**changes):
    values = {
        "request_id": uuid4(),
        "brief": AiBrief(purpose="Compare monthly figures", audience="Team", success="See changes"),
        "config": make_config(),
        "instruction": "",
    }
    return AiCreateRequest(**(values | changes))


def generated(config=None):
    return GeneratedPlan(
        config=config or make_config(),
        summary="A sample display plan",
        usage=AiUsage(input_tokens=10, output_tokens=20),
    )


class FakeGenerator:
    def __init__(self):
        self.calls = 0
        self.error = None
        self.on_call = None

    def generate(self, brief, config, instruction):
        self.calls += 1
        if self.on_call:
            self.on_call()
        if self.error:
            raise self.error
        color = "green" if instruction else "blue"
        return generated(config.model_copy(update={"color": color}))


@pytest.fixture
def ai_settings():
    return Settings(
        database_url="sqlite://",
        environment="test",
        google_login=False,
        ai_enabled=True,
        ai_vertex_project="example-project",
    )


@pytest.fixture
def ai_client(factory, ai_settings):
    app = create_app(ai_settings, factory)
    fake = FakeGenerator()
    app.state.ai_generator = fake
    with TestClient(app, base_url="http://localhost") as client:
        login = client.post("/api/v1/auth/login", json={"email": OWNER}, headers=WRITE)
        assert login.status_code == 200
        client.headers.update(WRITE | {"Authorization": "Bearer " + login.json()["token"]})
        yield client, fake, app


@pytest.fixture
def ai_repo(factory, ai_settings, clock):
    sessions = SessionRepository(factory)
    sessions.login(OWNER)
    sessions.login(OTHER)
    return AiRepository(factory, ai_settings, clock)


def test_api_generates_once_confirms_and_persists_revision_and_owned_list(ai_client):
    client, fake, app = ai_client
    payload = make_request().model_dump(mode="json")
    response = client.post("/api/v1/ai/apps", json=payload)
    assert response.status_code == 201
    initial = response.json()
    assert initial["status"] == "draft" and initial["revision"] == 1
    assert initial["config"]["color"] == "blue"
    assert initial["model"] == "gemini-3.5-flash-lite"
    assert initial["usage"] == {"input_tokens": 10, "output_tokens": 20}
    assert client.post("/api/v1/ai/apps", json=payload).json() == initial
    assert fake.calls == 1
    path = "/api/v1/ai/apps/" + initial["id"]
    assert client.post(path + "/confirm", json={"expected_revision": 1}).json()["status"] == "ready"
    assert fake.calls == 1
    update = {
        "request_id": str(uuid4()),
        "expected_revision": 1,
        "instruction": "Use green",
    }
    revised = client.post(path + "/revise", json=update)
    assert revised.status_code == 200
    assert revised.json()["config"]["color"] == "green"
    assert revised.json()["status"] == "draft" and revised.json()["revision"] == 2
    assert revised.json()["brief"] == initial["brief"]
    assert client.post(path + "/confirm", json={"expected_revision": 1}).status_code == 409
    assert client.post(path + "/confirm", json={"expected_revision": 2}).status_code == 200
    assert client.post(path + "/revise", json=update).json() == revised.json()
    assert fake.calls == 2
    assert client.get(path).json()["status"] == "ready"
    assert len(client.get("/api/v1/ai/apps").json()["items"]) == 1
    deleted = client.request("DELETE", path, json={})
    assert deleted.status_code == 200
    assert client.request("DELETE", path, json={}).status_code == 200
    assert client.get(path).status_code == 404
    assert client.get("/api/v1/ai/apps").json()["items"] == []
    assert client.post("/api/v1/ai/apps", json=payload).status_code == 404


def test_api_ownership_and_request_id_do_not_reveal_other_accounts(ai_client):
    client, fake, _ = ai_client
    payload = make_request().model_dump(mode="json")
    initial = client.post("/api/v1/ai/apps", json=payload).json()
    path = "/api/v1/ai/apps/" + initial["id"]
    login = client.post("/api/v1/auth/login", json={"email": OTHER}, headers=WRITE)
    client.headers["Authorization"] = "Bearer " + login.json()["token"]
    assert client.get(path).status_code == 404
    assert client.get("/api/v1/ai/apps").json()["items"] == []
    assert client.post(path + "/confirm", json={"expected_revision": 1}).status_code == 404
    assert (
        client.post(
            path + "/revise",
            json={
                "request_id": str(uuid4()),
                "expected_revision": 1,
                "instruction": "Blue",
            },
        ).status_code
        == 404
    )
    assert client.request("DELETE", path, json={}).status_code == 404
    assert client.post("/api/v1/ai/apps", json=payload).status_code == 404
    assert fake.calls == 1


def test_api_requires_auth_json_client_origin_and_known_bounded_fields(ai_client):
    client, fake, _ = ai_client
    payload = make_request().model_dump(mode="json")
    headers = dict(client.headers)
    client.headers.pop("Authorization")
    assert client.post("/api/v1/ai/apps", json=payload).status_code == 401
    client.headers.update(headers)
    assert (
        client.post(
            "/api/v1/ai/apps",
            json=payload,
            headers={
                "Origin": "https://other.invalid",
            },
        ).status_code
        == 403
    )
    client.headers.pop("X-ProtoHub-Client")
    assert client.post("/api/v1/ai/apps", json=payload).status_code == 403
    client.headers.update(headers)
    for bad in [
        payload | {"image": "untrusted"},
        payload | {"instruction": "a" * 1001},
        payload | {"config": payload["config"] | {"trend": "true"}},
        payload | {"config": payload["config"] | {"template": "hello-web", "trend": True}},
        payload | {"brief": payload["brief"] | {"purpose": " "}},
    ]:
        assert client.post("/api/v1/ai/apps", json=bad).status_code == 422
    assert fake.calls == 0


def test_disabled_feature_and_provider_failure_never_fall_back_or_leak(ai_client, factory):
    client, fake, app = ai_client
    payload = make_request().model_dump(mode="json")
    initial = client.post("/api/v1/ai/apps", json=payload).json()
    path = "/api/v1/ai/apps/" + initial["id"]
    fake.error = RuntimeError("private-token-provider-body")
    request = {
        "request_id": str(uuid4()),
        "expected_revision": 1,
        "instruction": "Change",
    }
    failed = client.post(path + "/revise", json=request)
    assert failed.status_code == 503
    assert "private-token" not in failed.text
    assert failed.json()["error"]["code"] == "ai_generation_failed"
    assert client.get(path).json() == initial
    assert client.post(path + "/revise", json=request).status_code == 503
    assert fake.calls == 2
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(AiGenerationRow)) == 2
    app.state.settings.ai_enabled = False
    assert (
        client.post("/api/v1/ai/apps", json=make_request().model_dump(mode="json")).status_code
        == 503
    )
    assert fake.calls == 2


def test_api_returns_quota_429_without_model_call(ai_client):
    client, fake, app = ai_client
    app.state.settings.ai_hourly_limit = 1
    assert (
        client.post("/api/v1/ai/apps", json=make_request().model_dump(mode="json")).status_code
        == 201
    )
    response = client.post("/api/v1/ai/apps", json=make_request().model_dump(mode="json"))
    assert response.status_code == 429
    assert response.json()["error"]["code"] == "ai_quota_exceeded"
    assert fake.calls == 1


def test_request_id_reuse_mismatch_and_active_generation_are_conflicts(ai_repo):
    payload = make_request()
    reservation = ai_repo.reserve(OWNER, payload)
    with pytest.raises(Conflict):
        ai_repo.reserve(OWNER, payload)
    with pytest.raises(Conflict):
        ai_repo.reserve(OWNER, payload.model_copy(update={"instruction": "different"}))
    with pytest.raises(Conflict):
        ai_repo.reserve(OWNER, make_request())
    result = ai_repo.complete(reservation, generated())
    with pytest.raises(Conflict):
        ai_repo.complete(reservation, generated())
    ai_repo.fail(reservation)
    assert ai_repo.reserve(OWNER, payload).cached == result


@pytest.mark.parametrize("limit", ["ai_hourly_limit", "ai_daily_limit", "ai_global_daily_limit"])
def test_failed_attempts_count_against_each_quota(ai_repo, limit):
    setattr(ai_repo.settings, limit, 1)
    first = make_request()
    reservation = ai_repo.reserve(OWNER, first)
    ai_repo.fail(reservation)
    with pytest.raises(AiGenerationFailed):
        ai_repo.reserve(OWNER, first)
    principal = OTHER if limit == "ai_global_daily_limit" else OWNER
    with pytest.raises(AiQuotaExceeded):
        ai_repo.reserve(principal, make_request())


def test_expired_token_and_stale_holder_cannot_commit_or_reuse_results(ai_repo, clock, factory):
    first = ai_repo.reserve(OWNER, make_request())
    clock.advance(ai_repo.settings.ai_timeout_seconds + 11)
    second = ai_repo.reserve(OWNER, make_request())
    with pytest.raises(Conflict):
        ai_repo.complete(first, generated())
    with pytest.raises(Conflict):
        ai_repo.complete(replace(second, token=uuid4()), generated())
    assert ai_repo.list(OWNER) == []
    final = ai_repo.complete(second, generated())
    assert ai_repo.list(OWNER) == [final]
    with factory() as session:
        assert session.get(AiGenerationRow, first.request_id).status == "failed"


def test_delete_and_revision_checks_reject_late_model_results(ai_repo, factory):
    first = ai_repo.complete(ai_repo.reserve(OWNER, make_request()), generated())
    request = AiReviseRequest(request_id=uuid4(), expected_revision=1, instruction="Green")
    pending = ai_repo.reserve(OWNER, request, first.id)
    with pytest.raises(Conflict):
        ai_repo.confirm(first.id, OWNER, 1)
    ai_repo.delete(first.id, OWNER)
    with pytest.raises(Conflict):
        ai_repo.complete(pending, generated())
    ai_repo.delete(first.id, OWNER)
    assert ai_repo.list(OWNER) == []
    with pytest.raises(NotFound):
        ai_repo.get(first.id, OWNER)
    with factory() as session:
        row = session.get(AiApplicationRow, first.id)
        assert row.status == "deleted" and row.revision == 2
        assert session.get(AiGenerationRow, pending.request_id).error_code == "application_deleted"


def test_newer_revision_rejects_earlier_model_completion(ai_repo, factory):
    first = ai_repo.complete(ai_repo.reserve(OWNER, make_request()), generated())
    pending = ai_repo.reserve(
        OWNER,
        AiReviseRequest(
            request_id=uuid4(),
            expected_revision=1,
            instruction="Change",
        ),
        first.id,
    )
    with factory.begin() as session:
        row = session.get(AiApplicationRow, first.id)
        row.revision = 2
    with pytest.raises(Conflict):
        ai_repo.complete(pending, generated())
    assert ai_repo.get(first.id, OWNER).revision == 2


def vertex_response(config=None, **changes):
    value = {
        "candidates": [
            {
                "finishReason": "STOP",
                "content": {
                    "parts": [
                        {
                            "text": json.dumps(
                                {
                                    "config": (config or make_config()).model_dump(),
                                    "summary": "A sample display",
                                }
                            )
                        }
                    ]
                },
            }
        ],
        "usageMetadata": {
            "promptTokenCount": 12,
            "candidatesTokenCount": 20,
            "thoughtsTokenCount": 3,
        },
    }
    return value | changes


def test_vertex_transport_has_fixed_endpoint_schema_and_usage_without_private_context(ai_settings):
    requests = []

    def handle(request):
        requests.append(request)
        assert request.url.host == "aiplatform.googleapis.com"
        assert request.url.path.endswith(
            "/locations/global/publishers/google/models/gemini-3.5-flash-lite:generateContent"
        )
        assert request.headers["Authorization"] == "Bearer fixture-access-token"
        body = json.loads(request.content)
        assert "owner_email" not in str(body)
        assert "tools" not in body and body["generationConfig"]["maxOutputTokens"] == 2048
        assert body["generationConfig"]["responseMimeType"] == "application/json"
        return httpx.Response(200, json=vertex_response())

    with httpx.Client(transport=httpx.MockTransport(handle)) as http:
        result = GeminiGenerator(ai_settings, http, lambda: "fixture-access-token")._generate_once(
            make_request().brief,
            make_config(),
            "Make a sample",
        )
    assert result.usage == AiUsage(input_tokens=12, output_tokens=23)
    assert len(requests) == 1


@pytest.mark.parametrize(
    "case",
    [
        "http",
        "timeout",
        "redirect",
        "malformed",
        "blocked",
        "oversized",
        "extra",
        "template",
        "tool",
        "usage",
    ],
)
def test_vertex_rejects_failed_unsafe_or_incomplete_output_without_retry(ai_settings, case):
    calls = []

    def handle(request):
        calls.append(request)
        if case == "http":
            return httpx.Response(429, text="private provider message")
        if case == "timeout":
            raise httpx.ReadTimeout("private provider timeout", request=request)
        if case == "redirect":
            return httpx.Response(302, headers={"Location": "https://other.invalid/"})
        if case == "malformed":
            return httpx.Response(200, text="not JSON")
        if case == "oversized":
            return httpx.Response(200, content=b"x" * 65537)
        body = vertex_response()
        if case == "blocked":
            body["candidates"][0]["finishReason"] = "SAFETY"
        elif case == "extra":
            body["candidates"][0]["content"]["parts"][0]["text"] = json.dumps(
                {
                    "config": make_config().model_dump() | {"script": "execute"},
                    "summary": "Private content",
                }
            )
        elif case == "template":
            body = vertex_response(make_config("hello-web"))
        elif case == "tool":
            body["candidates"][0]["content"]["parts"] = [{"executableCode": {"code": "private"}}]
        elif case == "usage":
            body["usageMetadata"]["promptTokenCount"] = -1
        return httpx.Response(200, json=body)

    with httpx.Client(transport=httpx.MockTransport(handle)) as http:
        with pytest.raises(GeminiUnavailable) as error:
            GeminiGenerator(ai_settings, http, lambda: "fixture-token")._generate_once(
                make_request().brief,
                make_config(),
                "",
            )
    assert "private" not in str(error.value)
    assert len(calls) == 1


def test_adc_failure_is_sanitized_and_unconfigured_generator_does_not_request_credentials(
    ai_settings,
    monkeypatch,
):
    import google.auth

    def unavailable(**kwargs):
        raise RuntimeError("private credential material")

    monkeypatch.setattr(google.auth, "default", unavailable)
    with pytest.raises(GeminiUnavailable) as error:
        access_token(1)
    assert "private" not in str(error.value)
    ai_settings.ai_enabled = False
    token = []

    def token_provider():
        token.append(True)
        return "fixture"

    with pytest.raises(GeminiUnavailable):
        GeminiGenerator(ai_settings, token_provider=token_provider)._generate_once(
            make_request().brief,
            make_config(),
            "",
        )
    assert token == []


def test_vertex_rejects_a_response_received_after_the_generation_deadline(ai_settings, monkeypatch):
    from types import SimpleNamespace

    import protohub.ai.gemini as gemini

    values = iter([0, 0, 21])
    monkeypatch.setattr(gemini, "time", SimpleNamespace(monotonic=lambda: next(values)))
    with httpx.Client(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=vertex_response()))
    ) as http:
        with pytest.raises(GeminiUnavailable):
            GeminiGenerator(ai_settings, http, lambda: "fixture-token")._generate_once(
                make_request().brief, make_config(), ""
            )


def test_adc_refresh_request_has_a_bounded_timeout_and_cloud_platform_scope(monkeypatch):
    from types import SimpleNamespace

    import google.auth
    import google.auth.transport.requests

    seen = {}

    def transport(self, *args, **kwargs):
        seen["timeout"] = kwargs["timeout"]
        return SimpleNamespace(status=200, data=b"{}")

    class Credentials:
        token = "fixture-adc-token"

        def refresh(self, request):
            request("https://metadata.example.test/", timeout=500)

    def default(**kwargs):
        seen["scopes"] = kwargs["scopes"]
        return Credentials(), "example-project"

    monkeypatch.setattr(google.auth, "default", default)
    monkeypatch.setattr(google.auth.transport.requests.Request, "__call__", transport)
    assert access_token(1) == "fixture-adc-token"
    assert 0 < seen["timeout"] <= 1
    assert seen["scopes"] == ["https://www.googleapis.com/auth/cloud-platform"]


def test_reservation_timestamps_and_quotas_use_time_after_acquiring_the_lock(
    ai_repo,
    clock,
    monkeypatch,
    factory,
):
    ai_repo.settings.ai_hourly_limit = 1
    old = ai_repo.reserve(OWNER, make_request())
    ai_repo.fail(old)
    original = ai_repo.lock

    def delayed_lock(session):
        original(session)
        clock.advance(3601)

    monkeypatch.setattr(ai_repo, "lock", delayed_lock)
    reserved = ai_repo.reserve(OWNER, make_request())
    with factory() as session:
        row = session.get(AiGenerationRow, reserved.request_id)
        assert row.created_at == clock.value
        assert row.expires_at == clock.value + timedelta(
            seconds=ai_repo.settings.ai_timeout_seconds + 10
        )


def test_completion_checks_expiry_after_waiting_for_the_lock(ai_repo, clock, monkeypatch):
    reserved = ai_repo.reserve(OWNER, make_request())
    original = ai_repo.lock

    def delayed_lock(session):
        original(session)
        clock.advance(ai_repo.settings.ai_timeout_seconds + 11)

    monkeypatch.setattr(ai_repo, "lock", delayed_lock)
    with pytest.raises(Conflict):
        ai_repo.complete(reserved, generated())
    assert ai_repo.list(OWNER) == []


# The production supervisor starts only this trusted module. These tests replace
# the OS launch with fixed fixture programs, never a caller/model supplied command.
def fixture_worker(monkeypatch, code, *arguments):
    import asyncio
    import sys

    import protohub.ai.gemini as gemini

    original = asyncio.create_subprocess_exec
    processes = []

    async def create(*args, **kwargs):
        assert args == (sys.executable, "-m", "protohub.ai.gemini", "--worker")
        assert kwargs["stderr"] == asyncio.subprocess.DEVNULL
        assert not any(name.startswith("PROTOHUB_") for name in kwargs["env"])
        process = await original(sys.executable, "-c", code, *arguments, **kwargs)
        processes.append(process)
        return process

    monkeypatch.setattr(gemini.asyncio, "create_subprocess_exec", create)
    return processes


def assert_worker_reaped(processes):
    import os

    assert len(processes) == 1
    assert processes[0].returncode is not None
    if os.name == "posix":
        with pytest.raises(ProcessLookupError):
            os.kill(processes[0].pid, 0)


def test_supervisor_sends_only_ai_settings_and_returns_a_validated_plan(
    ai_settings,
    monkeypatch,
):
    monkeypatch.setenv("PROTOHUB_GOOGLE_CLIENT_SECRET", "private-oauth-value")
    monkeypatch.setenv("PROTOHUB_LLM_API_KEY", "private-shared-value")
    code = """
import json, os, sys
from protohub.ai.gemini import WorkerInput, GeneratedPlan, AI_SETTING_NAMES
assert not any(name.startswith("PROTOHUB_") for name in os.environ)
raw = sys.stdin.buffer.read()
assert b"private-oauth-value" not in raw and b"private-shared-value" not in raw
payload = json.loads(raw)
assert set(payload["settings"]) == set(AI_SETTING_NAMES)
request = WorkerInput.model_validate_json(raw)
sys.stdout.write(GeneratedPlan(config=request.config, summary="A validated plan").model_dump_json())
"""
    ai_settings.ai_timeout_seconds = 5
    processes = fixture_worker(monkeypatch, code)
    result = GeminiGenerator(ai_settings).generate(make_request().brief, make_config(), "")
    assert result.summary == "A validated plan"
    assert_worker_reaped(processes)


def test_supervisor_terminates_credential_startup_work_at_the_single_deadline(
    ai_settings,
    monkeypatch,
    record_property,
):
    import time

    ai_settings.ai_timeout_seconds = 1
    processes = fixture_worker(monkeypatch, "import time; time.sleep(30)")
    start = time.monotonic()
    with pytest.raises(GeminiUnavailable):
        GeminiGenerator(ai_settings).generate(make_request().brief, make_config(), "")
    elapsed = time.monotonic() - start
    record_property("elapsed_seconds", elapsed)
    assert elapsed < 1.4
    assert_worker_reaped(processes)


@pytest.mark.parametrize(
    "output",
    [
        pytest.param("private-token-not-json", id="invalid"),
        pytest.param("x" * 20000, id="oversized"),
    ],
)
def test_supervisor_rejects_invalid_or_oversized_private_output_and_reaps(
    ai_settings,
    monkeypatch,
    output,
):
    code = "import sys; sys.stderr.write('private-stderr'); sys.stdout.write(" + repr(output) + ")"
    ai_settings.ai_timeout_seconds = 5
    processes = fixture_worker(monkeypatch, code)
    with pytest.raises(GeminiUnavailable) as error:
        GeminiGenerator(ai_settings).generate(make_request().brief, make_config(), "")
    assert "private" not in str(error.value)
    assert_worker_reaped(processes)


def test_supervisor_cancellation_kills_and_reaps_the_actual_worker(ai_settings, monkeypatch):
    import asyncio

    from protohub.ai.gemini import AI_SETTING_NAMES, WorkerInput, WorkerSettings, run_worker

    processes = fixture_worker(monkeypatch, "import time; time.sleep(30)")
    request = WorkerInput(
        settings=WorkerSettings.model_validate(
            {name: getattr(ai_settings, name) for name in AI_SETTING_NAMES}
        ),
        brief=make_request().brief,
        config=make_config(),
        instruction="",
    )

    async def cancel():
        task = asyncio.create_task(run_worker(request.model_dump_json().encode(), 10))
        for _ in range(200):
            if processes:
                break
            await asyncio.sleep(0.005)
        assert processes
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(cancel())
    assert_worker_reaped(processes)


def test_real_delayed_headers_and_body_share_one_deadline_and_socket_is_closed(
    ai_settings,
    monkeypatch,
    record_property,
):
    import threading
    import time
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    disconnected = threading.Event()
    header_sent = threading.Event()
    requests = []
    response = json.dumps(vertex_response()).encode()

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *args):
            pass

        def do_POST(self):
            self.rfile.read(int(self.headers["Content-Length"]))
            requests.append(self.path)
            time.sleep(0.2)
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(response)))
            self.end_headers()
            self.wfile.flush()
            header_sent.set()
            # A normal client receives the body 1.2 seconds after the headers.
            # The supervised client must close this real socket at its 1s
            # total deadline, not wait another per-read timeout.
            self.connection.settimeout(1.2)
            try:
                if self.connection.recv(1) == b"":
                    disconnected.set()
                    return
            except TimeoutError:
                pass
            try:
                self.wfile.write(response)
            except (BrokenPipeError, ConnectionResetError):
                disconnected.set()

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    code = """
import sys, httpx
from protohub.ai.gemini import WorkerInput, GeminiGenerator
request = WorkerInput.model_validate_json(sys.stdin.buffer.read())
class Loopback(httpx.BaseTransport):
    def __init__(self):
        self.real = httpx.HTTPTransport()
    def handle_request(self, outgoing):
        target = outgoing.url.copy_with(scheme="http",host="127.0.0.1",port=int(sys.argv[1]))
        return self.real.handle_request(httpx.Request(
            outgoing.method,target,headers=outgoing.headers,content=outgoing.read()))
    def close(self):
        self.real.close()
with httpx.Client(transport=Loopback()) as client:
    result=GeminiGenerator(request.settings,client,lambda:"fixture-token")._generate_once(
        request.brief,request.config,request.instruction)
    sys.stdout.write(result.model_dump_json())
"""
    try:
        ai_settings.ai_timeout_seconds = 1
        processes = fixture_worker(monkeypatch, code, str(server.server_port))
        start = time.monotonic()
        with pytest.raises(GeminiUnavailable):
            GeminiGenerator(ai_settings).generate(make_request().brief, make_config(), "")
        elapsed = time.monotonic() - start
        record_property("elapsed_seconds", elapsed)
        record_property("configured_timeout_seconds", 1)
        record_property("header_delay_seconds", 0.2)
        record_property("body_delay_seconds", 1.2)
        assert elapsed < 1.4
        assert header_sent.wait(1)
        assert disconnected.wait(1)
        assert len(requests) == 1
        assert_worker_reaped(processes)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
