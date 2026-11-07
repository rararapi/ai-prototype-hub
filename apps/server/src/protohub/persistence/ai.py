"""Durable, owned Gemini plans and serialized, charged-at-reservation quotas."""

import hashlib
import json
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta
from threading import RLock
from uuid import UUID, uuid4

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session, sessionmaker

from protohub.ai.gemini import GeneratedPlan
from protohub.domain.models import (
    AiApplication,
    AiBrief,
    AiConfig,
    AiCreateRequest,
    AiReviseRequest,
)
from protohub.domain.settings import Settings
from protohub.persistence.models import (
    AiApplicationRow,
    AiGenerationRow,
    AiQuotaRow,
    utcnow,
)
from protohub.persistence.repository import Conflict, NotFound

# PostgreSQL row locks provide cross-process serialization. This local lock also
# prevents SQLite StaticPool connection overlap in deterministic unit tests.
_PROCESS_LOCK = RLock()


class AiQuotaExceeded(Exception):
    pass


class AiGenerationFailed(Exception):
    pass


@dataclass(frozen=True)
class Reservation:
    request_id: UUID
    token: UUID
    owner: str
    brief: AiBrief
    config: AiConfig
    instruction: str
    application_id: UUID | None = None
    expected_revision: int | None = None
    cached: AiApplication | None = None


def application(row: AiApplicationRow) -> AiApplication:
    return AiApplication.model_validate(row)


class AiRepository:
    def __init__(
        self,
        factory: sessionmaker[Session],
        settings: Settings,
        clock: Callable[[], datetime] = utcnow,
    ):
        self.factory, self.settings, self.clock = factory, settings, clock

    @contextmanager
    def transaction(self) -> Iterator[Session]:
        with _PROCESS_LOCK, self.factory() as session:
            try:
                yield session
            except (Conflict, NotFound, AiQuotaExceeded, AiGenerationFailed):
                # Only expiry/failure cleanup precedes domain rejections.
                session.commit()
                raise
            except Exception:
                session.rollback()
                raise
            else:
                session.commit()

    @staticmethod
    def lock(session: Session) -> None:
        dialect = session.get_bind().dialect.name
        insert = pg_insert if dialect == "postgresql" else sqlite_insert
        session.execute(insert(AiQuotaRow).values(id="global").on_conflict_do_nothing())
        session.scalar(select(AiQuotaRow).where(AiQuotaRow.id == "global").with_for_update())

    @staticmethod
    def owned(session: Session, application_id: UUID, owner: str) -> AiApplicationRow:
        row = session.scalar(
            select(AiApplicationRow)
            .where(
                AiApplicationRow.id == application_id,
                AiApplicationRow.owner_email == owner,
                AiApplicationRow.status != "deleted",
            )
            .with_for_update()
        )
        if row is None:
            raise NotFound
        return row

    def list(self, owner: str) -> list[AiApplication]:
        with _PROCESS_LOCK, self.factory() as session:
            rows = session.scalars(
                select(AiApplicationRow)
                .where(AiApplicationRow.owner_email == owner, AiApplicationRow.status != "deleted")
                .order_by(AiApplicationRow.created_at.desc(), AiApplicationRow.id)
            ).all()
            return [application(row) for row in rows]

    def get(self, application_id: UUID, owner: str) -> AiApplication:
        with self.transaction() as session:
            return application(self.owned(session, application_id, owner))

    def reserve(
        self,
        owner: str,
        payload: AiCreateRequest | AiReviseRequest,
        application_id: UUID | None = None,
    ) -> Reservation:
        digest = hashlib.sha256(
            json.dumps(
                {
                    "application_id": str(application_id) if application_id else None,
                    "action": "revise" if application_id else "create",
                    "payload": payload.model_dump(mode="json"),
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
        with self.transaction() as session:
            self.lock(session)
            now = self.clock()
            session.execute(
                update(AiGenerationRow)
                .where(
                    AiGenerationRow.status == "running",
                    AiGenerationRow.expires_at <= now,
                )
                .values(status="failed", error_code="generation_expired")
            )
            prior = session.get(AiGenerationRow, payload.request_id)
            if prior is not None:
                if prior.owner_email != owner:
                    raise NotFound
                if prior.payload_hash != digest:
                    raise Conflict("Request ID was already used for different content")
                if prior.status == "succeeded" and prior.result and prior.application_id:
                    self.owned(session, prior.application_id, owner)
                    cached = AiApplication.model_validate(prior.result)
                    return Reservation(
                        prior.id,
                        prior.token,
                        owner,
                        cached.brief,
                        cached.config,
                        "",
                        prior.application_id,
                        cached.revision,
                        cached,
                    )
                if prior.status == "running":
                    raise Conflict("A generation with this request ID is already in progress")
                raise AiGenerationFailed
            if isinstance(payload, AiReviseRequest):
                if application_id is None:
                    raise NotFound
                current = self.owned(session, application_id, owner)
                if current.revision != payload.expected_revision:
                    raise Conflict("The application changed; reload before generating")
                brief = AiBrief.model_validate(current.brief)
                config = AiConfig.model_validate(current.config)
                expected_revision: int | None = payload.expected_revision
            else:
                brief, config, expected_revision = payload.brief, payload.config, None
            active = session.scalar(
                select(func.count())
                .select_from(AiGenerationRow)
                .where(
                    AiGenerationRow.owner_email == owner,
                    AiGenerationRow.status == "running",
                    AiGenerationRow.expires_at > now,
                )
            )
            if active:
                raise Conflict("Another generation is already in progress")
            limits = [
                (now - timedelta(hours=1), owner, self.settings.ai_hourly_limit),
                (now - timedelta(days=1), owner, self.settings.ai_daily_limit),
                (now - timedelta(days=1), None, self.settings.ai_global_daily_limit),
            ]
            for since, principal, limit in limits:
                query = (
                    select(func.count())
                    .select_from(AiGenerationRow)
                    .where(AiGenerationRow.created_at > since)
                )
                if principal is not None:
                    query = query.where(AiGenerationRow.owner_email == principal)
                if (session.scalar(query) or 0) >= limit:
                    raise AiQuotaExceeded
            token = uuid4()
            session.add(
                AiGenerationRow(
                    id=payload.request_id,
                    owner_email=owner,
                    payload_hash=digest,
                    application_id=application_id,
                    status="running",
                    token=token,
                    expires_at=now + timedelta(seconds=self.settings.ai_timeout_seconds + 10),
                    created_at=now,
                )
            )
            return Reservation(
                payload.request_id,
                token,
                owner,
                brief,
                config,
                payload.instruction,
                application_id,
                expected_revision,
            )

    def complete(self, reservation: Reservation, generated: GeneratedPlan) -> AiApplication:
        generated = GeneratedPlan.model_validate(generated)
        with self.transaction() as session:
            self.lock(session)
            now = self.clock()
            record = session.get(AiGenerationRow, reservation.request_id)
            if (
                record is None
                or record.owner_email != reservation.owner
                or record.token != reservation.token
                or record.status != "running"
                or record.expires_at <= now
            ):
                if (
                    record is not None
                    and record.token == reservation.token
                    and record.status == "running"
                ):
                    record.status, record.error_code = "failed", "generation_expired"
                raise Conflict("The generation expired; reload before trying again")
            if reservation.application_id is None:
                row = AiApplicationRow(
                    id=uuid4(),
                    owner_email=reservation.owner,
                    brief=reservation.brief.model_dump(mode="json"),
                    config=generated.config.model_dump(mode="json"),
                    summary=generated.summary,
                    model=self.settings.ai_model,
                    status="draft",
                    revision=1,
                    usage=generated.usage.model_dump() if generated.usage else None,
                    created_at=now,
                    updated_at=now,
                )
                session.add(row)
            else:
                existing = session.get(AiApplicationRow, reservation.application_id)
                if (
                    existing is None
                    or existing.owner_email != reservation.owner
                    or existing.status == "deleted"
                    or existing.revision != reservation.expected_revision
                ):
                    record.status, record.error_code = "failed", "stale_generation"
                    raise Conflict("The application changed; the old generation was discarded")
                row = existing
                row.config = generated.config.model_dump(mode="json")
                row.summary, row.model = generated.summary, self.settings.ai_model
                row.usage = generated.usage.model_dump() if generated.usage else None
                row.revision += 1
                row.status, row.updated_at = "draft", now
            session.flush()
            result = application(row)
            record.application_id = row.id
            record.status, record.error_code = "succeeded", None
            record.result = result.model_dump(mode="json")
            return result

    def fail(self, reservation: Reservation) -> None:
        with self.transaction() as session:
            self.lock(session)
            session.execute(
                update(AiGenerationRow)
                .where(
                    AiGenerationRow.id == reservation.request_id,
                    AiGenerationRow.owner_email == reservation.owner,
                    AiGenerationRow.token == reservation.token,
                    AiGenerationRow.status == "running",
                )
                .values(status="failed", error_code="generation_failed")
            )

    def confirm(self, application_id: UUID, owner: str, revision: int) -> AiApplication:
        with self.transaction() as session:
            self.lock(session)
            row = self.owned(session, application_id, owner)
            if row.revision != revision:
                raise Conflict("The application changed; review the current version")
            active = session.scalar(
                select(func.count())
                .select_from(AiGenerationRow)
                .where(
                    AiGenerationRow.application_id == application_id,
                    AiGenerationRow.status == "running",
                    AiGenerationRow.expires_at > self.clock(),
                )
            )
            if active:
                raise Conflict("Wait for the current generation before confirming")
            row.status, row.updated_at = "ready", self.clock()
            return application(row)

    def delete(self, application_id: UUID, owner: str) -> None:
        with self.transaction() as session:
            self.lock(session)
            row = session.get(AiApplicationRow, application_id)
            if row is None or row.owner_email != owner:
                raise NotFound
            if row.status != "deleted":
                row.status, row.updated_at = "deleted", self.clock()
                row.revision += 1
            session.execute(
                update(AiGenerationRow)
                .where(
                    AiGenerationRow.application_id == application_id,
                    AiGenerationRow.status == "running",
                )
                .values(status="failed", error_code="application_deleted")
            )
