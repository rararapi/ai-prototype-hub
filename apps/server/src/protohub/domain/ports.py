"""Synchronous short DB calls; runtime calls must not hold a DB transaction."""

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol
from uuid import UUID

from protohub.domain.models import Action, DesiredState, Error, SandboxStatus


@dataclass(frozen=True)
class RuntimeSpec:
    sandbox_id: UUID
    generation: int
    template_id: str = "hello-web"
    may_mutate: Callable[[], bool] | None = field(default=None, compare=False, repr=False)


@dataclass(frozen=True)
class Observation:
    status: SandboxStatus
    preview_url: str | None = None
    error: Error | None = None


@dataclass(frozen=True)
class Claim:
    operation_id: UUID
    sandbox_id: UUID
    generation: int
    action: Action
    lease_owner: str
    lease_token: UUID
    lease_expires_at: datetime
    attempt_count: int
    spec: RuntimeSpec


@dataclass(frozen=True)
class ReconcileTarget:
    spec: RuntimeSpec
    desired_state: DesiredState
    status: SandboxStatus


class RuntimeFailure(Exception):
    """Safe, bounded diagnostic; raw provider exceptions must be suppressed."""

    def __init__(self, code: str, message: str, retryable: bool = False):
        self.error = Error(code=code, message=message)
        self.retryable = retryable
        super().__init__(message)


class RuntimeProvider(Protocol):
    def ensure_started(self, spec: RuntimeSpec) -> None: ...
    def observe(self, spec: RuntimeSpec) -> Observation: ...
    def ensure_stopped(self, spec: RuntimeSpec) -> None: ...
    def ensure_deleted(self, spec: RuntimeSpec) -> None: ...


class JobStore(Protocol):
    def claim(self, owner: str, lease_seconds: int = 30) -> Claim | None: ...
    def is_current(self, claim: Claim) -> bool: ...
    def heartbeat(self, claim: Claim, lease_seconds: int = 30) -> bool: ...
    def complete(self, claim: Claim, observation: Observation) -> bool: ...
    def fail(self, claim: Claim, error: Error, retryable: bool = False) -> bool: ...
    def supersede(self, claim: Claim) -> bool: ...
    def enqueue_expired(self) -> int: ...
    def reconcile_targets(self) -> list[ReconcileTarget]: ...
    def reconcile_observation(self, spec: RuntimeSpec, observation: Observation) -> bool: ...


class UnitOfWork(Protocol):
    """A store call owns one short transaction and closes it before returning."""

    def commit(self) -> None: ...
    def rollback(self) -> None: ...
