"""Bounded read-only public-route recovery barrier after an API rollout."""

import json
import math
import subprocess
import time
from collections.abc import Callable
from typing import Any
from urllib.error import URLError


class RecoveryError(AssertionError):
    """Recovery failed; diagnostics intentionally exclude bodies and credentials."""


def ready_api_uid(pods: dict[str, Any]) -> str | None:
    items = pods.get("items")
    if not isinstance(items, list) or any(not isinstance(pod, dict) for pod in items):
        raise RecoveryError("Invalid API Pod observation")
    # Include terminating old Pods: a Ready replacement alone is insufficient.
    if len(items) != 1:
        return None
    pod = items[0]
    metadata = pod.get("metadata", {})
    status = pod.get("status", {})
    uid = metadata.get("uid")
    if (
        not isinstance(uid, str)
        or not uid
        or metadata.get("deletionTimestamp") is not None
        or status.get("phase") != "Running"
        or not any(
            item.get("type") == "Ready" and item.get("status") == "True"
            for item in status.get("conditions", [])
        )
    ):
        return None
    return uid


def wait_for_api_recovery(
    read_pods: Callable[[float], dict[str, Any]],
    probe: Callable[[float], tuple[int, bytes]],
    *,
    previous_uid: str,
    expected: dict[str, str],
    timeout_seconds: float = 120,
    stable_seconds: float = 3,
    interval_seconds: float = 0.5,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    """Callbacks receive remaining time; probe must only GET the retained record.

    Never retry a mutation. Wrong records, auth errors and malformed responses fail
    immediately. An old/overlapping/unready Pod or transient routing failure resets
    the entire success window. The same replacement UID must span that window.
    """
    if (
        not previous_uid
        or not expected
        or not all(
            math.isfinite(value) for value in (interval_seconds, stable_seconds, timeout_seconds)
        )
        or not 0 < interval_seconds <= stable_seconds < timeout_seconds
    ):
        raise ValueError("Recovery requires a previous Pod, expected record and bounded timing")
    started = clock()
    deadline = started + timeout_seconds
    stable_uid = None
    stable_since = None
    observations = 0
    transient_failures = 0
    reason = "API Pods have not converged"

    def remaining() -> float:
        value = deadline - clock()
        if value <= 0:
            raise RecoveryError(f"API recovery timed out: {reason}")
        return value

    while True:
        observations += 1
        success = False
        try:
            uid = ready_api_uid(read_pods(min(5, remaining())))
            remaining()
            if uid is not None and uid != previous_uid:
                status, body = probe(min(5, remaining()))
                remaining()
                if status == 200:
                    try:
                        record = json.loads(body)
                    except (ValueError, UnicodeDecodeError):
                        raise RecoveryError("API recovery returned invalid JSON") from None
                    if not isinstance(record, dict) or any(
                        record.get(key) != value for key, value in expected.items()
                    ):
                        raise RecoveryError("API recovery returned a different retained record")
                    if stable_uid != uid or stable_since is None:
                        stable_uid, stable_since = uid, clock()
                    success = True
                    if clock() - stable_since >= stable_seconds:
                        return {
                            "pod_uid": uid,
                            "observations": observations,
                            "transient_failures": transient_failures,
                            "stable_seconds": stable_seconds,
                            "elapsed_seconds": round(clock() - started, 3),
                        }
                    reason = "Public API success window is not stable yet"
                elif status in {502, 503, 504}:
                    transient_failures += 1
                    reason = f"Public API returned transient HTTP {status}"
                else:
                    raise RecoveryError(f"API recovery rejected HTTP {status}")
            else:
                reason = "API Pods have not converged to one Ready replacement"
        except (URLError, TimeoutError, ConnectionError, subprocess.TimeoutExpired):
            transient_failures += 1
            reason = "Public API or Pod observation temporarily unavailable"
        if not success:
            stable_uid, stable_since = None, None
        sleep(min(interval_seconds, remaining()))
