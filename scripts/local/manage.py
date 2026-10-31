#!/usr/bin/env python3
"""Owned localhost development resources only; never installs or changes OS settings."""

from __future__ import annotations

import argparse
import json
import os
import re
import signal
import socket
import string
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
STATE = ROOT / ".harness" / "local"
OWNER_LABEL = "protohub.io/owner"
NAME = re.compile(r"protohub-[a-z0-9][a-z0-9-]{0,42}\Z")


class Blocked(Exception):
    pass


def run(argv: list[str], capture: bool = False) -> str:
    result = subprocess.run(
        argv,
        cwd=ROOT,
        check=True,
        stdin=subprocess.DEVNULL,
        text=True,
        stdout=subprocess.PIPE if capture else None,
    )
    return result.stdout.strip() if capture else ""


def save(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    temporary.chmod(0o600)
    temporary.replace(path)


def owner() -> str:
    path = STATE / "owner.json"
    if not path.exists():
        save(path, {"owner_id": uuid4().hex})
    return json.loads(path.read_text(encoding="utf-8"))["owner_id"]


def config(mode: str | None = None) -> dict:
    active = STATE / "active.json"
    previous = json.loads(active.read_text()) if active.exists() else {}
    mode = mode or os.environ.get("PROTOHUB_MODE", previous.get("mode", "mock"))
    if mode not in {"mock", "real-kind"}:
        raise Blocked("PROTOHUB_MODE must be mock or real-kind")
    key = "PROTOHUB_CLUSTER_NAME" if mode == "real-kind" else "COMPOSE_PROJECT_NAME"
    name = os.environ.get(
        key,
        previous.get("name", "protohub-local")
        if previous.get("mode") == mode
        else "protohub-local",
    )
    if not NAME.fullmatch(name):
        raise Blocked(f"{key} must start with protohub- and contain only lowercase names")
    try:
        reuse = previous.get("mode") == mode and previous.get("name") == name
        console = int(
            os.environ.get(
                "PROTOHUB_CONSOLE_PORT",
                str(previous.get("console_port", 8080)) if reuse else "8080",
            )
        )
        preview = int(
            os.environ.get(
                "PROTOHUB_PREVIEW_PORT",
                str(previous.get("preview_port", 8081)) if reuse else "8081",
            )
        )
        if not (1024 <= console <= 65535 and 1024 <= preview <= 65535 and console != preview):
            raise ValueError
    except ValueError:
        raise Blocked("Console/preview need distinct unprivileged TCP ports") from None
    return {
        "mode": mode,
        "name": name,
        "console_port": console,
        "preview_port": preview,
        "owner_id": owner(),
    }


def record_path(cfg: dict) -> Path:
    return (
        STATE / ("kind" if cfg["mode"] == "real-kind" else "compose") / cfg["name"] / "state.json"
    )


def existing_record(cfg: dict) -> dict | None:
    path = record_path(cfg)
    if not path.exists():
        return None
    record = json.loads(path.read_text(encoding="utf-8"))
    if any(record.get(k) != cfg[k] for k in ("mode", "name", "owner_id")):
        raise Blocked("Local ownership record does not match this checkout")
    return record


def preflight(mode: str, operation: str = "start") -> None:
    if sys.platform != "linux":
        raise Blocked("Run in WSL2/Linux; native Windows is not the supported Docker launcher")
    if re.match(r"^/mnt/[a-zA-Z]/", str(ROOT)):
        raise Blocked("Move the checkout to the WSL Linux filesystem before launching Docker")
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "harness/doctor.py"),
            "--mode",
            "kind" if mode == "real-kind" else "compose",
            "--operation",
            operation,
        ],
        cwd=ROOT,
        check=False,
        stdin=subprocess.DEVNULL,
    )
    if result.returncode:
        raise Blocked("Environment doctor failed; no setup or fallback was attempted")


def free_ports(cfg: dict) -> None:
    for key in (
        ("console_port", "preview_port") if cfg["mode"] == "real-kind" else ("console_port",)
    ):
        with socket.socket() as sock:
            try:
                sock.bind(("127.0.0.1", cfg[key]))
            except OSError:
                raise Blocked(f"127.0.0.1:{cfg[key]} is in use; choose another port") from None


def compose(cfg: dict, *args: str) -> str:
    os.environ["PROTOHUB_OWNER_ID"] = cfg["owner_id"]
    os.environ["PROTOHUB_CONSOLE_PORT"] = str(cfg["console_port"])
    os.environ["PROTOHUB_PREVIEW_PORT"] = str(cfg["preview_port"])
    return run(["docker", "compose", "-p", cfg["name"], "-f", "compose.yaml", *args])


def verify_compose(cfg: dict) -> bool:
    exists = False
    for resource, filter_label in (
        ("container", "com.docker.compose.project"),
        ("volume", "com.docker.compose.project"),
        ("network", "com.docker.compose.project"),
    ):
        command = (
            ["docker", "ps", "-aq"] if resource == "container" else ["docker", resource, "ls", "-q"]
        )
        ids = run([*command, "--filter", f"label={filter_label}={cfg['name']}"], True).splitlines()
        for resource_id in ids:
            exists = True
            value = json.loads(run(["docker", resource, "inspect", resource_id], True))[0]
            labels = (
                value.get("Config", {}).get("Labels", {})
                if resource == "container"
                else value.get("Labels", {})
            )
            if labels.get(OWNER_LABEL) != cfg["owner_id"]:
                raise Blocked(
                    "An existing Compose resource has another owner; refusing to modify it"
                )
    return exists


def kube(cfg: dict, *args: str, capture: bool = False) -> str:
    return run(["kubectl", "--context", "kind-" + cfg["name"], *args], capture)


def wait_for_drain(
    cfg: dict,
    namespace: str,
    selector: str,
    *,
    worker: bool = False,
    timeout_seconds: float = 90,
) -> None:
    """Observe scaled controllers and Pod absence before the next shutdown step."""
    stage = "worker" if worker else "sample"
    deadline = time.monotonic() + timeout_seconds
    print(f"Waiting for {stage} Pods to stop...", flush=True)

    def read(*args: str) -> dict:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError(f"Timed out draining {stage} Pods; shutdown is incomplete")
        request_timeout = f"{max(0.001, min(5, remaining)):.3f}s"
        value = json.loads(
            kube(
                cfg,
                f"--request-timeout={request_timeout}",
                "-n",
                namespace,
                *args,
                "-o",
                "json",
                capture=True,
            )
        )
        if not isinstance(value, dict):
            raise ValueError("Invalid Kubernetes drain response")
        return value

    while True:
        deployments = (
            [read("get", "deployment", "worker")]
            if worker
            else read("get", "deployments", "-l", selector).get("items")
        )
        pods = read("get", "pods", "-l", selector).get("items")
        if not isinstance(deployments, list) or not isinstance(pods, list):
            raise ValueError("Invalid Kubernetes drain resource list")
        controllers_stopped = True
        for deployment in deployments:
            generation = deployment["metadata"]["generation"]
            if deployment["spec"].get("replicas", 1) != 0:
                raise ValueError(f"The {stage} replica target changed during shutdown")
            status = deployment.get("status") or {}
            controllers_stopped = controllers_stopped and (
                status.get("observedGeneration", 0) >= generation
                and (status.get("replicas") or 0) == 0
            )
        if controllers_stopped and not pods:
            return
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError(f"Timed out draining {stage} Pods; shutdown is incomplete")
        time.sleep(min(0.5, remaining))


def wait_for_worker_drain(cfg: dict, timeout_seconds: float = 90) -> None:
    wait_for_drain(
        cfg, "protohub-system", "app=protohub-worker", worker=True, timeout_seconds=timeout_seconds
    )


def wait_for_sample_drain(cfg: dict, timeout_seconds: float = 90) -> None:
    wait_for_drain(
        cfg,
        "protohub-samples",
        "app.kubernetes.io/managed-by=protohub",
        timeout_seconds=timeout_seconds,
    )


def verify_kind(cfg: dict, allow_incomplete: bool = False) -> bool:
    clusters = run(["kind", "get", "clusters"], True).splitlines()
    if cfg["name"] not in clusters:
        return False
    record = existing_record(cfg)
    if record is None or "node_id" not in record:
        raise Blocked(
            "Existing kind cluster has no matching ownership record; refusing to adopt it"
        )
    inspected = json.loads(run(["docker", "inspect", cfg["name"] + "-control-plane"], True))[0]
    if (
        inspected["Id"] != record["node_id"]
        or inspected.get("Config", {}).get("Labels", {}).get("io.x-k8s.kind.cluster") != cfg["name"]
    ):
        raise Blocked("kind control-plane identity differs from the created resource")
    if any(record.get(k) != cfg[k] for k in ("console_port", "preview_port")):
        raise Blocked(
            "Existing kind port mappings differ; retain configured ports or explicitly reset"
        )
    try:
        namespaces = json.loads(kube(cfg, "get", "namespace", "-o", "json", capture=True))["items"]
    except subprocess.CalledProcessError:
        if allow_incomplete and record.get("bootstrap_state") == "incomplete":
            return True
        raise
    for namespace in namespaces:
        if (
            namespace["metadata"]["name"] in {"protohub-system", "protohub-samples"}
            and namespace["metadata"].get("labels", {}).get(OWNER_LABEL) != cfg["owner_id"]
        ):
            raise Blocked("ProtoHub namespace belongs to another owner")
    return True


def render(cfg: dict, source: str, target: str, tag: str = "") -> Path:
    values = {
        "OWNER_ID": cfg["owner_id"],
        "CONSOLE_PORT": cfg["console_port"],
        "PREVIEW_PORT": cfg["preview_port"],
        "BUILD_TAG": tag,
    }
    output = record_path(cfg).parent / target
    output.parent.mkdir(parents=True, exist_ok=True)
    text = string.Template((ROOT / source).read_text(encoding="utf-8")).substitute(values)
    output.write_text(text, encoding="utf-8")
    return output


def parse_rfc3339(value: str) -> datetime:
    """Parse aware timestamps, including Docker nanoseconds, on Python 3.10."""
    match = re.fullmatch(
        r"(?P<date>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})"
        r"(?:\.(?P<fraction>\d+))?(?P<offset>Z|[+-]\d{2}:\d{2})",
        value,
    )
    if match is None:
        raise ValueError("Expected a timezone-aware RFC3339 timestamp")
    fraction = match.group("fraction")
    normalized = match.group("date")
    if fraction is not None:
        normalized += "." + (fraction + "000000")[:6]
    offset = match.group("offset")
    return datetime.fromisoformat(normalized + ("+00:00" if offset == "Z" else offset))


def capture_created_node(cfg: dict, receipt: str) -> bool:
    """Record a fresh node from this confirmed-absent bootstrap, including on timeout."""
    record = existing_record(cfg)
    if record is None or record.get("creation_receipt") != receipt:
        raise Blocked("Bootstrap receipt changed; refusing to claim a node")
    try:
        node = json.loads(run(["docker", "inspect", cfg["name"] + "-control-plane"], True))[0]
    except subprocess.CalledProcessError:
        return False
    labels = node.get("Config", {}).get("Labels", {})
    created = parse_rfc3339(node["Created"])
    started = parse_rfc3339(record["creation_started_at"])
    if (
        labels.get("io.x-k8s.kind.cluster") != cfg["name"]
        or labels.get("io.x-k8s.kind.role") != "control-plane"
        or created < started
    ):
        raise Blocked("Bootstrap node is not a fresh member of the requested cluster")
    save(record_path(cfg), {**record, "node_id": node["Id"], "bootstrap_state": "incomplete"})
    return True


def create_kind(cfg: dict, cluster: Path) -> None:
    # kind discovery can miss an unlabeled same-name container; check the exact name too.
    existing = run(
        ["docker", "ps", "-aq", "--filter", f"name=^/{cfg['name']}-control-plane$"], True
    )
    if existing:
        raise Blocked("A container with the requested node name already exists")
    receipt = uuid4().hex
    save(
        record_path(cfg),
        {
            **cfg,
            "creation_receipt": receipt,
            "creation_started_at": datetime.now(timezone.utc).isoformat(),
        },
    )
    try:
        run(
            [
                "kind",
                "create",
                "cluster",
                "--name",
                cfg["name"],
                "--config",
                str(cluster),
                "--wait",
                "180s",
                "--retain",
            ]
        )
    except (subprocess.CalledProcessError, KeyboardInterrupt):
        # Bootstrap may have created our node before kubeadm timed out. Save its fresh
        # identity under this attempt's receipt so exact owned cleanup remains possible.
        capture_created_node(cfg, receipt)
        raise
    if not capture_created_node(cfg, receipt):
        raise Blocked("kind returned without a verifiable node identity")


def up(cfg: dict) -> None:
    preflight(cfg["mode"])
    if cfg["mode"] == "mock":
        exists = verify_compose(cfg)
        if not exists:
            free_ports(cfg)
        save(record_path(cfg), cfg)
        compose(cfg, "up", "--build", "-d", "--wait", "--wait-timeout", "180")
    else:
        exists = verify_kind(cfg)
        if not exists:
            free_ports(cfg)
            cluster = render(cfg, "infra/kind/cluster.yaml.in", "cluster.yaml")
            create_kind(cfg, cluster)
        revision = run(["git", "rev-parse", "HEAD"], True)
        tag = revision[:12] + "-" + str(int(time.time()))
        for image, dockerfile in (
            ("server", "infra/docker/server.Dockerfile"),
            ("web", "infra/docker/web.Dockerfile"),
            ("hello-web", "examples/hello-web/Dockerfile"),
        ):
            build_args = [
                "docker",
                "build",
                "-f",
                dockerfile,
                "-t",
                f"protohub/{image}:{tag}",
                "--label",
                "org.opencontainers.image.revision=" + revision,
            ]
            if image == "server":
                build_args.extend(["--target", "runtime"])
            run([*build_args, "."])
        run(
            [
                "kind",
                "load",
                "docker-image",
                "--name",
                cfg["name"],
                *[f"protohub/{image}:{tag}" for image in ("server", "web", "hello-web")],
            ]
        )
        namespace_file = render(cfg, "infra/kubernetes/namespaces.yaml.in", "namespaces.yaml")
        kube(cfg, "apply", "-f", str(namespace_file))
        kube(cfg, "apply", "-f", "infra/kubernetes/rbac.yaml")
        stack = render(cfg, "infra/kubernetes/stack.yaml.in", "stack.yaml", tag)
        kube(cfg, "apply", "-f", str(stack))
        for deployment in ("db", "api", "worker", "preview", "web"):
            kube(
                cfg,
                "-n",
                "protohub-system",
                "rollout",
                "status",
                "deployment/" + deployment,
                "--timeout=300s",
            )
        record = existing_record(cfg) or cfg
        save(
            record_path(cfg),
            {**record, "build_tag": tag, "git_sha": revision, "bootstrap_state": "ready"},
        )
    if os.environ.get("PROTOHUB_NO_ACTIVATE") != "1":
        save(STATE / "active.json", cfg)
    print(f"Console: http://localhost:{cfg['console_port']} ({cfg['mode']})")
    if cfg["mode"] == "real-kind":
        print(f"Preview: http://localhost:{cfg['preview_port']}/apps/<sandbox UUID>/")
    else:
        print("Mock runtime — no sample application or preview is started")


def down(cfg: dict) -> None:
    preflight(cfg["mode"], operation="cleanup")
    if cfg["mode"] == "mock":
        if verify_compose(cfg):
            compose(cfg, "down", "--remove-orphans")
    elif verify_kind(cfg):
        kube(cfg, "-n", "protohub-system", "scale", "deployment/worker", "--replicas=0")
        wait_for_worker_drain(cfg)
        kube(
            cfg,
            "-n",
            "protohub-samples",
            "scale",
            "deployment",
            "-l",
            "app.kubernetes.io/managed-by=protohub",
            "--replicas=0",
        )
        wait_for_sample_drain(cfg)
        kube(
            cfg,
            "-n",
            "protohub-system",
            "scale",
            "deployment",
            "-l",
            "app.kubernetes.io/managed-by=protohub",
            "--replicas=0",
        )
    print("Stopped owned workloads; database volume and kind cluster retained")


def reset(cfg: dict) -> None:
    preflight(cfg["mode"], operation="cleanup")
    print(f"Destructive reset target: {cfg['mode']} {cfg['name']} (includes its local database)")
    if os.environ.get("PROTOHUB_RESET_CONFIRM") != cfg["name"]:
        raise Blocked("Set PROTOHUB_RESET_CONFIRM to that exact name to authorize reset")
    if cfg["mode"] == "mock":
        if verify_compose(cfg):
            compose(cfg, "down", "--volumes", "--remove-orphans")
    elif verify_kind(cfg, allow_incomplete=True):
        run(["kind", "delete", "cluster", "--name", cfg["name"]])
    # Keep record as historical evidence; it cannot authorize a different new node identity.
    record = existing_record(cfg) or cfg
    save(record_path(cfg), {**record, "reset_at": int(time.time())})


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("up-mock", "up-real", "down", "logs", "reset-local"))
    args = parser.parse_args()

    def interrupted(_signum, _frame):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, interrupted)
    try:
        cfg = config({"up-mock": "mock", "up-real": "real-kind"}.get(args.action))
        if args.action.startswith("up-"):
            up(cfg)
        elif args.action == "down":
            down(cfg)
        elif args.action == "reset-local":
            reset(cfg)
        else:
            preflight(cfg["mode"], operation="cleanup")
            if cfg["mode"] == "mock":
                if verify_compose(cfg):
                    compose(cfg, "logs", "--tail", "100")
            elif verify_kind(cfg):
                kube(
                    cfg,
                    "-n",
                    "protohub-system",
                    "logs",
                    "-l",
                    "app.kubernetes.io/managed-by=protohub",
                    "--all-containers=true",
                    "--tail=100",
                    "--max-log-requests=10",
                )
        return 0
    except Blocked as exc:
        print(f"BLOCKED: {exc}", file=sys.stderr)
        return 78
    except KeyboardInterrupt:
        print("FAIL local operation interrupted; owned resource identity retained", file=sys.stderr)
        return 130
    except (subprocess.CalledProcessError, OSError, ValueError) as exc:
        print(
            f"FAIL local {args.action}: {type(exc).__name__}; inspect the command output",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
