from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from protohub.api.main import create_app
from protohub.domain.settings import Settings
from protohub.persistence.database import create_session_factory
from protohub.persistence.jobs import SqlJobStore
from protohub.persistence.models import Base
from protohub.persistence.repository import SandboxRepository


class Clock:
    def __init__(self):
        self.value = datetime(2026, 10, 30, tzinfo=UTC)

    def __call__(self):
        return self.value

    def advance(self, seconds):
        self.value += timedelta(seconds=seconds)


@pytest.fixture
def factory():
    factory = create_session_factory("sqlite://")
    Base.metadata.create_all(factory.kw["bind"])
    yield factory
    factory.kw["bind"].dispose()


@pytest.fixture
def settings():
    return Settings(database_url="sqlite://", runtime_mode="mock")


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def repository(factory, settings, clock):
    return SandboxRepository(factory, settings, clock=clock)


@pytest.fixture
def jobs(factory, settings, clock):
    return SqlJobStore(factory, settings, clock=clock)


@pytest.fixture
def client(factory, settings):
    with TestClient(create_app(settings, factory), base_url="http://localhost") as client:
        yield client
