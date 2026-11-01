"""Regression for a GET200 followed by a post-rollout nginx502 in CI."""

import importlib.util
import json
import subprocess
from pathlib import Path
from urllib.error import URLError

import pytest

SOURCE = Path(__file__).resolve().parents[4] / "tests/e2e/api_recovery.py"
SPEC = importlib.util.spec_from_file_location("protohub_api_recovery", SOURCE)
recovery = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(recovery)
EXPECTED = {"id": "retained-id", "name": "Retained app", "owner_email": "owner@example.test"}
BODY = json.dumps(EXPECTED).encode()


class Clock:
    def __init__(self):
        self.now = 0.0

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        assert seconds > 0
        self.now += seconds


def pod(uid="replacement", *, ready=True, terminating=False):
    return {
        "metadata": {"uid": uid, **({"deletionTimestamp": "synthetic"} if terminating else {})},
        "status": {
            "phase": "Running",
            "conditions": [{"type": "Ready", "status": "True" if ready else "False"}],
        },
    }


class Probes:
    def __init__(self, clock, frames=None, responses=None):
        self.clock = clock
        self.frames = frames or [[pod()]]
        self.responses = responses or [(200, BODY)]
        self.pod_calls = []
        self.http_calls = []

    def read_pods(self, timeout):
        self.pod_calls.append(timeout)
        frame = self.frames[min(len(self.pod_calls) - 1, len(self.frames) - 1)]
        return {"items": frame}

    def probe(self, timeout):
        self.http_calls.append(timeout)
        response = self.responses[min(len(self.http_calls) - 1, len(self.responses) - 1)]
        if isinstance(response, Exception):
            raise response
        return response

    def run(self, **kwargs):
        return recovery.wait_for_api_recovery(
            self.read_pods,
            self.probe,
            previous_uid="old",
            expected=EXPECTED,
            timeout_seconds=5,
            stable_seconds=2,
            interval_seconds=0.5,
            clock=self.clock.monotonic,
            sleep=self.clock.sleep,
            **kwargs,
        )


def test_one_success_then_502_resets_entire_stability_window():
    clock = Clock()
    probes = Probes(clock, responses=[(200, BODY), (502, b"nginx unavailable"), (200, BODY)])
    observed = probes.run()
    assert clock.now == 3
    assert observed["transient_failures"] == 1
    assert observed["observations"] == 7
    assert observed["pod_uid"] == "replacement"
    assert observed["stable_seconds"] == 2


def test_old_pod_overlap_and_previous_uid_cannot_start_public_success_window():
    clock = Clock()
    probes = Probes(
        clock,
        frames=[
            [pod("old")],
            [pod("old", terminating=True), pod()],
            [pod()],
        ],
    )
    observed = probes.run()
    assert clock.now == 3
    assert len(probes.pod_calls) == 7 and len(probes.http_calls) == 5
    assert observed["pod_uid"] != "old"


def test_replacement_uid_change_restarts_stability_window():
    clock = Clock()
    probes = Probes(clock, frames=[[pod()], [pod()], [pod("newer")]])
    observed = probes.run()
    assert clock.now == 3
    assert observed["pod_uid"] == "newer"


def test_lost_readiness_resets_same_uid_success_window():
    clock = Clock()
    probes = Probes(clock, frames=[[pod()], [pod(ready=False)], [pod()]])
    probes.run()
    assert clock.now == 3


@pytest.mark.parametrize("status", [502, 503, 504])
def test_transient_public_errors_are_bounded_not_success(status):
    clock = Clock()
    probes = Probes(clock, responses=[(status, b"synthetic-sensitive-body")])
    with pytest.raises(recovery.RecoveryError, match="timed out") as error:
        probes.run()
    assert clock.now == 5 and len(probes.http_calls) == 10
    assert "synthetic-sensitive-body" not in str(error.value)
    assert all(0 < value <= 5 for value in probes.pod_calls + probes.http_calls)
    assert probes.http_calls[-1] == 0.5


@pytest.mark.parametrize("status", [301, 401, 403, 404, 409, 422, 500])
def test_permanent_http_and_auth_errors_fail_immediately_without_retry(status):
    clock = Clock()
    probes = Probes(clock, responses=[(status, b"synthetic-sensitive-body")])
    with pytest.raises(recovery.RecoveryError, match=f"HTTP {status}") as error:
        probes.run()
    assert clock.now == 0 and len(probes.http_calls) == 1
    assert "synthetic-sensitive-body" not in str(error.value)


@pytest.mark.parametrize(
    "body",
    [
        b"broken-json",
        b"[]",
        b"{}",
        b'"text"',
        b"\xff",
        json.dumps({**EXPECTED, "id": "other-id"}).encode(),
        json.dumps({**EXPECTED, "owner_email": "other@example.test"}).encode(),
    ],
)
def test_invalid_or_different_retained_record_is_never_retried(body):
    clock = Clock()
    probes = Probes(clock, responses=[(200, body)])
    with pytest.raises(recovery.RecoveryError):
        probes.run()
    assert clock.now == 0 and len(probes.http_calls) == 1


@pytest.mark.parametrize(
    "failure",
    [
        URLError("synthetic-sensitive-detail"),
        TimeoutError("synthetic-sensitive-detail"),
        ConnectionResetError("synthetic-sensitive-detail"),
        subprocess.TimeoutExpired(["kubectl"], 5),
    ],
)
def test_transport_failure_resets_window_then_can_recover(failure):
    clock = Clock()
    probes = Probes(clock, responses=[(200, BODY), failure, (200, BODY)])
    observed = probes.run()
    assert clock.now == 3 and observed["transient_failures"] == 1


@pytest.mark.parametrize("slow_stage", ["pod", "http"])
def test_probe_crossing_absolute_deadline_cannot_report_success(slow_stage):
    clock = Clock()
    http_calls = []

    def slow_pods(timeout):
        assert 0 < timeout <= 5
        if slow_stage == "pod":
            clock.now += 5.1
        return {"items": [pod()]}

    def slow_http(timeout):
        assert 0 < timeout <= 5
        http_calls.append(timeout)
        clock.now += 5.1
        return 200, BODY

    with pytest.raises(recovery.RecoveryError, match="timed out"):
        recovery.wait_for_api_recovery(
            slow_pods,
            slow_http,
            previous_uid="old",
            expected=EXPECTED,
            timeout_seconds=5,
            stable_seconds=2,
            clock=clock.monotonic,
            sleep=clock.sleep,
        )
    assert clock.now == 5.1
    assert len(http_calls) == (1 if slow_stage == "http" else 0)


@pytest.mark.parametrize("frame", [[], [pod("old")], [pod(ready=False)], [pod(terminating=True)]])
def test_missing_old_unready_or_terminating_pods_never_admit_http(frame):
    clock = Clock()
    probes = Probes(clock, frames=[frame])
    with pytest.raises(recovery.RecoveryError, match="timed out"):
        probes.run()
    assert clock.now == 5 and probes.http_calls == []


def test_observation_failures_are_not_hidden_as_http_retries():
    def broken(timeout):
        raise subprocess.CalledProcessError(1, ["kubectl"])

    with pytest.raises(subprocess.CalledProcessError):
        recovery.wait_for_api_recovery(
            broken,
            lambda timeout: (200, BODY),
            previous_uid="old",
            expected=EXPECTED,
        )


@pytest.mark.parametrize(
    "timing",
    [
        {"timeout_seconds": float("inf")},
        {"stable_seconds": float("nan")},
        {"interval_seconds": 0},
    ],
)
def test_unbounded_or_invalid_timing_is_rejected_before_any_probe(timing):
    calls = []
    with pytest.raises(ValueError):
        recovery.wait_for_api_recovery(
            lambda timeout: calls.append("pod"),
            lambda timeout: calls.append("http"),
            previous_uid="old",
            expected=EXPECTED,
            **timing,
        )
    assert calls == []
