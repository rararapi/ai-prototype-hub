"""Bounded operations with DB-fenced leases and eventual cleanup."""

import logging
import time
from dataclasses import replace
from functools import partial
from threading import Event, Thread
from uuid import uuid4

from protohub.domain.models import Action, DesiredState, Error, SandboxStatus
from protohub.domain.ports import (
    Claim,
    JobStore,
    Observation,
    ReconcileTarget,
    RuntimeFailure,
    RuntimeProvider,
)
from protohub.domain.settings import Settings

LOG = logging.getLogger(__name__)


class Worker:
    def __init__(
        self,
        store: JobStore,
        runtime: RuntimeProvider,
        settings: Settings,
        owner: str | None = None,
    ) -> None:
        self.store, self.runtime, self.settings = store, runtime, settings
        self.owner = owner or f"worker-{uuid4()}"
        self.stop = Event()

    def _current(self, claim: Claim, lost: Event) -> bool:
        return not lost.is_set() and not self.stop.is_set() and self.store.is_current(claim)

    def _heartbeat(self, claim: Claim, done: Event, lost: Event) -> None:
        interval = max(0.1, self.settings.lease_seconds / 3)
        while not done.wait(interval):
            try:
                if not self.store.heartbeat(claim, self.settings.lease_seconds):
                    lost.set()
                    return
            except Exception:
                # A disconnected holder cannot safely keep making runtime writes.
                lost.set()
                LOG.warning("lease_heartbeat_unavailable")
                return

    def run_once(self) -> bool:
        self.store.enqueue_expired()
        claim = self.store.claim(self.owner, self.settings.lease_seconds)
        if claim is None:
            return False
        done, lost = Event(), Event()
        heartbeat = Thread(target=self._heartbeat, args=(claim, done, lost), daemon=True)
        heartbeat.start()
        try:
            if not self._current(claim, lost):
                return True
            action = {
                Action.START: self.runtime.ensure_started,
                Action.STOP: self.runtime.ensure_stopped,
                Action.DELETE: self.runtime.ensure_deleted,
            }[claim.action]
            guarded = replace(claim.spec, may_mutate=lambda: self._current(claim, lost))
            action(guarded)
            deadline = time.monotonic() + self.settings.operation_timeout_seconds
            expected = {
                Action.START: SandboxStatus.RUNNING,
                Action.STOP: SandboxStatus.STOPPED,
                Action.DELETE: SandboxStatus.DELETED,
            }[claim.action]
            while self._current(claim, lost):
                observation = self.runtime.observe(claim.spec)
                if observation.status == expected or (
                    claim.action == Action.STOP and observation.status == SandboxStatus.DELETED
                ):
                    if claim.action == Action.STOP:
                        observation = Observation(SandboxStatus.STOPPED)
                    if self._current(claim, lost):
                        self.store.complete(claim, observation)
                    return True
                if observation.status == SandboxStatus.FAILED:
                    raise RuntimeFailure("runtime_failed", "The sample could not become ready")
                if time.monotonic() >= deadline:
                    raise RuntimeFailure(
                        "runtime_timeout", "Timed out waiting for observed sample state"
                    )
                self.stop.wait(self.settings.poll_interval_seconds)
            return True
        except RuntimeFailure as exc:
            if self._current(claim, lost):
                self.store.fail(claim, exc.error, exc.retryable)
            return True
        except Exception:
            if self._current(claim, lost):
                self.store.fail(
                    claim,
                    Error(
                        code="runtime_unavailable", message="Sample operation could not complete"
                    ),
                    True,
                )
            LOG.warning("sample_operation_unavailable")
            return True
        finally:
            done.set()
            heartbeat.join(timeout=max(1, self.settings.lease_seconds / 3 + 1))

    def _can_reconcile(self, target: ReconcileTarget) -> bool:
        return not self.stop.is_set() and any(
            current.spec == target.spec
            and current.desired_state == target.desired_state
            and (current.status == SandboxStatus.FAILED) == (target.status == SandboxStatus.FAILED)
            for current in self.store.reconcile_targets()
        )

    def reconcile(self) -> None:
        for target in self.store.reconcile_targets():
            if self.stop.is_set():
                return
            try:
                # Re-read immediately before a side effect. Provider generation CAS adds a fence.
                if target not in self.store.reconcile_targets():
                    continue
                guarded = replace(target.spec, may_mutate=partial(self._can_reconcile, target))
                if (
                    target.desired_state == DesiredState.DELETED
                    or target.status == SandboxStatus.FAILED
                ):
                    self.runtime.ensure_deleted(guarded)
                elif target.desired_state == DesiredState.STOPPED:
                    self.runtime.ensure_stopped(guarded)
                elif target.status in {SandboxStatus.RUNNING, SandboxStatus.STARTING}:
                    observation = self.runtime.observe(target.spec)
                    if observation.status == SandboxStatus.DELETED:
                        observation = Observation(SandboxStatus.STOPPED)
                    if not self.store.reconcile_observation(target.spec, observation):
                        continue
                    if observation.status not in {SandboxStatus.RUNNING, SandboxStatus.FAILED}:
                        if not any(
                            t.spec == target.spec
                            and t.desired_state == DesiredState.RUNNING
                            and t.status != SandboxStatus.FAILED
                            for t in self.store.reconcile_targets()
                        ):
                            continue
                        self.runtime.ensure_started(guarded)
                    if observation.status != SandboxStatus.FAILED:
                        self.store.reconcile_observation(
                            target.spec, self.runtime.observe(target.spec)
                        )
            except RuntimeFailure as exc:
                if (
                    target.desired_state == DesiredState.RUNNING
                    and target.status != SandboxStatus.FAILED
                ):
                    self.store.reconcile_observation(
                        target.spec,
                        Observation(
                            SandboxStatus.STARTING if exc.retryable else SandboxStatus.FAILED,
                            error=exc.error,
                        ),
                    )
                LOG.warning("sample_reconcile_unavailable")

    def run(self) -> None:
        reconcile_at = 0.0
        while not self.stop.is_set():
            try:
                did_work = self.run_once()
                if time.monotonic() >= reconcile_at:
                    self.reconcile()
                    reconcile_at = time.monotonic() + 5
                if not did_work:
                    self.stop.wait(self.settings.poll_interval_seconds)
            except Exception:
                LOG.warning("worker_dependency_unavailable")
                self.stop.wait(2)
