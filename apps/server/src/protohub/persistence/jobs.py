from collections.abc import Callable
from datetime import datetime, timedelta
from uuid import uuid4

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session, sessionmaker

from protohub.domain.models import (
    Action,
    DesiredState,
    Error,
    OperationStatus,
    SandboxStatus,
)
from protohub.domain.ports import Claim, Observation, ReconcileTarget, RuntimeSpec
from protohub.domain.settings import Settings
from protohub.persistence.models import AuditEventRow, OperationRow, SandboxRow, utcnow
from protohub.persistence.repository import DESIRED, FINISHED, clear_lease, enqueue_intent


class SqlJobStore:
    """At-least-once PostgreSQL queue with lease and generation fencing.

    Every write locks Sandbox before Operation, as the API does. Runtime I/O belongs
    outside these short transactions. SQLite supports deterministic unit tests only;
    PostgreSQL integration tests establish SKIP LOCKED concurrency behavior.
    """

    def __init__(
        self,
        factory: sessionmaker[Session],
        settings: Settings,
        clock: Callable[[], datetime] = utcnow,
    ):
        self.factory = factory
        self.settings = settings
        self.clock = clock

    def _current(
        self, sandbox: SandboxRow, operation: OperationRow, claim: Claim, now: datetime
    ) -> bool:
        return (
            sandbox.id == claim.sandbox_id
            and operation.sandbox_id == claim.sandbox_id
            and sandbox.active_operation_id == claim.operation_id
            and sandbox.generation == claim.generation == operation.generation
            and sandbox.desired_state == DESIRED[claim.action]
            and operation.action == claim.action
            and operation.status == OperationStatus.RUNNING
            and operation.lease_owner == claim.lease_owner
            and operation.lease_token == claim.lease_token
            and operation.lease_expires_at is not None
            and operation.lease_expires_at > now
        )

    def _locked(self, session: Session, claim: Claim) -> tuple[SandboxRow, OperationRow] | None:
        sandbox = session.scalar(
            select(SandboxRow).where(SandboxRow.id == claim.sandbox_id).with_for_update()
        )
        if sandbox is None:
            return None
        operation = session.scalar(
            select(OperationRow).where(OperationRow.id == claim.operation_id).with_for_update()
        )
        if operation is None or not self._current(sandbox, operation, claim, self.clock()):
            return None
        return sandbox, operation

    def _final_failure(
        self,
        session: Session,
        sandbox: SandboxRow,
        operation: OperationRow,
        error: Error,
        now: datetime,
    ) -> None:
        operation.status = OperationStatus.FAILED
        operation.error = error.model_dump()
        operation.updated_at = now
        clear_lease(operation)
        sandbox.status = SandboxStatus.FAILED
        sandbox.error = error.model_dump()
        sandbox.preview_url = None
        sandbox.expires_at = None
        sandbox.updated_at = now
        session.add(
            AuditEventRow(
                sandbox_id=sandbox.id,
                operation_id=operation.id,
                event="operation_failed",
                created_at=now,
            )
        )

    def claim(self, owner: str, lease_seconds: int = 30) -> Claim | None:
        if not owner or len(owner) > 128 or lease_seconds <= 0:
            raise ValueError("A bounded owner and positive lease are required")
        # Drain exhausted leases without leaving a poison job at the queue head.
        for _ in range(100):
            with self.factory.begin() as session:
                now = self.clock()
                eligible = or_(
                    and_(
                        OperationRow.status == OperationStatus.QUEUED,
                        OperationRow.available_at <= now,
                    ),
                    and_(
                        OperationRow.status == OperationStatus.RUNNING,
                        OperationRow.lease_expires_at <= now,
                    ),
                )
                sandbox = session.scalar(
                    select(SandboxRow)
                    .join(OperationRow, SandboxRow.active_operation_id == OperationRow.id)
                    .where(eligible)
                    .order_by(OperationRow.available_at, OperationRow.id)
                    .limit(1)
                    .with_for_update(of=SandboxRow, skip_locked=True)
                )
                if sandbox is None:
                    return None
                operation = session.scalar(
                    select(OperationRow)
                    .where(OperationRow.id == sandbox.active_operation_id)
                    .with_for_update()
                )
                if operation is None:
                    return None
                now = self.clock()
                action = Action(operation.action)
                # The join predicate used an earlier statement snapshot. Recheck after
                # both locks so a just-renewed lease cannot be stolen.
                claimable = (
                    operation.status == OperationStatus.QUEUED and operation.available_at <= now
                ) or (
                    operation.status == OperationStatus.RUNNING
                    and operation.lease_expires_at is not None
                    and operation.lease_expires_at <= now
                )
                if not claimable:
                    continue
                if (
                    sandbox.generation != operation.generation
                    or sandbox.desired_state != DESIRED[action]
                ):
                    operation.status = OperationStatus.SUPERSEDED
                    clear_lease(operation)
                    operation.updated_at = now
                    continue
                if operation.attempt_count >= min(3, self.settings.max_attempts):
                    self._final_failure(
                        session,
                        sandbox,
                        operation,
                        Error(code="attempts_exhausted", message="Worker retry limit reached"),
                        now,
                    )
                    continue
                operation.status = OperationStatus.RUNNING
                operation.attempt_count += 1
                operation.lease_owner = owner
                operation.lease_token = uuid4()
                operation.lease_expires_at = now + timedelta(seconds=lease_seconds)
                operation.updated_at = now
                operation.error = None
                result = Claim(
                    operation_id=operation.id,
                    sandbox_id=sandbox.id,
                    generation=operation.generation,
                    action=action,
                    lease_owner=owner,
                    lease_token=operation.lease_token,
                    lease_expires_at=operation.lease_expires_at,
                    attempt_count=operation.attempt_count,
                    spec=RuntimeSpec(sandbox.id, sandbox.generation, sandbox.template_id),
                )
            return result
        return None

    def is_current(self, claim: Claim) -> bool:
        with self.factory.begin() as session:
            return self._locked(session, claim) is not None

    def heartbeat(self, claim: Claim, lease_seconds: int = 30) -> bool:
        if lease_seconds <= 0:
            return False
        with self.factory.begin() as session:
            locked = self._locked(session, claim)
            if locked is None:
                return False
            _, operation = locked
            operation.lease_expires_at = self.clock() + timedelta(seconds=lease_seconds)
            operation.updated_at = self.clock()
        return True

    def complete(self, claim: Claim, observation: Observation) -> bool:
        if observation.status != FINISHED[claim.action] or observation.error is not None:
            return False
        if (
            claim.action == Action.START
            and self.settings.runtime_mode == "real-kind"
            and not observation.preview_url
        ):
            return False
        with self.factory.begin() as session:
            locked = self._locked(session, claim)
            if locked is None:
                return False
            sandbox, operation = locked
            now = self.clock()
            operation.status = OperationStatus.SUCCEEDED
            operation.updated_at = now
            operation.error = None
            clear_lease(operation)
            sandbox.status = observation.status
            sandbox.error = None
            sandbox.updated_at = now
            sandbox.preview_url = (
                observation.preview_url
                if self.settings.runtime_mode == "real-kind"
                and observation.status == SandboxStatus.RUNNING
                else None
            )
            sandbox.expires_at = (
                now + timedelta(seconds=sandbox.ttl_seconds)
                if observation.status == SandboxStatus.RUNNING
                else None
            )
            session.add(
                AuditEventRow(
                    sandbox_id=sandbox.id,
                    operation_id=operation.id,
                    event="operation_succeeded",
                    created_at=now,
                )
            )
        return True

    def fail(self, claim: Claim, error: Error, retryable: bool = False) -> bool:
        with self.factory.begin() as session:
            locked = self._locked(session, claim)
            if locked is None:
                return False
            sandbox, operation = locked
            now = self.clock()
            if retryable and operation.attempt_count < min(3, self.settings.max_attempts):
                operation.status = OperationStatus.QUEUED
                operation.error = error.model_dump()
                operation.available_at = now + timedelta(seconds=2**operation.attempt_count)
                operation.updated_at = now
                clear_lease(operation)
            else:
                self._final_failure(session, sandbox, operation, error, now)
        return True

    def supersede(self, claim: Claim) -> bool:
        with self.factory.begin() as session:
            locked = self._locked(session, claim)
            if locked is None:
                return False
            _, operation = locked
            operation.status = OperationStatus.SUPERSEDED
            operation.updated_at = self.clock()
            clear_lease(operation)
        return True

    def enqueue_expired(self) -> int:
        with self.factory.begin() as session:
            now = self.clock()
            rows = session.scalars(
                select(SandboxRow)
                .where(
                    SandboxRow.desired_state == DesiredState.RUNNING, SandboxRow.expires_at <= now
                )
                .with_for_update(skip_locked=True)
            )
            count = 0
            for sandbox in rows:
                enqueue_intent(session, sandbox, Action.STOP, now)
                count += 1
        return count

    def reconcile_targets(self) -> list[ReconcileTarget]:
        with self.factory() as session:
            rows = session.scalars(
                select(SandboxRow)
                .outerjoin(OperationRow, OperationRow.id == SandboxRow.active_operation_id)
                .where(
                    or_(
                        SandboxRow.desired_state.in_([DesiredState.STOPPED, DesiredState.DELETED]),
                        SandboxRow.status.in_([SandboxStatus.RUNNING, SandboxStatus.FAILED]),
                        and_(
                            SandboxRow.status == SandboxStatus.STARTING,
                            OperationRow.status.notin_(
                                [OperationStatus.QUEUED, OperationStatus.RUNNING]
                            ),
                        ),
                    )
                )
            )
            return [
                ReconcileTarget(
                    spec=RuntimeSpec(row.id, row.generation, row.template_id),
                    desired_state=DesiredState(row.desired_state),
                    status=SandboxStatus(row.status),
                )
                for row in rows
            ]

    def reconcile_observation(self, spec: RuntimeSpec, observation: Observation) -> bool:
        if observation.status not in {
            SandboxStatus.RUNNING,
            SandboxStatus.STARTING,
            SandboxStatus.STOPPED,
            SandboxStatus.FAILED,
        }:
            return False
        if observation.status == SandboxStatus.RUNNING and observation.error is not None:
            return False
        if (
            observation.status == SandboxStatus.RUNNING
            and self.settings.runtime_mode == "real-kind"
            and not observation.preview_url
        ):
            return False
        with self.factory.begin() as session:
            sandbox = session.scalar(
                select(SandboxRow).where(SandboxRow.id == spec.sandbox_id).with_for_update()
            )
            if (
                sandbox is None
                or sandbox.generation != spec.generation
                or sandbox.desired_state != DesiredState.RUNNING
                or sandbox.status not in {SandboxStatus.RUNNING, SandboxStatus.STARTING}
            ):
                return False
            if sandbox.active_operation_id is not None:
                active = session.scalar(
                    select(OperationRow)
                    .where(OperationRow.id == sandbox.active_operation_id)
                    .with_for_update()
                )
                if active is not None and active.status in {
                    OperationStatus.QUEUED,
                    OperationStatus.RUNNING,
                }:
                    return False
            sandbox.status = (
                SandboxStatus.STARTING
                if observation.status == SandboxStatus.STOPPED
                else observation.status
            )
            sandbox.preview_url = (
                observation.preview_url
                if sandbox.status == SandboxStatus.RUNNING
                and self.settings.runtime_mode == "real-kind"
                else None
            )
            sandbox.error = observation.error.model_dump() if observation.error else None
            sandbox.updated_at = self.clock()
            # expires_at deliberately remains unchanged: observing cannot renew TTL.
        return True
