"""Shutdown sequencing uses observed controller and Pod state, never scale acceptance."""

import importlib.util
import json
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

SOURCE = Path(__file__).resolve().parents[4] / "scripts/local/manage.py"
SPEC = importlib.util.spec_from_file_location("protohub_local_drain", SOURCE)
local = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(local)


class Clock:
    def __init__(self):
        self.now = 0.0

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


def pod():
    return {"metadata": {"deletionTimestamp": "2026-10-31T00:00:00Z"}}


class Cluster:
    def __init__(
        self, worker_frames=None, sample_never_stops=False, samples=None, sample_pod_frames=None
    ):
        self.worker_frames = worker_frames or [
            (6, 0, []),  # Controller has not observed the scale, despite an empty Pod list.
            (7, 1, [pod()]),
            (7, 0, []),
        ]
        self.sample_never_stops = sample_never_stops
        self.sample_pod_frames = (
            sample_pod_frames if sample_pod_frames is not None else [[pod()], []]
        )
        self.worker_reads = 0
        self.sample_reads = 0
        self.worker_drained = False
        self.sample_drained = False
        self.samples = {"first"} if samples is None else set(samples)
        self.scaled_samples = set()
        self.events = []
        self.request_timeouts = []
        self.process_timeouts = []

    def __call__(self, cfg, *args, capture=False, timeout_seconds=None, capture_stderr=False):
        namespace = args[args.index("-n") + 1]
        if "scale" in args:
            assert not capture
            if "deployment/worker" in args:
                self.events.append("worker-scale")
            elif namespace == "protohub-samples":
                assert self.worker_drained, "sample scale overtook a live worker"
                if not self.samples:
                    raise subprocess.CalledProcessError(
                        1, ["kubectl", *args], stderr="no objects passed to scale"
                    )
                self.scaled_samples = self.samples.copy()
                self.events.append("sample-scale")
            else:
                assert self.worker_drained and self.sample_drained
                self.events.append("control-scale")
            return ""
        assert capture and "get" in args
        self.process_timeouts.append(timeout_seconds)
        timeout = next(value for value in args if value.startswith("--request-timeout="))
        self.request_timeouts.append(float(timeout.split("=")[1][:-1]))
        resource = args[args.index("get") + 1]
        if namespace == "protohub-system":
            frame = self.worker_frames[min(self.worker_reads, len(self.worker_frames) - 1)]
            observed, replicas, pods = frame
            if resource == "deployment":
                return json.dumps(
                    {
                        "metadata": {"generation": 7},
                        "spec": {"replicas": 0},
                        "status": {"observedGeneration": observed, "replicas": replicas},
                    }
                )
            assert args[args.index("-l") + 1] == "app=protohub-worker"
            if replicas:
                # Simulate the worker's previously accepted create finishing during termination.
                self.samples.add("late")
                self.events.append("late-sample-created")
            if observed == 7 and not replicas and not pods:
                self.worker_drained = True
                self.events.append("worker-drained")
            self.worker_reads += 1
            return json.dumps({"items": pods})
        assert namespace == "protohub-samples"
        assert args[args.index("-l") + 1] == "app.kubernetes.io/managed-by=protohub"
        if resource == "deployments":
            return json.dumps(
                {
                    "items": [
                        {
                            "metadata": {"generation": 4},
                            "spec": {"replicas": 0 if sample in self.scaled_samples else 1},
                            "status": {"observedGeneration": 4},
                        }
                        for sample in self.samples
                    ]
                }
            )
        self.sample_reads += 1
        remaining = (
            [pod()]
            if self.sample_never_stops
            else self.sample_pod_frames[min(self.sample_reads - 1, len(self.sample_pod_frames) - 1)]
        )
        if not remaining:
            self.sample_drained = True
            self.events.append("samples-drained")
        return json.dumps({"items": remaining})


@pytest.fixture
def cfg(monkeypatch, tmp_path):
    monkeypatch.setattr(local, "STATE", tmp_path / "local")
    monkeypatch.setattr(local, "preflight", lambda *args, **kwargs: None)
    monkeypatch.setattr(local, "verify_kind", lambda _: True)
    monkeypatch.setattr(local, "time", Clock())
    return {
        "mode": "real-kind",
        "name": "protohub-test",
        "owner_id": "synthetic-owner",
        "console_port": 18080,
        "preview_port": 18081,
    }


def test_down_drains_worker_before_stopping_late_sample_and_is_repeatable(cfg, monkeypatch, capsys):
    cluster = Cluster()
    monkeypatch.setattr(local, "kube", cluster)
    local.down(cfg)
    assert cluster.scaled_samples == {"first", "late"}
    assert cluster.worker_reads == 3
    assert cluster.events.index("late-sample-created") < cluster.events.index("worker-drained")
    assert cluster.events.index("worker-drained") < cluster.events.index("sample-scale")
    assert cluster.events.index("samples-drained") < cluster.events.index("control-scale")
    assert all(0 < value <= 5 for value in cluster.request_timeouts)
    assert all(0 < value <= 90 for value in cluster.process_timeouts)
    assert "Stopped owned workloads" in capsys.readouterr().out
    local.down(cfg)
    assert cluster.events.count("control-scale") == 2


def test_empty_sample_namespace_down_is_successful_and_repeatable(cfg, monkeypatch, capsys):
    cluster = Cluster(worker_frames=[(7, 0, [])], samples=set(), sample_pod_frames=[[]])
    monkeypatch.setattr(local, "kube", cluster)
    local.down(cfg)
    local.down(cfg)
    # The fake rejects empty scale exactly as kubectl does; production must not call it.
    assert "sample-scale" not in cluster.events
    assert cluster.events.count("worker-scale") == 2
    assert cluster.events.count("control-scale") == 2
    assert cluster.sample_reads == 2
    assert capsys.readouterr().out.count("Stopped owned workloads") == 2


def test_empty_deployment_list_still_waits_for_orphan_terminating_pods(cfg, monkeypatch):
    cluster = Cluster(worker_frames=[(7, 0, [])], samples=set(), sample_pod_frames=[[pod()], []])
    monkeypatch.setattr(local, "kube", cluster)
    local.down(cfg)
    assert "sample-scale" not in cluster.events
    assert cluster.sample_reads == 2
    assert cluster.events.index("samples-drained") < cluster.events.index("control-scale")


def test_empty_deployment_list_with_stuck_orphan_does_not_report_success(cfg, monkeypatch, capsys):
    cluster = Cluster(worker_frames=[(7, 0, [])], samples=set(), sample_never_stops=True)
    monkeypatch.setattr(local, "kube", cluster)
    wait = local.wait_for_sample_drain
    monkeypatch.setattr(local, "wait_for_sample_drain", lambda cfg: wait(cfg, timeout_seconds=1))
    with pytest.raises(TimeoutError, match="sample"):
        local.down(cfg)
    assert "sample-scale" not in cluster.events and "control-scale" not in cluster.events
    assert "Stopped owned workloads" not in capsys.readouterr().out


@pytest.mark.parametrize(
    "message",
    [
        "error: no objects passed to scale\n",
        'Error from server (NotFound): deployments.apps "first" not found\n',
        'Error from server (NotFound): deployments/scale.apps "first" not found\n',
    ],
)
def test_scale_disappearance_is_reobserved_and_pods_still_drained(
    cfg, monkeypatch, capsys, message
):
    cluster = Cluster(worker_frames=[(7, 0, [])], sample_pod_frames=[[pod()], []])
    selections = []

    def observe(cfg, *args, **kwargs):
        if "protohub-samples" in args and "deployments" in args:
            selections.append(cluster.samples.copy())
        if "protohub-samples" in args and "scale" in args:
            assert kwargs["capture_stderr"] is True and kwargs["timeout_seconds"] == 10
            cluster.samples.clear()  # A previously accepted foreground delete finishes now.
            raise subprocess.CalledProcessError(1, ["kubectl", *args], stderr=message)
        return cluster(cfg, *args, **kwargs)

    monkeypatch.setattr(local, "kube", observe)
    local.down(cfg)
    assert selections[:2] == [{"first"}, set()]
    assert cluster.sample_reads == 2
    assert cluster.events.index("samples-drained") < cluster.events.index("control-scale")
    assert "Stopped owned workloads" in capsys.readouterr().out


def test_missing_scale_target_still_present_is_not_ignored(cfg, monkeypatch, capsys):
    cluster = Cluster(worker_frames=[(7, 0, [])])
    selections = []

    def observe(cfg, *args, **kwargs):
        if "protohub-samples" in args and "deployments" in args:
            selections.append(cluster.samples.copy())
        if "protohub-samples" in args and "scale" in args:
            raise subprocess.CalledProcessError(
                1, ["kubectl", *args], stderr="error: no objects passed to scale\n"
            )
        return cluster(cfg, *args, **kwargs)

    monkeypatch.setattr(local, "kube", observe)
    with pytest.raises(subprocess.CalledProcessError):
        local.down(cfg)
    assert selections == [{"first"}, {"first"}]
    assert "control-scale" not in cluster.events
    assert "Stopped owned workloads" not in capsys.readouterr().out


@pytest.mark.parametrize(
    "message",
    [
        'Error from server (Forbidden): deployments.apps "first" is forbidden\n',
        "error: the server is currently unable to handle the request\n",
        "error: no objects passed to scale\nError from server (Forbidden): access denied\n",
        'Error from server (NotFound): namespaces "protohub-samples" not found\n',
    ],
)
def test_other_scale_errors_fail_even_if_deployments_disappeared(cfg, monkeypatch, capsys, message):
    cluster = Cluster(worker_frames=[(7, 0, [])])
    selections = []

    def observe(cfg, *args, **kwargs):
        if "protohub-samples" in args and "deployments" in args:
            selections.append(cluster.samples.copy())
        if "protohub-samples" in args and "scale" in args:
            cluster.samples.clear()
            raise subprocess.CalledProcessError(1, ["kubectl", *args], stderr=message)
        return cluster(cfg, *args, **kwargs)

    monkeypatch.setattr(local, "kube", observe)
    with pytest.raises(subprocess.CalledProcessError):
        local.down(cfg)
    assert selections == [{"first"}]  # Other errors never trigger the recovery re-observation.
    assert "control-scale" not in cluster.events
    assert "Stopped owned workloads" not in capsys.readouterr().out


def test_disappeared_scale_target_with_live_orphan_still_times_out(cfg, monkeypatch, capsys):
    cluster = Cluster(worker_frames=[(7, 0, [])], sample_never_stops=True)

    def observe(cfg, *args, **kwargs):
        if "protohub-samples" in args and "scale" in args:
            cluster.samples.clear()
            raise subprocess.CalledProcessError(
                1, ["kubectl", *args], stderr="error: no objects passed to scale\n"
            )
        return cluster(cfg, *args, **kwargs)

    monkeypatch.setattr(local, "kube", observe)
    wait = local.wait_for_sample_drain
    monkeypatch.setattr(local, "wait_for_sample_drain", lambda cfg: wait(cfg, timeout_seconds=1))
    with pytest.raises(TimeoutError, match="sample"):
        local.down(cfg)
    assert "control-scale" not in cluster.events
    assert "Stopped owned workloads" not in capsys.readouterr().out


def test_scale_timeout_is_not_recovered_even_when_target_disappeared(cfg, monkeypatch, capsys):
    cluster = Cluster(worker_frames=[(7, 0, [])])
    selections = []

    def observe(cfg, *args, **kwargs):
        if "protohub-samples" in args and "deployments" in args:
            selections.append(cluster.samples.copy())
        if "protohub-samples" in args and "scale" in args:
            cluster.samples.clear()
            raise subprocess.TimeoutExpired(["kubectl", *args], 10)
        return cluster(cfg, *args, **kwargs)

    monkeypatch.setattr(local, "kube", observe)
    monkeypatch.setattr(local, "config", lambda _: cfg)
    monkeypatch.setattr(local.sys, "argv", ["manage.py", "down"])
    monkeypatch.setattr(local, "signal", SimpleNamespace(SIGTERM=15, signal=lambda *args: None))
    assert local.main() == 1
    assert selections == [{"first"}]
    assert "control-scale" not in cluster.events
    assert "Stopped owned workloads" not in capsys.readouterr().out


@pytest.mark.parametrize("response", ["invalid JSON", "[]", '{"items":{}}', '{"items":[null]}'])
def test_sample_selection_malformed_response_is_failure(cfg, monkeypatch, capsys, response):
    cluster = Cluster(worker_frames=[(7, 0, [])], samples=set(), sample_pod_frames=[[]])

    def observe(cfg, *args, **kwargs):
        if "protohub-samples" in args and "deployments" in args:
            return response
        return cluster(cfg, *args, **kwargs)

    monkeypatch.setattr(local, "kube", observe)
    with pytest.raises(ValueError):
        local.down(cfg)
    assert "sample-scale" not in cluster.events and "control-scale" not in cluster.events
    assert "Stopped owned workloads" not in capsys.readouterr().out


@pytest.mark.parametrize(
    "error",
    [
        OSError("synthetic API outage"),
        subprocess.CalledProcessError(1, ["kubectl", "get", "deployments"]),
        subprocess.TimeoutExpired(["kubectl", "get", "deployments"], 10),
    ],
)
def test_sample_selection_api_errors_have_nonzero_cli_exit(cfg, monkeypatch, capsys, error):
    cluster = Cluster(worker_frames=[(7, 0, [])], samples=set(), sample_pod_frames=[[]])

    def observe(cfg, *args, **kwargs):
        if "protohub-samples" in args and "deployments" in args:
            raise error
        return cluster(cfg, *args, **kwargs)

    monkeypatch.setattr(local, "kube", observe)
    monkeypatch.setattr(local, "config", lambda _: cfg)
    monkeypatch.setattr(local.sys, "argv", ["manage.py", "down"])
    monkeypatch.setattr(local, "signal", SimpleNamespace(SIGTERM=15, signal=lambda *args: None))
    assert local.main() == 1
    assert "sample-scale" not in cluster.events and "control-scale" not in cluster.events
    assert "Stopped owned workloads" not in capsys.readouterr().out


def test_worker_timeout_prevents_sample_and_control_shutdown(cfg, monkeypatch, capsys):
    cluster = Cluster(worker_frames=[(7, 1, [pod()])])
    monkeypatch.setattr(local, "kube", cluster)
    wait = local.wait_for_worker_drain
    monkeypatch.setattr(local, "wait_for_worker_drain", lambda cfg: wait(cfg, timeout_seconds=1))
    with pytest.raises(TimeoutError, match="worker"):
        local.down(cfg)
    assert "sample-scale" not in cluster.events and "control-scale" not in cluster.events
    assert "Stopped owned workloads" not in capsys.readouterr().out


def test_sample_timeout_has_nonzero_cli_exit_and_keeps_control_stack(cfg, monkeypatch, capsys):
    cluster = Cluster(worker_frames=[(7, 0, [])], sample_never_stops=True)
    monkeypatch.setattr(local, "kube", cluster)
    wait = local.wait_for_sample_drain
    monkeypatch.setattr(local, "wait_for_sample_drain", lambda cfg: wait(cfg, timeout_seconds=1))
    monkeypatch.setattr(local, "config", lambda _: cfg)
    monkeypatch.setattr(local.sys, "argv", ["manage.py", "down"])
    monkeypatch.setattr(local, "signal", SimpleNamespace(SIGTERM=15, signal=lambda *args: None))
    assert local.main() == 1
    assert "sample-scale" in cluster.events and "control-scale" not in cluster.events
    assert "Stopped owned workloads" not in capsys.readouterr().out


def test_drain_api_failure_does_not_continue_shutdown(cfg, monkeypatch, capsys):
    cluster = Cluster(worker_frames=[(7, 0, [])])

    def unavailable(cfg, *args, **kwargs):
        if "get" in args:
            raise OSError("synthetic API outage")
        return cluster(cfg, *args, **kwargs)

    monkeypatch.setattr(local, "kube", unavailable)
    with pytest.raises(OSError):
        local.down(cfg)
    assert cluster.events == ["worker-scale"]
    assert "Stopped owned workloads" not in capsys.readouterr().out


def test_drain_rejects_malformed_resource_lists(cfg, monkeypatch):
    monkeypatch.setattr(local, "kube", lambda *args, **kwargs: "{}")
    with pytest.raises(ValueError, match="resource list"):
        local.wait_for_sample_drain(cfg, timeout_seconds=1)


def test_drain_rejects_a_concurrent_worker_restart(cfg, monkeypatch):
    def changed_target(_cfg, *args, **kwargs):
        if "deployment" in args:
            return json.dumps(
                {
                    "metadata": {"generation": 8},
                    "spec": {"replicas": 1},
                    "status": {"observedGeneration": 8, "replicas": 0},
                }
            )
        return json.dumps({"items": []})

    monkeypatch.setattr(local, "kube", changed_target)
    with pytest.raises(ValueError, match="replica target changed"):
        local.wait_for_worker_drain(cfg, timeout_seconds=1)


def test_sample_drain_waits_for_controller_even_when_no_pods_exist(cfg, monkeypatch):
    polls = []

    def pending_controller(_cfg, *args, **kwargs):
        if "deployments" in args:
            polls.append("controller")
            return json.dumps(
                {
                    "items": [
                        {
                            "metadata": {"generation": 4},
                            "spec": {"replicas": 0},
                            "status": {"observedGeneration": 3, "replicas": 0},
                        }
                    ]
                }
            )
        return json.dumps({"items": []})

    monkeypatch.setattr(local, "kube", pending_controller)
    with pytest.raises(TimeoutError, match="sample"):
        local.wait_for_sample_drain(cfg, timeout_seconds=1)
    assert len(polls) == 2


def test_real_build_selects_server_runtime_stage_only(cfg, monkeypatch):
    calls = []
    monkeypatch.setattr(
        local,
        "worklogs_dir",
        lambda root: pytest.fail("unit build must not resolve checkout work records"),
    )
    monkeypatch.setattr(local, "configure_llm_secret", lambda cfg: None)
    monkeypatch.setattr(local, "time", SimpleNamespace(time=lambda: 1))
    monkeypatch.setattr(local, "existing_record", lambda _: cfg.copy())
    monkeypatch.setattr(local, "save", lambda *args: None)
    monkeypatch.setattr(local, "render", lambda *args: Path("/synthetic/rendered.yaml"))
    monkeypatch.setattr(local, "kube", lambda *args, **kwargs: "")

    def execute(argv, capture=False):
        calls.append(argv)
        return "4edf55d4c943e4378534399191fae04046a58091" if argv[0] == "git" else ""

    monkeypatch.setattr(local, "run", execute)
    local.up(cfg)
    builds = [argv for argv in calls if argv[:2] == ["docker", "build"]]
    assert len(builds) == 3
    server = next(argv for argv in builds if "infra/docker/server.Dockerfile" in argv)
    assert server[server.index("--target") + 1] == "runtime"
    assert all("--target" not in argv for argv in builds if argv is not server)
    assert all(argv[-1] == "." for argv in builds)


def test_kube_forwards_optional_timeout_to_subprocess(cfg, monkeypatch):
    calls = []

    def execute(argv, **kwargs):
        calls.append((argv, kwargs))
        return subprocess.CompletedProcess(argv, 0, stdout="{}")

    monkeypatch.setattr(local.subprocess, "run", execute)
    assert local.kube(cfg, "get", "pods", capture=True, timeout_seconds=1.25) == "{}"
    assert calls[-1][1]["timeout"] == 1.25
    assert calls[-1][0][:3] == ["kubectl", "--context", "kind-protohub-test"]
    local.kube(cfg, "get", "pods", capture=True)
    assert calls[-1][1]["timeout"] is None


@pytest.mark.parametrize(
    "failure",
    [
        subprocess.CalledProcessError(1, ["kubectl"], stderr="error: no objects passed to scale\n"),
        subprocess.TimeoutExpired(["kubectl"], 10, stderr=b"partial timeout diagnostic\n"),
    ],
)
def test_opt_in_stderr_capture_preserves_error_output(cfg, monkeypatch, capsys, failure):
    calls = []

    def execute(argv, **kwargs):
        calls.append(kwargs)
        raise failure

    monkeypatch.setattr(local.subprocess, "run", execute)
    with pytest.raises(type(failure)) as caught:
        local.kube(cfg, "scale", "deployment", capture_stderr=True, timeout_seconds=10)
    assert caught.value is failure
    assert calls[0]["stderr"] == subprocess.PIPE
    expected = failure.stderr.decode() if isinstance(failure.stderr, bytes) else failure.stderr
    assert capsys.readouterr().err == expected


def test_normal_commands_keep_uncaptured_stderr(cfg, monkeypatch):
    calls = []

    def execute(argv, **kwargs):
        calls.append(kwargs)
        return subprocess.CompletedProcess(argv, 0)

    monkeypatch.setattr(local.subprocess, "run", execute)
    local.kube(cfg, "get", "pods")
    assert calls[0]["stderr"] is None and calls[0]["timeout"] is None


def test_stuck_kubectl_process_times_out_and_cli_never_continues_shutdown(cfg, monkeypatch, capsys):
    events = []
    process_timeouts = []
    run_process = subprocess.run
    real_kube = local.kube

    def stuck_kubectl(argv, **kwargs):
        assert argv[0] == "kubectl"
        process_timeouts.append(kwargs["timeout"])
        # This real child models hung discovery/retries independently of HTTP timeouts.
        return run_process([sys.executable, "-c", "import time; time.sleep(30)"], **kwargs)

    def observe(cfg, *args, **kwargs):
        if "scale" in args:
            events.append(args)
            return ""
        return real_kube(cfg, *args, **kwargs)

    monkeypatch.setattr(local.subprocess, "run", stuck_kubectl)
    monkeypatch.setattr(local, "kube", observe)
    wait = local.wait_for_worker_drain
    monkeypatch.setattr(local, "wait_for_worker_drain", lambda cfg: wait(cfg, timeout_seconds=0.1))
    monkeypatch.setattr(local, "config", lambda _: cfg)
    monkeypatch.setattr(local.sys, "argv", ["manage.py", "down"])
    monkeypatch.setattr(local, "signal", SimpleNamespace(SIGTERM=15, signal=lambda *args: None))
    started = time.monotonic()
    assert local.main() == 1
    assert time.monotonic() - started < 3
    assert process_timeouts == [0.1]
    assert len(events) == 1 and "deployment/worker" in events[0]
    assert "Stopped owned workloads" not in capsys.readouterr().out
