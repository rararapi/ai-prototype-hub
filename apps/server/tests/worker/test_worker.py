import time
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from protohub.domain.models import Action, DesiredState, SandboxStatus
from protohub.domain.ports import Claim, Observation, ReconcileTarget, RuntimeFailure, RuntimeSpec
from protohub.domain.settings import Settings
from protohub.runtime.mock import MockRuntime
from protohub.worker import Worker


class Store:
    def __init__(self, action=Action.START):
        spec = RuntimeSpec(uuid4(), 1)
        self.item = Claim(
            uuid4(),
            spec.sandbox_id,
            1,
            action,
            "test",
            uuid4(),
            datetime.now(UTC) + timedelta(seconds=30),
            1,
            spec,
        )
        self.current = True
        self.done = []
        self.failures = []
        self.heartbeats = 0
        self.expired_calls = 0
        self.targets = []

    def enqueue_expired(self):
        self.expired_calls += 1
        return 0

    def claim(self, *_):
        return self.item

    def is_current(self, _):
        return self.current

    def heartbeat(self, *_):
        self.heartbeats += 1
        return self.current

    def complete(self, claim, observation):
        assert self.current
        self.done.append(observation)
        return True

    def fail(self, claim, error, retryable=False):
        assert self.current
        self.failures.append((error, retryable))
        return True

    def reconcile_targets(self):
        return self.targets

    def reconcile_observation(self, *_):
        return True


def test_worker_completes_only_observed_states_and_invokes_ttl():
    store = Store()
    Worker(store, MockRuntime(), Settings()).run_once()
    assert store.done == [Observation(SandboxStatus.RUNNING)]
    assert store.expired_calls == 1
    store.item = None
    assert not Worker(store, MockRuntime(), Settings()).run_once()


def test_lease_lost_during_provider_call_prevents_observe_and_complete():
    store = Store()

    class Runtime(MockRuntime):
        def ensure_started(self, spec):
            store.current = False

        def observe(self, spec):
            raise AssertionError("must not call provider after losing lease")

    Worker(store, Runtime(), Settings()).run_once()
    assert not store.done and not store.failures


def test_heartbeat_runs_during_io_without_holding_a_transaction():
    store = Store()

    class Runtime(MockRuntime):
        def ensure_started(self, spec):
            time.sleep(0.45)
            super().ensure_started(spec)

    Worker(store, Runtime(), Settings(lease_seconds=1)).run_once()
    assert store.heartbeats >= 1
    assert store.done


def test_timeout_and_retryability_propagate_safely():
    store = Store()

    class NeverReady(MockRuntime):
        def observe(self, spec):
            return Observation(SandboxStatus.STARTING)

    Worker(store, NeverReady(), Settings(operation_timeout_seconds=0)).run_once()
    assert store.failures[0][0].code == "runtime_timeout"
    assert store.failures[0][1] is False

    class TemporaryFailure(MockRuntime):
        def ensure_started(self, spec):
            raise RuntimeFailure("runtime_unavailable", "Sample runtime unavailable", True)

    store = Store()
    Worker(store, TemporaryFailure(), Settings()).run_once()
    assert store.failures[0][1] is True


def test_reconcile_cleans_failed_and_deleted_without_touching_other_apps():
    runtime = MockRuntime()
    first, second = RuntimeSpec(uuid4(), 1), RuntimeSpec(uuid4(), 1)
    runtime.ensure_started(first)
    runtime.ensure_started(second)
    store = Store()
    store.targets = [ReconcileTarget(first, DesiredState.RUNNING, SandboxStatus.FAILED)]
    worker = Worker(store, runtime, Settings())
    worker.reconcile()
    assert runtime.observe(first).status == SandboxStatus.DELETED
    assert runtime.observe(second).status == SandboxStatus.RUNNING
    store.targets = [ReconcileTarget(first, DesiredState.DELETED, SandboxStatus.DELETED)]
    worker.reconcile()
    assert runtime.observe(first).status == SandboxStatus.DELETED


def test_stop_absent_resources_still_completes_stopped():
    store = Store(Action.STOP)

    class Missing(MockRuntime):
        def observe(self, spec):
            return Observation(SandboxStatus.DELETED)

    Worker(store, Missing(), Settings()).run_once()
    assert store.done == [Observation(SandboxStatus.STOPPED)]
