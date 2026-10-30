from dataclasses import replace
from uuid import uuid4

import pytest
from sqlalchemy import event, select

from protohub.domain.models import Action, CreateSandbox, Error, OperationStatus, SandboxStatus
from protohub.domain.ports import Observation, RuntimeSpec
from protohub.persistence.jobs import SqlJobStore
from protohub.persistence.models import AuditEventRow, OperationRow


def register(repository, name="Example app"):
    return repository.create(CreateSandbox(name=name, template_id="hello-web", ttl_seconds=60))


def claimed(repository, jobs):
    sandbox = register(repository)
    operation = repository.request(sandbox.id, Action.START)
    claim = jobs.claim("worker-a", lease_seconds=10)
    assert claim is not None and claim.operation_id == operation.id
    return sandbox, operation, claim


def test_claim_complete_duplicate_and_ttl_begin_on_success(repository, jobs, clock):
    sandbox, operation, claim = claimed(repository, jobs)
    assert repository.get(sandbox.id).expires_at is None
    assert jobs.claim("worker-b") is None
    clock.advance(2)
    assert jobs.complete(claim, Observation(SandboxStatus.RUNNING))
    running = repository.get(sandbox.id)
    assert running.status == SandboxStatus.RUNNING
    assert running.expires_at == clock() + __import__("datetime").timedelta(seconds=60)
    assert repository.get_operation(operation.id).status == OperationStatus.SUCCEEDED
    assert repository.request(sandbox.id, Action.START).id == operation.id
    assert not jobs.complete(claim, Observation(SandboxStatus.RUNNING))


def test_new_generation_rejects_all_old_mutations(repository, jobs):
    sandbox, _, claim = claimed(repository, jobs)
    stopped = repository.request(sandbox.id, Action.STOP)
    assert stopped.generation == claim.generation + 1
    error = Error(code="late", message="Old operation")
    assert not jobs.is_current(claim)
    assert not jobs.heartbeat(claim)
    assert not jobs.complete(claim, Observation(SandboxStatus.RUNNING))
    assert not jobs.fail(claim, error)
    assert not jobs.supersede(claim)
    current = repository.get(sandbox.id)
    assert current.status == SandboxStatus.STOPPING
    assert current.preview_url is None
    assert repository.get_operation(claim.operation_id).status == OperationStatus.SUPERSEDED


def test_reclaim_rotates_token_and_rejects_old_holder_same_generation(repository, jobs, clock):
    sandbox, operation, old = claimed(repository, jobs)
    clock.advance(11)
    new = jobs.claim("worker-b", lease_seconds=20)
    assert new is not None
    assert new.operation_id == old.operation_id
    assert new.generation == old.generation
    assert new.lease_token != old.lease_token
    assert new.attempt_count == 2
    assert not jobs.complete(old, Observation(SandboxStatus.RUNNING))
    assert not jobs.heartbeat(old)
    assert not jobs.fail(old, Error(code="late", message="Late failure"))
    assert not jobs.supersede(old)
    assert jobs.complete(new, Observation(SandboxStatus.RUNNING))
    assert repository.get(sandbox.id).status == SandboxStatus.RUNNING
    assert repository.get_operation(operation.id).attempt_count == 2


def test_lease_expiry_rejects_result_before_any_reclaim(repository, jobs, clock):
    _, _, claim = claimed(repository, jobs)
    clock.advance(10)
    assert not jobs.is_current(claim)
    assert not jobs.complete(claim, Observation(SandboxStatus.RUNNING))
    assert not jobs.heartbeat(claim)


def test_owner_token_and_action_are_all_fenced(repository, jobs):
    _, _, claim = claimed(repository, jobs)
    for forged in [
        replace(claim, lease_owner="other"),
        replace(claim, lease_token=uuid4()),
        replace(claim, action=Action.STOP),
        replace(claim, sandbox_id=uuid4()),
    ]:
        assert not jobs.is_current(forged)
        assert not jobs.complete(forged, Observation(SandboxStatus.RUNNING))


def test_heartbeat_extends_current_lease_without_changing_token(repository, jobs, clock):
    _, _, claim = claimed(repository, jobs)
    clock.advance(8)
    assert jobs.heartbeat(claim, lease_seconds=10)
    clock.advance(5)
    assert jobs.is_current(claim)
    assert jobs.claim("worker-b") is None


def test_retry_backoff_is_bounded_three_attempts(repository, jobs, clock):
    sandbox, operation, first = claimed(repository, jobs)
    error = Error(code="temporary_runtime_error", message="Runtime is temporarily unavailable")
    assert jobs.fail(first, error, retryable=True)
    assert jobs.claim("worker-b") is None
    clock.advance(2)
    second = jobs.claim("worker-b")
    assert second is not None and second.attempt_count == 2
    assert jobs.fail(second, error, retryable=True)
    clock.advance(3)
    assert jobs.claim("worker-c") is None
    clock.advance(1)
    third = jobs.claim("worker-c")
    assert third is not None and third.attempt_count == 3
    assert jobs.fail(third, error, retryable=True)
    clock.advance(100)
    assert jobs.claim("worker-d") is None
    assert repository.get(sandbox.id).status == SandboxStatus.FAILED
    assert repository.get_operation(operation.id).status == OperationStatus.FAILED
    retried = repository.request(sandbox.id, Action.START)
    assert retried.generation == operation.generation + 1
    assert jobs.claim("worker-e").attempt_count == 1


def test_expired_third_claim_becomes_failed_instead_of_infinite_retry(repository, jobs, clock):
    sandbox, _, first = claimed(repository, jobs)
    clock.advance(11)
    second = jobs.claim("second", lease_seconds=10)
    clock.advance(11)
    third = jobs.claim("third", lease_seconds=10)
    assert first.attempt_count == 1 and second.attempt_count == 2 and third.attempt_count == 3
    clock.advance(11)
    assert jobs.claim("fourth") is None
    assert repository.get(sandbox.id).error.code == "attempts_exhausted"


def test_nonretryable_partial_failure_is_failed_and_reconcile_cleanup_target(repository, jobs):
    sandbox, _, claim = claimed(repository, jobs)
    assert jobs.fail(claim, Error(code="permission_denied", message="Sample resources denied"))
    assert repository.get(sandbox.id).status == SandboxStatus.FAILED
    target = next(item for item in jobs.reconcile_targets() if item.spec.sandbox_id == sandbox.id)
    assert target.status == SandboxStatus.FAILED
    assert jobs.claim("another") is None


def test_invalid_observation_cannot_complete_start(repository, jobs):
    _, _, claim = claimed(repository, jobs)
    assert not jobs.complete(claim, Observation(SandboxStatus.STARTING))
    assert not jobs.complete(claim, Observation(SandboxStatus.STOPPED))
    assert not jobs.complete(
        claim, Observation(SandboxStatus.RUNNING, error=Error(code="bad", message="Not healthy"))
    )
    assert jobs.is_current(claim)


def test_real_running_requires_url(factory, settings, repository, clock):
    settings.runtime_mode = "real-kind"
    jobs = SqlJobStore(factory, settings, clock)
    sandbox, _, claim = claimed(repository, jobs)
    assert not jobs.complete(claim, Observation(SandboxStatus.RUNNING))
    url = f"http://localhost:8081/apps/{sandbox.id}/"
    assert jobs.complete(claim, Observation(SandboxStatus.RUNNING, url))
    assert repository.get(sandbox.id).preview_url == url


def test_ttl_stop_is_idempotent_persists_management_record(repository, jobs, clock):
    sandbox, _, claim = claimed(repository, jobs)
    assert jobs.complete(claim, Observation(SandboxStatus.RUNNING))
    clock.advance(59)
    assert jobs.enqueue_expired() == 0
    clock.advance(1)
    assert jobs.enqueue_expired() == 1
    assert jobs.enqueue_expired() == 0
    stopped = jobs.claim("ttl-worker")
    assert stopped.action == Action.STOP
    assert jobs.complete(stopped, Observation(SandboxStatus.STOPPED))
    assert repository.get(sandbox.id).status == SandboxStatus.STOPPED
    assert repository.get(sandbox.id).expires_at is None


def test_two_apps_independent_stop_restart_delete(repository, jobs):
    first = register(repository, "First")
    second = register(repository, "Second")
    for sandbox in [first, second]:
        repository.request(sandbox.id, Action.START)
        claim = jobs.claim("worker")
        assert jobs.complete(claim, Observation(SandboxStatus.RUNNING))
    repository.request(first.id, Action.STOP)
    assert jobs.complete(jobs.claim("worker"), Observation(SandboxStatus.STOPPED))
    assert repository.get(second.id).status == SandboxStatus.RUNNING
    repository.request(first.id, Action.START)
    assert jobs.complete(jobs.claim("worker"), Observation(SandboxStatus.RUNNING))
    deleted = repository.request(first.id, Action.DELETE)
    assert jobs.complete(jobs.claim("worker"), Observation(SandboxStatus.DELETED))
    assert repository.request(first.id, Action.DELETE).id == deleted.id
    assert repository.get(first.id).status == SandboxStatus.DELETED
    assert [item.id for item in repository.list()] == [second.id]
    assert repository.get(second.id).status == SandboxStatus.RUNNING


def test_reconcile_clears_unhealthy_preview_preserves_ttl_and_can_recover(
    factory, settings, repository, clock
):
    settings.runtime_mode = "real-kind"
    jobs = SqlJobStore(factory, settings, clock)
    sandbox, _, claim = claimed(repository, jobs)
    url = f"http://localhost:8081/apps/{sandbox.id}/"
    assert jobs.complete(claim, Observation(SandboxStatus.RUNNING, url))
    expires = repository.get(sandbox.id).expires_at
    clock.advance(20)
    assert jobs.reconcile_observation(claim.spec, Observation(SandboxStatus.STOPPED))
    assert repository.get(sandbox.id).status == SandboxStatus.STARTING
    assert repository.get(sandbox.id).preview_url is None
    assert repository.get(sandbox.id).expires_at == expires
    assert any(item.spec == claim.spec for item in jobs.reconcile_targets())
    assert jobs.reconcile_observation(claim.spec, Observation(SandboxStatus.RUNNING, url))
    assert repository.get(sandbox.id).expires_at == expires
    repository.request(sandbox.id, Action.STOP)
    assert not jobs.reconcile_observation(claim.spec, Observation(SandboxStatus.RUNNING, url))


def test_reconcile_cannot_overwrite_active_job_or_failed_sandbox(repository, jobs):
    sandbox, _, claim = claimed(repository, jobs)
    assert not jobs.reconcile_observation(claim.spec, Observation(SandboxStatus.RUNNING))
    assert jobs.fail(claim, Error(code="failed", message="Failed runtime"))
    assert not jobs.reconcile_observation(claim.spec, Observation(SandboxStatus.RUNNING))
    assert not jobs.reconcile_observation(
        RuntimeSpec(uuid4(), 1), Observation(SandboxStatus.RUNNING)
    )
    assert repository.get(sandbox.id).status == SandboxStatus.FAILED


def test_explicit_start_retries_failure_discovered_after_previous_success(repository, jobs):
    sandbox, operation, claim = claimed(repository, jobs)
    assert jobs.complete(claim, Observation(SandboxStatus.RUNNING))
    assert jobs.reconcile_observation(
        claim.spec,
        Observation(
            SandboxStatus.FAILED, error=Error(code="lost_runtime", message="Runtime was lost")
        ),
    )
    retried = repository.request(sandbox.id, Action.START)
    assert retried.id != operation.id
    assert retried.generation == operation.generation + 1


def test_lease_state_is_not_exposed_in_public_operation(repository, jobs, factory):
    _, operation, claim = claimed(repository, jobs)
    exposed = repository.get_operation(operation.id).model_dump()
    assert not {"lease_owner", "lease_token", "lease_expires_at"} & exposed.keys()
    with factory() as session:
        stored = session.scalar(select(OperationRow).where(OperationRow.id == claim.operation_id))
        assert stored.lease_token == claim.lease_token


def test_intent_and_queue_roll_back_together_when_transaction_fails(repository, factory):
    sandbox = register(repository)

    def fail_audit(mapper, connection, target):
        if target.event == "start_requested":
            raise RuntimeError("Synthetic transaction interruption")

    event.listen(AuditEventRow, "before_insert", fail_audit)
    try:
        with pytest.raises(RuntimeError, match="Synthetic transaction"):
            repository.request(sandbox.id, Action.START)
    finally:
        event.remove(AuditEventRow, "before_insert", fail_audit)
    current = repository.get(sandbox.id)
    assert current.status == SandboxStatus.STOPPED
    assert current.generation == 0
    assert current.active_operation_id is None
    with factory() as session:
        assert session.query(OperationRow).count() == 0


@pytest.mark.parametrize("owner,lease", [("", 10), ("x" * 129, 10), ("worker", 0)])
def test_invalid_claim_inputs(jobs, owner, lease):
    with pytest.raises(ValueError):
        jobs.claim(owner, lease)
