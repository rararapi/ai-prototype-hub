"""Independent real-kind fixtures for E2E and security; never falls back to mock."""

import argparse
import json
import os
import signal
import socket
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from uuid import uuid4

root = Path(__file__).resolve().parents[2]
parser = argparse.ArgumentParser()
parser.add_argument("--gate", choices=["e2e", "security"], required=True)
parser.add_argument("--report", type=Path, required=True)
args = parser.parse_args()
name = f"protohub-{args.gate}-" + uuid4().hex[:10]


def port():
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


console, preview = port(), port()
while preview == console:
    preview = port()
env = {
    **os.environ,
    "PROTOHUB_MODE": "real-kind",
    "PROTOHUB_CLUSTER_NAME": name,
    "PROTOHUB_CONSOLE_PORT": str(console),
    "PROTOHUB_PREVIEW_PORT": str(preview),
    "PROTOHUB_RESET_CONFIRM": name,
    "PROTOHUB_NO_ACTIVATE": "1",
    "PROTOHUB_CONSOLE_URL": f"http://localhost:{console}",
    "PROTOHUB_PREVIEW_URL": f"http://localhost:{preview}",
}
(args.report / "fixture.json").write_text(
    json.dumps(
        {
            "cluster": name,
            "context": f"kind-{name}",
            "console_port": console,
            "preview_port": preview,
            "run_id": os.environ.get("PROTOHUB_HARNESS_RUN_ID"),
            "gate": args.gate,
        },
        indent=2,
    ),
    encoding="utf-8",
)


def run(argv, check=True):
    result = subprocess.run(argv, cwd=root, env=env, check=False)
    if check and result.returncode:
        raise RuntimeError(f"Child command failed (exit {result.returncode})")
    return result.returncode


def interrupted(signum, frame):
    raise KeyboardInterrupt


for sig in (signal.SIGINT, signal.SIGTERM):
    signal.signal(sig, interrupted)
code = 1
try:
    run(["bash", "scripts/local/up-real.sh"])
    if args.gate == "e2e":
        run(
            [
                "docker",
                "build",
                "-f",
                "tests/e2e/Dockerfile",
                "-t",
                f"protohub/browser:{name}",
                ".",
            ]
        )
        run(
            [
                "docker",
                "run",
                "--rm",
                "--network",
                "host",
                "--ipc=host",
                "-e",
                f"PROTOHUB_CONSOLE_URL={env['PROTOHUB_CONSOLE_URL']}",
                "-v",
                f"{args.report.resolve()}:/evidence",
                f"protohub/browser:{name}",
            ]
        )
        cases = list(ET.parse(args.report / "playwright.xml").iter("testcase"))
        assert cases and not any(case.find("skipped") is not None for case in cases)
    run(
        [
            sys.executable,
            "tests/e2e/assert_runtime.py",
            "--gate",
            args.gate,
            "--report",
            str(args.report),
        ]
    )
    code = 0
except (RuntimeError, KeyboardInterrupt) as exc:
    print(f"FAIL {args.gate}: {exc}")
finally:
    # Save only workload metadata, never Secrets, kubeconfig or environment dumps.
    for namespace in ("protohub-system", "protohub-samples"):
        result = subprocess.run(
            [
                "kubectl",
                "--context",
                f"kind-{name}",
                "-n",
                namespace,
                "get",
                "pods,deployments,services",
                "-o",
                "json",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode == 0:
            (args.report / f"{namespace}.json").write_text(
                result.stdout[:1_000_000], encoding="utf-8"
            )
    if run(["bash", "scripts/local/reset-local.sh"], check=False):
        print("FAIL fixture cleanup: ownership record retained; see fixture.json for exact target")
        code = 1
raise SystemExit(code)
