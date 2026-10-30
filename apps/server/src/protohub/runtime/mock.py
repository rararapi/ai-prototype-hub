"""Explicit simulation; never produces an HTTP preview URL."""

from threading import Lock
from uuid import UUID

from protohub.domain.models import SandboxStatus
from protohub.domain.ports import Observation, RuntimeFailure, RuntimeSpec


class MockRuntime:
    def __init__(self) -> None:
        self._states: dict[UUID, tuple[int, SandboxStatus]] = {}
        self._lock = Lock()

    def _set(self, spec: RuntimeSpec, status: SandboxStatus) -> None:
        with self._lock:
            if spec.may_mutate is not None and not spec.may_mutate():
                raise RuntimeFailure("lease_lost", "This operation no longer owns the sample")
            current = self._states.get(spec.sandbox_id)
            if current is not None and current[0] > spec.generation:
                raise RuntimeFailure("stale_generation", "A newer operation owns this sample")
            self._states[spec.sandbox_id] = (spec.generation, status)

    def ensure_started(self, spec: RuntimeSpec) -> None:
        if spec.template_id != "hello-web":
            raise RuntimeFailure(
                "invalid_template", "Only the trusted hello-web template is supported"
            )
        self._set(spec, SandboxStatus.RUNNING)

    def ensure_stopped(self, spec: RuntimeSpec) -> None:
        self._set(spec, SandboxStatus.STOPPED)

    def ensure_deleted(self, spec: RuntimeSpec) -> None:
        self._set(spec, SandboxStatus.DELETED)

    def observe(self, spec: RuntimeSpec) -> Observation:
        with self._lock:
            current = self._states.get(spec.sandbox_id)
            return Observation(current[1] if current else SandboxStatus.STOPPED)
