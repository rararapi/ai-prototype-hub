from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect

from protohub.domain.models import Action, CreateSandbox
from protohub.domain.settings import Settings
from protohub.persistence.database import create_session_factory
from protohub.persistence.repository import SandboxRepository


def test_migration_reentrant_and_records_persist_across_new_engine(tmp_path, monkeypatch):
    url = "sqlite:///" + str(tmp_path / "migration.db").replace("\\", "/")
    monkeypatch.setenv("PROTOHUB_DATABASE_URL", url)
    ini = Path(__file__).resolve().parents[2] / "alembic.ini"
    config = Config(str(ini))
    command.upgrade(config, "head")
    command.upgrade(config, "head")
    factory = create_session_factory(url)
    tables = inspect(factory.kw["bind"]).get_table_names()
    assert set(tables) == {
        "alembic_version",
        "ai_applications",
        "ai_generations",
        "ai_quotas",
        "sandboxes",
        "operations",
        "audit_events",
        "users",
        "sessions",
        "google_accounts",
        "sandbox_shares",
    }
    settings = Settings(database_url=url)
    repository = SandboxRepository(factory, settings)
    sandbox = repository.create(CreateSandbox(name="Persistent app", template_id="hello-web"))
    operation = repository.request(sandbox.id, Action.START)
    factory.kw["bind"].dispose()
    fresh = create_session_factory(url)
    recreated = SandboxRepository(fresh, settings)
    assert recreated.get(sandbox.id).name == "Persistent app"
    assert recreated.get_operation(operation.id).generation == 1
    fresh.kw["bind"].dispose()


def test_upgrade_retains_legacy_rows_without_assigning_an_owner(tmp_path, monkeypatch):
    from sqlalchemy import text

    url = "sqlite:///" + str(tmp_path / "legacy.db").replace("\\", "/")
    monkeypatch.setenv("PROTOHUB_DATABASE_URL", url)
    config = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
    command.upgrade(config, "0001_initial")
    factory = create_session_factory(url)
    with factory.begin() as session:
        session.execute(
            text(
                "INSERT INTO sandboxes (id,name,template_id,ttl_seconds,desired_state,status,"
                "generation,created_at,updated_at) VALUES "
                "('00000000000040008000000000000001','Legacy','hello-web',900,'stopped',"
                "'stopped',0,'2026-10-30 00:00:00','2026-10-30 00:00:00')"
            )
        )
    command.upgrade(config, "head")
    repository = SandboxRepository(factory, Settings(database_url=url))
    assert len(repository.list()) == 1
    assert repository.list()[0].owner_email is None
    assert repository.list("owner@example.test") == []
    command.downgrade(config, "0001_initial")
    with factory() as session:
        assert session.scalar(text("SELECT name FROM sandboxes")) == "Legacy"
    factory.kw["bind"].dispose()


def test_0002_upgrade_preserves_dev_sessions_without_provisioning_google_accounts(
    tmp_path, monkeypatch
):
    from sqlalchemy import text

    from protohub.persistence.auth import AuthenticationRequired, SessionRepository

    url = f"sqlite:///{tmp_path / 'dev-sessions.db'}"
    monkeypatch.setenv("PROTOHUB_DATABASE_URL", url)
    config = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
    command.upgrade(config, "0002_local_users")
    factory = create_session_factory(url)
    repo = SessionRepository(factory)
    dev_token = "a" * 43
    with factory.begin() as session:
        session.execute(text("INSERT INTO users VALUES ('dev@example.test','2026-01-01')"))
        session.execute(
            text(
                "INSERT INTO sessions (token_digest,email,expires_at,created_at) "
                "VALUES (:digest,'dev@example.test','2099-01-01','2026-01-01')"
            ),
            {"digest": repo.digest(dev_token)},
        )
    command.upgrade(config, "head")
    dev = "Bearer " + dev_token
    assert repo.authenticate(dev).email == "dev@example.test"
    with pytest.raises(AuthenticationRequired):
        repo.authenticate(dev, google=True)
    with pytest.raises(AuthenticationRequired):
        repo.login_google("dev@example.test", "subject", True)
    repo.add_account("dev@example.test")
    repo.login_google("dev@example.test", "subject", True)
    command.downgrade(config, "0002_local_users")
    with factory() as session:
        assert session.scalars(text("SELECT token_digest FROM sessions")).all() == [
            repo.digest(dev_token)
        ]
    factory.kw["bind"].dispose()
