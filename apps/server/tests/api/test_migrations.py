from pathlib import Path

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
    assert set(tables) == {"alembic_version", "sandboxes", "operations", "audit_events"}
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
