"""Create and remove only a uniquely named ephemeral PostgreSQL fixture."""

import argparse
import json
import os
import signal
import subprocess
from pathlib import Path
from uuid import uuid4

root = Path(__file__).resolve().parents[2]
parser = argparse.ArgumentParser()
parser.add_argument("--gate", required=True, choices=["integration"])
parser.add_argument("--report", required=True, type=Path)
args = parser.parse_args()
project = "protohub-it-" + uuid4().hex[:12]
env = {
    **os.environ,
    "COMPOSE_PROJECT_NAME": project,
    "PROTOHUB_TEST_REPORT_DIR": str(args.report.resolve()),
}
command = ["docker", "compose", "-p", project, "-f", "tests/integration/compose.yaml"]
existing = subprocess.run(
    ["docker", "ps", "-aq", "--filter", f"label=com.docker.compose.project={project}"],
    capture_output=True,
    text=True,
    check=True,
)
if existing.stdout.strip():
    raise SystemExit("Refusing to reuse an existing fixture")
(args.report / "fixture.json").write_text(
    json.dumps({"project": project, "ephemeral": True, "database": "protohub_test"}, indent=2),
    encoding="utf-8",
)
code = 1


def interrupted(signum, frame):
    # The harness grants a bounded cleanup grace to this entire process group.
    # Convert termination into stack unwinding so owned Compose resources are removed.
    raise KeyboardInterrupt


for sig in (signal.SIGINT, signal.SIGTERM):
    signal.signal(sig, interrupted)
try:
    result = subprocess.run(
        [
            *command,
            "up",
            "--build",
            "--abort-on-container-exit",
            "--exit-code-from",
            "tests",
            "tests",
        ],
        cwd=root,
        env=env,
        check=False,
    )
    code = 0 if result.returncode == 0 else 1
except KeyboardInterrupt:
    code = 1
    print("FAIL integration: interrupted; removing owned fixture")
finally:
    result = subprocess.run(
        [*command, "down", "--volumes", "--remove-orphans"],
        cwd=root,
        env=env,
        check=False,
    )
    if result.returncode:
        code = 1
raise SystemExit(code)
