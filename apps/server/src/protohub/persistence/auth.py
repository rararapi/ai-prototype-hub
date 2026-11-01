"""Local development identities; email login is deliberately not production auth."""

import hashlib
import re
import secrets
from collections.abc import Callable
from datetime import datetime, timedelta

from sqlalchemy import delete
from sqlalchemy.dialects.postgresql import insert as postgres_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session, sessionmaker

from protohub.domain.models import LoginSession, Principal
from protohub.persistence.models import SessionRow, UserRow, utcnow


class AuthenticationRequired(Exception):
    pass


class SessionRepository:
    def __init__(self, factory: sessionmaker[Session], clock: Callable[[], datetime] = utcnow):
        self.factory = factory
        self.clock = clock

    @staticmethod
    def digest(token: str) -> str:
        return hashlib.sha256(token.encode("ascii")).hexdigest()

    def login(self, email: str) -> LoginSession:
        now = self.clock()
        token = secrets.token_urlsafe(32)
        expires_at = now + timedelta(hours=24)
        with self.factory.begin() as session:
            dialect = session.get_bind().dialect.name
            insert = postgres_insert if dialect == "postgresql" else sqlite_insert
            session.execute(
                insert(UserRow).values(email=email, created_at=now).on_conflict_do_nothing()
            )
            # Bound storage for expired sessions during normal development logins.
            session.execute(delete(SessionRow).where(SessionRow.expires_at <= now))
            session.add(
                SessionRow(
                    token_digest=self.digest(token),
                    email=email,
                    expires_at=expires_at,
                    created_at=now,
                )
            )
        return LoginSession(token=token, email=email, expires_at=expires_at)

    def authenticate(self, authorization: str | None) -> Principal:
        token = self.token(authorization)
        with self.factory() as session:
            row = session.get(SessionRow, self.digest(token))
            if row is None or row.expires_at <= self.clock():
                raise AuthenticationRequired
            return Principal(email=row.email)

    @staticmethod
    def token(authorization: str | None) -> str:
        if authorization is None or not re.fullmatch(r"Bearer [A-Za-z0-9_-]{43}", authorization):
            raise AuthenticationRequired
        return authorization[7:]

    def logout(self, authorization: str | None) -> None:
        token = self.token(authorization)
        with self.factory.begin() as session:
            session.execute(delete(SessionRow).where(SessionRow.token_digest == self.digest(token)))
