"""Non-skippable real PostgreSQL identity, migration and access-control evidence."""

import hashlib
import os
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from protohub.api.main import create_app
from protohub.domain.settings import Settings
from protohub.persistence.database import create_session_factory
from protohub.persistence.models import SandboxRow, SessionRow
from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import make_url

pytestmark = pytest.mark.postgres
ROOT = Path(__file__).resolve().parents[2]
WRITE = {"X-ProtoHub-Client": "console", "Origin": "http://localhost:8080"}


@pytest.fixture
def migrated_identity_database(monkeypatch):
    raw = os.environ.get("PROTOHUB_TEST_DATABASE_URL")
    if not raw:
        pytest.fail(
            "Real PostgreSQL identity checks require a database; not skipped", pytrace=False
        )
    url = make_url(raw)
    if url.get_backend_name() != "postgresql" or url.host not in {
        "localhost",
        "127.0.0.1",
        "db",
        "postgres",
        "integration-db",
    }:
        pytest.fail("A dedicated local PostgreSQL fixture is required", pytrace=False)
    schema = "protohub_identity_" + uuid4().hex
    legacy_id = uuid4()
    admin = create_engine(url, connect_args={"connect_timeout": 5})
    created = False
    factory = None
    isolated_engine = None
    try:
        with admin.begin() as connection:
            connection.execute(text(f'CREATE SCHEMA "{schema}"'))
            created = True
        isolated = url.update_query_dict({"options": f"-csearch_path={schema}"})
        isolated_url = isolated.render_as_string(hide_password=False)
        monkeypatch.setenv("PROTOHUB_DATABASE_URL", isolated_url)
        config = Config(str(ROOT / "apps/server/alembic.ini"))
        command.upgrade(config, "0001_initial")
        isolated_engine = create_engine(isolated)
        with isolated_engine.begin() as connection:
            connection.execute(
                text("""INSERT INTO sandboxes
                    (id, name, template_id, ttl_seconds, desired_state, status, generation,
                     created_at, updated_at)
                    VALUES (:id, 'Retained legacy app', 'hello-web', 900, 'stopped',
                            'stopped', 0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"""),
                {"id": legacy_id},
            )
        command.upgrade(config, "head")
        factory = create_session_factory(isolated_url)
        yield factory, legacy_id
    finally:
        if factory is not None:
            factory.kw["bind"].dispose()
        if isolated_engine is not None:
            isolated_engine.dispose()
        if created:
            with admin.begin() as connection:
                connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()


def login(client, email):
    response = client.post("/api/v1/auth/login", json={"email": email}, headers=WRITE)
    assert response.status_code == 200
    assert "set-cookie" not in response.headers
    value = response.json()
    return {**WRITE, "Authorization": f"Bearer {value['token']}"}, value["token"]


def create(client, auth, name):
    response = client.post(
        "/api/v1/sandboxes",
        headers=auth,
        json={"name": name, "template_id": "hello-web", "ttl_seconds": 900},
    )
    assert response.status_code == 201
    return response.json()


def test_postgres_migrates_legacy_and_persists_private_ownership(migrated_identity_database):
    factory, legacy_id = migrated_identity_database
    settings = Settings(environment="test")
    with TestClient(create_app(settings, factory), base_url="http://localhost") as first:
        owner, owner_token = login(first, "  OWNER@example.test  ")
        reader, _ = login(first, "reader@example.test")
        outsider, _ = login(first, "outsider@example.test")
        shared = create(first, owner, "Shared fixture")
        private = create(first, owner, "Private fixture")
        reader_private = create(first, reader, "Reader fixture")
        assert shared["owner_email"] == private["owner_email"] == "owner@example.test"
        assert first.get("/api/v1/sandboxes").status_code == 401
        share_path = f"/api/v1/sandboxes/{shared['id']}/shares"
        response = first.put(share_path, json={"emails": ["READER@example.test"]}, headers=owner)
        assert response.status_code == 200
        assert response.json() == {"emails": ["reader@example.test"]}
        start = first.post(f"/api/v1/sandboxes/{shared['id']}/start", json={}, headers=owner)
        assert start.status_code == 202
        operation_id = start.json()["id"]
    # Independent API instances observe the same migrated database and persisted sessions.
    with TestClient(create_app(settings, factory), base_url="http://localhost") as restarted:
        assert restarted.get("/api/v1/auth/me", headers=owner).json() == {
            "email": "owner@example.test"
        }
        expected = {shared["id"], reader_private["id"]}
        assert {
            item["id"]
            for item in restarted.get("/api/v1/sandboxes", headers=reader).json()["items"]
        } == expected
        assert restarted.get("/api/v1/sandboxes", headers=outsider).json() == {"items": []}
        for auth in (owner, reader, outsider):
            assert restarted.get(f"/api/v1/sandboxes/{legacy_id}", headers=auth).status_code == 404
        assert (
            restarted.get(f"/api/v1/sandboxes/{private['id']}", headers=reader).status_code == 404
        )
        assert (
            restarted.get(f"/api/v1/operations/{operation_id}", headers=reader).status_code == 200
        )
        assert (
            restarted.get(f"/api/v1/operations/{operation_id}", headers=outsider).status_code == 404
        )
        assert restarted.get(share_path, headers=reader).status_code == 404
        assert restarted.put(share_path, json={"emails": []}, headers=reader).status_code == 404
        assert (
            restarted.request(
                "DELETE", f"/api/v1/sandboxes/{shared['id']}", json={}, headers=reader
            ).status_code
            == 404
        )
        assert restarted.put(share_path, json={"emails": []}, headers=owner).status_code == 200
        assert restarted.get(f"/api/v1/sandboxes/{shared['id']}", headers=reader).status_code == 404
        assert (
            restarted.get(f"/api/v1/operations/{operation_id}", headers=reader).status_code == 404
        )
        assert restarted.post("/api/v1/auth/logout", json={}, headers=owner).status_code == 200
    with TestClient(create_app(settings, factory), base_url="http://localhost") as third:
        assert third.get("/api/v1/sandboxes", headers=owner).status_code == 401
        owner_again, _ = login(third, "owner@example.test")
        assert {
            item["id"]
            for item in third.get("/api/v1/sandboxes", headers=owner_again).json()["items"]
        } == {shared["id"], private["id"]}
    with factory() as session:
        retained = session.get(SandboxRow, legacy_id)
        assert retained is not None and retained.owner_email is None
        assert retained.name == "Retained legacy app" and retained.generation == 0
        assert session.get(SessionRow, owner_token) is None
        assert session.get(SessionRow, hashlib.sha256(owner_token.encode()).hexdigest()) is None
        sessions = session.scalars(select(SessionRow)).all()
        assert sessions and all(len(row.token_digest) == 64 for row in sessions)
