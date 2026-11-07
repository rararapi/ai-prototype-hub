"""Local and Google-verified sessions on the same application-owned principals."""

import hashlib
import re
import secrets
from collections.abc import Callable
from datetime import datetime, timedelta

from sqlalchemy import delete, or_, select, update
from sqlalchemy.dialects.postgresql import insert as postgres_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from protohub.domain.models import LoginRequest, LoginSession, Principal
from protohub.persistence.models import GoogleAccountRow, SessionRow, UserRow, utcnow


class AuthenticationRequired(Exception):
    pass


def validate_subject(subject: str) -> None:
    # OIDC sub is case-sensitive ASCII and at most 255 characters.
    if not re.fullmatch(r"[!-~]{1,255}", subject):
        raise ValueError("Invalid Google subject")


class SessionRepository:
    def __init__(self, factory: sessionmaker[Session], clock: Callable[[], datetime] = utcnow):
        self.factory = factory
        self.clock = clock

    @staticmethod
    def digest(token: str) -> str:
        return hashlib.sha256(token.encode("ascii")).hexdigest()

    @staticmethod
    def _insert(session: Session):
        return postgres_insert if session.get_bind().dialect.name == "postgresql" else sqlite_insert

    def _issue(self, session: Session, email: str, google_subject: str | None) -> LoginSession:
        now = self.clock()
        token = secrets.token_urlsafe(32)
        expires_at = now + timedelta(hours=24)
        session.execute(
            self._insert(session)(UserRow)
            .values(email=email, created_at=now)
            .on_conflict_do_nothing()
        )
        session.execute(delete(SessionRow).where(SessionRow.expires_at <= now))
        session.add(
            SessionRow(
                token_digest=self.digest(token),
                email=email,
                google_subject=google_subject,
                expires_at=expires_at,
                created_at=now,
            )
        )
        return LoginSession(token=token, email=email, expires_at=expires_at)

    def login(self, email: str) -> LoginSession:
        with self.factory.begin() as session:
            return self._issue(session, email, None)

    def login_google(self, email: str, subject: str, authoritative: bool) -> LoginSession:
        try:
            email = LoginRequest(email=email).email
            validate_subject(subject)
        except ValueError:
            raise AuthenticationRequired from None
        allowed = GoogleAccountRow.subject == subject
        if authoritative:
            allowed = or_(allowed, GoogleAccountRow.subject.is_(None))
        try:
            with self.factory.begin() as session:
                # Compare and bind under a row lock, including on repeat login. Removal
                # of the same membership serializes with this transaction.
                bound = session.scalar(
                    update(GoogleAccountRow)
                    .where(GoogleAccountRow.email == email, GoogleAccountRow.active, allowed)
                    .values(subject=subject)
                    .returning(GoogleAccountRow.email)
                )
                if bound is None:
                    raise AuthenticationRequired
                return self._issue(session, email, subject)
        except IntegrityError:
            # A subject already bound to a different email cannot migrate on login.
            raise AuthenticationRequired from None

    def add_account(self, email: str, subject: str | None = None) -> None:
        email = LoginRequest(email=email).email
        if subject is not None:
            validate_subject(subject)
        try:
            with self.factory.begin() as session:
                # Revocation preserves the bound subject. An assignment of the same email to
                # another Google user must not transfer email-keyed sandboxes or shares.
                updates: dict[str, str | bool] = {"active": True}
                allowed = None
                if subject is not None:
                    updates["subject"] = subject
                    allowed = or_(
                        GoogleAccountRow.subject.is_(None), GoogleAccountRow.subject == subject
                    )
                added = session.scalar(
                    self._insert(session)(GoogleAccountRow)
                    .values(email=email, subject=subject, active=True)
                    .on_conflict_do_update(
                        index_elements=[GoogleAccountRow.email], set_=updates, where=allowed
                    )
                    .returning(GoogleAccountRow.email)
                )
                if added is None:
                    raise ValueError("Email already bound to a different Google identity")
        except IntegrityError:
            raise ValueError("Google identity already bound to another account") from None

    def remove_account(self, email: str) -> None:
        email = LoginRequest(email=email).email
        with self.factory.begin() as session:
            session.execute(
                update(GoogleAccountRow).where(GoogleAccountRow.email == email).values(active=False)
            )
            session.execute(
                delete(SessionRow).where(
                    SessionRow.email == email, SessionRow.google_subject.is_not(None)
                )
            )

    def authenticate(self, authorization: str | None, *, google: bool = False) -> Principal:
        token = self.token(authorization)
        query = select(SessionRow.email).where(
            SessionRow.token_digest == self.digest(token), SessionRow.expires_at > self.clock()
        )
        if google:
            query = query.join(
                GoogleAccountRow,
                (SessionRow.email == GoogleAccountRow.email)
                & (SessionRow.google_subject == GoogleAccountRow.subject)
                & GoogleAccountRow.active,
            )
        else:
            query = query.where(SessionRow.google_subject.is_(None))
        with self.factory() as session:
            email = session.scalar(query)
            if email is None:
                raise AuthenticationRequired
            return Principal(email=email)

    @staticmethod
    def token(authorization: str | None) -> str:
        if authorization is None or not re.fullmatch(r"Bearer [A-Za-z0-9_-]{43}", authorization):
            raise AuthenticationRequired
        return authorization[7:]

    def logout(self, authorization: str | None) -> None:
        token = self.token(authorization)
        with self.factory.begin() as session:
            session.execute(delete(SessionRow).where(SessionRow.token_digest == self.digest(token)))
