"""Non-skippable real PostgreSQL AI reservation and migration evidence."""

import os
from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
from pathlib import Path
from threading import Barrier
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url

import protohub.persistence.ai as ai_storage
from protohub.ai.gemini import GeneratedPlan
from protohub.domain.models import AiBrief, AiConfig, AiCreateRequest, AiReviseRequest
from protohub.domain.settings import Settings
from protohub.persistence.ai import AiQuotaExceeded, AiRepository
from protohub.persistence.auth import SessionRepository
from protohub.persistence.database import create_session_factory
from protohub.persistence.repository import Conflict

pytestmark = pytest.mark.postgres
ROOT = Path(__file__).resolve().parents[4]


@pytest.fixture
def ai_postgres(monkeypatch):
    raw = os.environ.get("PROTOHUB_TEST_DATABASE_URL")
    if not raw:
        pytest.fail(
            "Real PostgreSQL AI tests require a dedicated database; not skipped", pytrace=False
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
    schema = "protohub_ai_" + uuid4().hex
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
        config = Config(str(ROOT / "apps/server/alembic.ini"))
        command.upgrade(config, "head")
        command.upgrade(config, "head")
        factory = create_session_factory(isolated_url)
        yield factory, isolated_url
    finally:
        if factory is not None:
            factory.kw["bind"].dispose()
        if created:
            with admin.begin() as connection:
                connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()


def request():
    return AiCreateRequest(
        request_id=uuid4(),
        brief=AiBrief(purpose="Compare figures", audience="Team", success="Read the chart"),
        config=AiConfig(
            template="management-dashboard",
            title="Sample",
            subtitle="Sample data",
            color="purple",
            trend=True,
            departments=False,
            cash_flow=False,
        ),
    )


def settings():
    return Settings(
        ai_enabled=True,
        ai_vertex_project="example-project",
        environment="test",
        ai_hourly_limit=10,
        ai_daily_limit=10,
        ai_global_daily_limit=1,
    )


def test_postgres_quota_is_atomic_between_independent_connections_without_process_lock(
    ai_postgres,
    monkeypatch,
):
    factory, database_url = ai_postgres
    # Prove PostgreSQL locking, not the in-process SQLite test mutex.
    monkeypatch.setattr(ai_storage, "_PROCESS_LOCK", nullcontext())
    owners = [f"owner{index}@example.test" for index in range(5)]
    for owner in owners:
        SessionRepository(factory).login(owner)
    barrier = Barrier(len(owners))

    def reserve(owner):
        independent = create_session_factory(database_url)
        try:
            repository = AiRepository(independent, settings())
            barrier.wait(timeout=10)
            try:
                reservation = repository.reserve(owner, request())
                return reservation
            except AiQuotaExceeded:
                return None
        finally:
            independent.kw["bind"].dispose()

    with ThreadPoolExecutor(max_workers=len(owners)) as executor:
        results = list(executor.map(reserve, owners))
    assert sum(result is not None for result in results) == 1
    with factory() as session:
        assert session.scalar(text("SELECT COUNT(*) FROM ai_generations")) == 1
        assert session.scalar(text("SELECT id FROM ai_quotas")) == "global"


def test_postgres_owned_plans_and_idempotency_survive_new_repository_and_delete(
    ai_postgres,
):
    factory, database_url = ai_postgres
    owner = "owner@example.test"
    SessionRepository(factory).login(owner)
    repository = AiRepository(factory, settings())
    payload = request()
    reserved = repository.reserve(owner, payload)
    generated = GeneratedPlan(config=payload.config, summary="A real database fixture")
    first = repository.complete(reserved, generated)
    fresh = create_session_factory(database_url)
    try:
        restarted = AiRepository(fresh, settings())
        assert restarted.reserve(owner, payload).cached == first
        assert restarted.get(first.id, owner) == first
        assert restarted.confirm(first.id, owner, first.revision).status == "ready"
        restarted.settings.ai_global_daily_limit = 10
        pending = restarted.reserve(
            owner,
            AiReviseRequest(
                request_id=uuid4(),
                expected_revision=1,
                instruction="Blue",
            ),
            first.id,
        )
        repository.delete(first.id, owner)
        with pytest.raises(Conflict):
            restarted.complete(pending, generated)
        assert restarted.list(owner) == []
        tables = set(inspect(fresh.kw["bind"]).get_table_names())
        assert {"ai_applications", "ai_generations", "ai_quotas"}.issubset(tables)
    finally:
        fresh.kw["bind"].dispose()


def test_postgres_completion_expiry_is_checked_after_a_real_quota_row_lock_wait(
    ai_postgres,
    clock,
    monkeypatch,
):
    from concurrent.futures import TimeoutError as FutureTimeout
    from threading import Event

    factory, _ = ai_postgres
    owner = "owner@example.test"
    SessionRepository(factory).login(owner)
    repository = AiRepository(factory, settings(), clock)
    payload = request()
    reserved = repository.reserve(owner, payload)
    entered = Event()
    original = repository.lock

    def observed_lock(session):
        entered.set()
        original(session)

    monkeypatch.setattr(repository, "lock", observed_lock)
    with factory.kw["bind"].connect() as holder, ThreadPoolExecutor(max_workers=1) as executor:
        transaction = holder.begin()
        holder.execute(text("SELECT id FROM ai_quotas WHERE id='global' FOR UPDATE"))
        future = executor.submit(
            repository.complete, reserved, GeneratedPlan(config=payload.config, summary="Late")
        )
        try:
            assert entered.wait(5)
            with pytest.raises(FutureTimeout):
                future.result(timeout=0.1)
            clock.advance(repository.settings.ai_timeout_seconds + 11)
        finally:
            transaction.commit()
        with pytest.raises(Conflict):
            future.result(timeout=5)
    assert repository.list(owner) == []


def test_postgres_reservation_uses_post_lock_time_for_quota_and_new_lease(
    ai_postgres,
    clock,
    monkeypatch,
):
    from concurrent.futures import TimeoutError as FutureTimeout
    from datetime import timedelta
    from threading import Event

    from protohub.persistence.models import AiGenerationRow

    factory, _ = ai_postgres
    owner = "owner@example.test"
    SessionRepository(factory).login(owner)
    limits = settings()
    limits.ai_global_daily_limit = 10
    limits.ai_hourly_limit = 1
    repository = AiRepository(factory, limits, clock)
    first = repository.reserve(owner, request())
    repository.fail(first)
    entered = Event()
    original = repository.lock

    def observed_lock(session):
        entered.set()
        original(session)

    monkeypatch.setattr(repository, "lock", observed_lock)
    with factory.kw["bind"].connect() as holder, ThreadPoolExecutor(max_workers=1) as executor:
        transaction = holder.begin()
        holder.execute(text("SELECT id FROM ai_quotas WHERE id='global' FOR UPDATE"))
        future = executor.submit(repository.reserve, owner, request())
        try:
            assert entered.wait(5)
            with pytest.raises(FutureTimeout):
                future.result(timeout=0.1)
            clock.advance(3601)
        finally:
            transaction.commit()
        reservation = future.result(timeout=5)
    with factory() as session:
        row = session.get(AiGenerationRow, reservation.request_id)
        assert row.created_at == clock.value
        assert row.expires_at == clock.value + timedelta(seconds=limits.ai_timeout_seconds + 10)
