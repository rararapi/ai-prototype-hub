from collections.abc import Callable
from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import delete, exists, or_, select
from sqlalchemy.orm import Session, sessionmaker

from protohub.domain.models import (
    Action,
    CreateSandbox,
    DesiredState,
    Operation,
    OperationStatus,
    Sandbox,
    SandboxStatus,
    ShareList,
)
from protohub.domain.settings import Settings
from protohub.persistence.models import (
    AuditEventRow,
    OperationRow,
    SandboxRow,
    SandboxShareRow,
    utcnow,
)

DESIRED = {
    Action.START: DesiredState.RUNNING,
    Action.STOP: DesiredState.STOPPED,
    Action.DELETE: DesiredState.DELETED,
}
PENDING = {
    Action.START: SandboxStatus.STARTING,
    Action.STOP: SandboxStatus.STOPPING,
    Action.DELETE: SandboxStatus.DELETING,
}
FINISHED = {
    Action.START: SandboxStatus.RUNNING,
    Action.STOP: SandboxStatus.STOPPED,
    Action.DELETE: SandboxStatus.DELETED,
}


class NotFound(Exception):
    pass


class Conflict(Exception):
    pass


def to_sandbox(row: SandboxRow) -> Sandbox:
    return Sandbox.model_validate(row)


def to_operation(row: OperationRow) -> Operation:
    return Operation.model_validate(row)


def clear_lease(row: OperationRow) -> None:
    row.lease_owner = None
    row.lease_token = None
    row.lease_expires_at = None


def enqueue_intent(
    session: Session, sandbox: SandboxRow, action: Action, now: datetime
) -> OperationRow:
    """Caller must hold the Sandbox row lock before entering this helper."""
    if sandbox.desired_state == DesiredState.DELETED and action != Action.DELETE:
        raise Conflict("Deleted applications cannot be started or stopped")
    active = None
    if sandbox.active_operation_id is not None:
        active = session.scalar(
            select(OperationRow)
            .where(OperationRow.id == sandbox.active_operation_id)
            .with_for_update()
        )
    if (
        active is not None
        and active.action == action
        and sandbox.desired_state == DESIRED[action]
        and sandbox.status != SandboxStatus.FAILED
        and active.status
        in {OperationStatus.QUEUED, OperationStatus.RUNNING, OperationStatus.SUCCEEDED}
    ):
        return active
    if active is not None and active.status in {OperationStatus.QUEUED, OperationStatus.RUNNING}:
        active.status = OperationStatus.SUPERSEDED
        active.updated_at = now
        clear_lease(active)
    sandbox.generation += 1
    operation = OperationRow(
        id=uuid4(),
        sandbox_id=sandbox.id,
        action=action,
        generation=sandbox.generation,
        status=OperationStatus.QUEUED,
        attempt_count=0,
        available_at=now,
        created_at=now,
        updated_at=now,
    )
    session.add(operation)
    sandbox.active_operation_id = operation.id
    sandbox.desired_state = DESIRED[action]
    sandbox.status = PENDING[action]
    sandbox.preview_url = None
    sandbox.expires_at = None
    sandbox.error = None
    sandbox.updated_at = now
    session.add(
        AuditEventRow(
            sandbox_id=sandbox.id,
            operation_id=operation.id,
            event=f"{action}_requested",
            created_at=now,
        )
    )
    session.flush()
    return operation


class SandboxRepository:
    def __init__(
        self,
        factory: sessionmaker[Session],
        settings: Settings,
        clock: Callable[[], datetime] = utcnow,
    ):
        self.factory = factory
        self.settings = settings
        self.clock = clock

    def create(self, payload: CreateSandbox, principal: str | None = None) -> Sandbox:
        now = self.clock()
        with self.factory.begin() as session:
            row = SandboxRow(
                id=uuid4(),
                owner_email=principal,
                name=payload.name.strip(),
                template_id=payload.template_id,
                ttl_seconds=payload.ttl_seconds,
                desired_state=DesiredState.STOPPED,
                status=SandboxStatus.STOPPED,
                generation=0,
                created_at=now,
                updated_at=now,
            )
            session.add(row)
            session.flush()
            session.add(AuditEventRow(sandbox_id=row.id, event="registered", created_at=now))
            result = to_sandbox(row)
        return result

    @staticmethod
    def visible_to(principal: str):
        return or_(
            SandboxRow.owner_email == principal,
            (SandboxRow.owner_email.is_not(None))
            & exists().where(
                SandboxShareRow.sandbox_id == SandboxRow.id,
                SandboxShareRow.email == principal,
            ),
        )

    def list(self, principal: str | None = None) -> list[Sandbox]:
        with self.factory() as session:
            query = select(SandboxRow).where(SandboxRow.desired_state != DesiredState.DELETED)
            if principal is not None:
                query = query.where(self.visible_to(principal))
            rows = session.scalars(query.order_by(SandboxRow.created_at.desc(), SandboxRow.id))
            return [to_sandbox(row) for row in rows]

    def get(self, sandbox_id: UUID, principal: str | None = None) -> Sandbox:
        with self.factory() as session:
            query = select(SandboxRow).where(SandboxRow.id == sandbox_id)
            if principal is not None:
                query = query.where(self.visible_to(principal))
            row = session.scalar(query)
            if row is None:
                raise NotFound
            return to_sandbox(row)

    def get_operation(self, operation_id: UUID, principal: str | None = None) -> Operation:
        with self.factory() as session:
            query = select(OperationRow).where(OperationRow.id == operation_id)
            if principal is not None:
                query = query.join(SandboxRow).where(self.visible_to(principal))
            row = session.scalar(query)
            if row is None:
                raise NotFound
            return to_operation(row)

    def request(self, sandbox_id: UUID, action: Action, principal: str | None = None) -> Operation:
        with self.factory.begin() as session:
            query = select(SandboxRow).where(SandboxRow.id == sandbox_id)
            if principal is not None:
                query = query.where(SandboxRow.owner_email == principal)
            row = session.scalar(query.with_for_update())
            if row is None:
                raise NotFound
            operation = enqueue_intent(session, row, action, self.clock())
            result = to_operation(operation)
        return result

    @staticmethod
    def shares_in_session(session: Session, sandbox_id: UUID) -> ShareList:
        return ShareList(
            emails=list(
                session.scalars(
                    select(SandboxShareRow.email)
                    .where(SandboxShareRow.sandbox_id == sandbox_id)
                    .order_by(SandboxShareRow.email)
                )
            )
        )

    def get_shares(self, sandbox_id: UUID, principal: str) -> ShareList:
        with self.factory() as session:
            row = session.scalar(
                select(SandboxRow).where(
                    SandboxRow.id == sandbox_id,
                    SandboxRow.owner_email == principal,
                    SandboxRow.desired_state != DesiredState.DELETED,
                )
            )
            if row is None:
                raise NotFound
            return self.shares_in_session(session, sandbox_id)

    def set_shares(self, sandbox_id: UUID, payload: ShareList, principal: str) -> ShareList:
        with self.factory.begin() as session:
            row = session.scalar(
                select(SandboxRow)
                .where(
                    SandboxRow.id == sandbox_id,
                    SandboxRow.owner_email == principal,
                    SandboxRow.desired_state != DesiredState.DELETED,
                )
                .with_for_update()
            )
            if row is None:
                raise NotFound
            session.execute(delete(SandboxShareRow).where(SandboxShareRow.sandbox_id == sandbox_id))
            for email in payload.emails:
                if email != principal:
                    session.add(SandboxShareRow(sandbox_id=sandbox_id, email=email))
            session.flush()
            return self.shares_in_session(session, sandbox_id)
