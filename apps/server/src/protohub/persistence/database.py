from typing import Any

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool


def create_session_factory(database_url: str) -> sessionmaker[Session]:
    options: dict[str, Any] = {}
    if database_url.startswith("sqlite"):
        options["connect_args"] = {"check_same_thread": False}
        if database_url in {"sqlite://", "sqlite:///:memory:", "sqlite+pysqlite:///:memory:"}:
            options["poolclass"] = StaticPool
    elif database_url.startswith("postgresql"):
        options["connect_args"] = {"connect_timeout": 5}
        options["pool_timeout"] = 5
    engine = create_engine(database_url, pool_pre_ping=True, **options)
    return sessionmaker(bind=engine, expire_on_commit=False)


class SqlUnitOfWork:
    """Transaction helper; closes the Session on both success and failure."""

    def __init__(self, factory: sessionmaker[Session]):
        self.session = factory()

    def __enter__(self) -> "SqlUnitOfWork":
        return self

    def commit(self) -> None:
        self.session.commit()

    def rollback(self) -> None:
        self.session.rollback()

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        try:
            if exc_type is not None:
                self.rollback()
        finally:
            self.session.close()
