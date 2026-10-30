from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import JSON, CheckConstraint, ForeignKey, Index, String, UniqueConstraint, Uuid
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import DateTime, TypeDecorator


def utcnow() -> datetime:
    return datetime.now(UTC)


class UTCDateTime(TypeDecorator[datetime]):
    """Restore timezone information on SQLite; PostgreSQL uses timestamptz."""

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Any) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("UTC-aware timestamps are required")
        return value.astimezone(UTC)

    def process_result_value(self, value: datetime | None, dialect: Any) -> datetime | None:
        if value is None:
            return None
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


class Base(DeclarativeBase):
    pass


class SandboxRow(Base):
    __tablename__ = "sandboxes"
    __table_args__ = (
        CheckConstraint("generation >= 0", name="sandbox_generation_nonnegative"),
        CheckConstraint("ttl_seconds BETWEEN 60 AND 3600", name="sandbox_ttl_range"),
        CheckConstraint("template_id = 'hello-web'", name="sandbox_trusted_template"),
        CheckConstraint("desired_state IN ('running','stopped','deleted')", name="sandbox_desired"),
        CheckConstraint(
            "status IN ('stopped','starting','running','stopping','deleting','deleted','failed')",
            name="sandbox_status",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(64))
    template_id: Mapped[str] = mapped_column(String(32), default="hello-web")
    ttl_seconds: Mapped[int] = mapped_column(default=900)
    desired_state: Mapped[str] = mapped_column(String(16), default="stopped")
    status: Mapped[str] = mapped_column(String(16), default="stopped")
    generation: Mapped[int] = mapped_column(default=0)
    active_operation_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    preview_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    error: Mapped[dict[str, str] | None] = mapped_column(JSON, nullable=True)


class OperationRow(Base):
    __tablename__ = "operations"
    __table_args__ = (
        UniqueConstraint("sandbox_id", "generation", name="operation_generation_unique"),
        CheckConstraint("action IN ('start','stop','delete')", name="operation_action"),
        CheckConstraint(
            "status IN ('queued','running','succeeded','failed','superseded')",
            name="operation_status",
        ),
        CheckConstraint("attempt_count BETWEEN 0 AND 3", name="operation_attempt_range"),
        Index("operation_claim", "status", "available_at", "lease_expires_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    sandbox_id: Mapped[UUID] = mapped_column(ForeignKey("sandboxes.id"), index=True)
    action: Mapped[str] = mapped_column(String(16))
    generation: Mapped[int] = mapped_column()
    status: Mapped[str] = mapped_column(String(16), default="queued")
    attempt_count: Mapped[int] = mapped_column(default=0)
    lease_owner: Mapped[str | None] = mapped_column(String(128), nullable=True)
    lease_token: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    available_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    error: Mapped[dict[str, str] | None] = mapped_column(JSON, nullable=True)


class AuditEventRow(Base):
    __tablename__ = "audit_events"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    sandbox_id: Mapped[UUID] = mapped_column(ForeignKey("sandboxes.id"), index=True)
    operation_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    event: Mapped[str] = mapped_column(String(40))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
