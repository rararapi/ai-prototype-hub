"""Real PostgreSQL checks. Select explicitly with -m postgres; never skip missing DB."""

import os
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Barrier
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.engine import make_url

from protohub.domain.models import Action, CreateSandbox, Error, SandboxStatus
from protohub.domain.ports import Observation
from protohub.domain.settings import Settings
from protohub.persistence.database import create_session_factory
from protohub.persistence.jobs import SqlJobStore
from protohub.persistence.models import OperationRow, SandboxRow
from protohub.persistence.repository import SandboxRepository

pytestmark = pytest.mark.postgres


@pytest.fixture
def postgres_factory(monkeypatch):
    raw = os.environ.get("PROTOHUB_TEST_DATABASE_URL")
    if not raw:
        pytest.fail(
            "Real PostgreSQL requires PROTOHUB_TEST_DATABASE_URL; check was not skipped",
            pytrace=False,
        )
    url = make_url(raw)
    if url.get_backend_name() != "postgresql" or url.host not in {
        "localhost",
        "127.0.0.1",
        "db",
        "postgres",
        "integration-db",
    }:
        pytest.fail("A dedicated local PostgreSQL test endpoint is required", pytrace=False)
    schema = "protohub_test_" + uuid4().hex
    admin = create_engine(url, connect_args={"connect_timeout": 5})
    created = False
    factory = None
    try:
        with admin.begin() as connection:
            connection.execute(text(f'CREATE SCHEMA "{schema}"'))
            created = True
        isolated = url.update_query_dict({"options": f"-csearch_path={schema}"})
        isolated_url = isolated.render_as_string(hide_password=False)
        monkeypatch.setenv("PROTOHUB_DATABASE_URL", isolated_url)
        config = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
        command.upgrade(config, "head")
        factory = create_session_factory(isolated_url)
        yield factory
    finally:
        if factory is not None:
            factory.kw["bind"].dispose()
        if created:
            with admin.begin() as connection:
                # Name is locally generated, never caller input; only this fixture owns it.
                connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()


def setup_repository(factory):
    settings = Settings(runtime_mode="mock")
    return SandboxRepository(factory, settings), SqlJobStore(factory, settings)


def add(repository, name="Postgres sample"):
    return repository.create(CreateSandbox(name=name, template_id="hello-web", ttl_seconds=60))


def test_postgres_duplicate_start_is_atomic_under_concurrency(postgres_factory):
    repository, _ = setup_repository(postgres_factory)
    sandbox = add(repository)
    barrier = Barrier(8)

    def request_start(_):
        barrier.wait(timeout=10)
        return repository.request(sandbox.id, Action.START).id

    with ThreadPoolExecutor(max_workers=8) as pool:
        ids = list(pool.map(request_start, range(8)))
    assert len(set(ids)) == 1
    assert repository.get(sandbox.id).generation == 1
    with postgres_factory() as session:
        assert session.scalar(select(func.count()).select_from(OperationRow)) == 1


def test_postgres_skip_locked_claims_other_app_without_waiting(postgres_factory):
    repository, jobs = setup_repository(postgres_factory)
    first, second = add(repository, "One"), add(repository, "Two")
    repository.request(first.id, Action.START)
    repository.request(second.id, Action.START)
    with postgres_factory.begin() as blocking:
        blocking.scalar(select(SandboxRow).where(SandboxRow.id == first.id).with_for_update())
        with ThreadPoolExecutor(max_workers=1) as pool:
            claim = pool.submit(jobs.claim, "other-consumer").result(timeout=5)
        assert claim is not None and claim.sandbox_id == second.id
    assert jobs.claim("first-consumer").sandbox_id == first.id
    assert jobs.claim("no-duplicate") is None


def test_postgres_old_lease_cannot_complete_same_generation_after_recovery(postgres_factory):
    now = [datetime.now(UTC)]
    settings = Settings(runtime_mode="mock")
    repository = SandboxRepository(postgres_factory, settings, clock=lambda: now[0])
    jobs = SqlJobStore(postgres_factory, settings, clock=lambda: now[0])
    sandbox = add(repository)
    operation = repository.request(sandbox.id, Action.START)
    old = jobs.claim("old-worker", lease_seconds=5)
    now[0] += timedelta(seconds=6)
    new = jobs.claim("recovered-worker", lease_seconds=30)
    assert old.operation_id == new.operation_id == operation.id
    assert old.generation == new.generation
    assert old.lease_token != new.lease_token
    assert not jobs.complete(old, Observation(SandboxStatus.RUNNING))
    assert not jobs.heartbeat(old)
    assert not jobs.fail(old, Error(code="late", message="Delayed failure"))
    assert jobs.complete(new, Observation(SandboxStatus.RUNNING))
    assert repository.get(sandbox.id).status == SandboxStatus.RUNNING


def test_postgres_new_stop_beats_delayed_start_and_ttl_persists(postgres_factory):
    now = [datetime.now(UTC)]
    settings = Settings(runtime_mode="mock")
    repository = SandboxRepository(postgres_factory, settings, clock=lambda: now[0])
    jobs = SqlJobStore(postgres_factory, settings, clock=lambda: now[0])
    sandbox = add(repository)
    repository.request(sandbox.id, Action.START)
    old = jobs.claim("slow-worker")
    repository.request(sandbox.id, Action.STOP)
    assert not jobs.complete(old, Observation(SandboxStatus.RUNNING))
    assert jobs.complete(jobs.claim("stop-worker"), Observation(SandboxStatus.STOPPED))
    repository.request(sandbox.id, Action.START)
    assert jobs.complete(jobs.claim("restart-worker"), Observation(SandboxStatus.RUNNING))
    now[0] += timedelta(seconds=60)
    assert jobs.enqueue_expired() == 1
    assert jobs.enqueue_expired() == 0
    assert jobs.complete(jobs.claim("ttl-worker"), Observation(SandboxStatus.STOPPED))
    # A new repository/worker process uses the same database records.
    recreated = SandboxRepository(postgres_factory, settings)
    assert recreated.get(sandbox.id).status == SandboxStatus.STOPPED
    assert len(recreated.list()) == 1
