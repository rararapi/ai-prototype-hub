#!/usr/bin/env python3
"""Shared make/CI gates. Default Docker executor; host mode is explicit and partial."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
SERVER = ROOT / "apps/server"
WEB = ROOT / "apps/web"
sys.path.insert(0, str(ROOT / "harness"))
import doctor  # noqa: E402
from local_paths import worklogs_dir  # noqa: E402


class MissingPrerequisite(Exception):
    pass


def require(command: str) -> str:
    value = shutil.which(command)
    if value is None:
        raise MissingPrerequisite(f"Required command unavailable: {command}")
    return value


def child(argv: list[str], cwd: Path = ROOT, env: dict | None = None) -> None:
    """Never pass a child's 78 through as a preflight BLOCKED result."""
    result = subprocess.run(argv, cwd=cwd, env=env, check=False)
    if result.returncode:
        print(f"FAIL child exit={result.returncode}: {Path(argv[0]).name}", flush=True)
        raise SystemExit(1)


def evidence(gate: str) -> Path:
    base = os.environ.get("PROTOHUB_HARNESS_REPORT_DIR")
    if base:
        result = Path(base) / gate
    else:
        run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:8]
        result = worklogs_dir(ROOT) / "reports" / run_id / gate
    result.mkdir(parents=True, exist_ok=True, mode=0o700)
    print(f"Evidence: {result}", flush=True)
    return result


def assert_junit(path: Path) -> None:
    root = ET.parse(path).getroot()
    cases = list(root.iter("testcase"))
    if not cases or any(
        list(case.iter(tag)) for case in cases for tag in ("skipped", "failure", "error")
    ):
        raise AssertionError(f"Required test suite empty, skipped or unsuccessful: {path.name}")


def python() -> str:
    configured = os.environ.get("UV_PROJECT_ENVIRONMENT")
    environment = Path(configured) if configured else SERVER / ".venv"
    if not environment.is_absolute():
        environment = SERVER / environment
    path = environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    if not path.is_file():
        raise MissingPrerequisite("Run uv sync --locked --project apps/server before host checks")
    return str(path)


def npm() -> str:
    if not (WEB / "node_modules").is_dir():
        raise MissingPrerequisite("Run npm ci in apps/web before host checks")
    return require("npm")


def pytest(paths: list[str], report: Path, extra: list[str] | None = None, env=None) -> None:
    child(
        [python(), "-m", "pytest", *paths, *(extra or []), f"--junitxml={report}"],
        SERVER,
        env,
    )
    assert_junit(report)


def host(gate: str, report: Path) -> None:
    if gate == "source":
        py = python()
        child([py, "scripts/checks/skills.py"])
        child([py, "-m", "ruff", "check", "src", "tests", "migrations"], SERVER)
        child(
            [py, "-m", "ruff", "format", "--check", "src", "tests", "migrations"],
            SERVER,
        )
        child([py, "-m", "mypy", "src/protohub"], SERVER)
        child(
            [
                py,
                "-m",
                "ruff",
                "check",
                "harness",
                "scripts",
                "tests/integration",
                "tests/e2e",
            ]
        )
        child(
            [
                py,
                "-m",
                "ruff",
                "format",
                "--check",
                "harness",
                "scripts",
                "tests/integration",
                "tests/e2e",
            ]
        )
        child([npm(), "run", "lint"], WEB)
        child([npm(), "run", "typecheck"], WEB)
        bash = (
            require("bash") if os.name != "nt" else str(Path("C:/Program Files/Git/bin/bash.exe"))
        )
        if not Path(bash).exists():
            raise MissingPrerequisite("Bash required for shell syntax validation")
        scripts = sorted([*ROOT.glob("scripts/**/*.sh"), *ROOT.glob(".devcontainer/*.sh")])
        if not scripts:
            raise AssertionError("No shell scripts found")
        for script in scripts:
            child([bash, "-n", str(script)])
    elif gate == "contracts":
        child([python(), str(ROOT / "contracts/check.py")])
        child([npm(), "run", "check:api"], WEB)
    elif gate == "unit":
        pytest(
            ["tests", str(ROOT / "tests/e2e/test_security_static.py")],
            report / "pytest.xml",
            ["-m", "not postgres"],
        )
        child(
            [
                npm(),
                "run",
                "test:unit",
                "--",
                "--reporter=default",
                "--reporter=junit",
                f"--outputFile={report / 'vitest.xml'}",
            ],
            WEB,
        )
        assert_junit(report / "vitest.xml")
    elif gate == "build":
        child([python(), "-m", "build", "--no-isolation"], SERVER)
        child([npm(), "run", "build"], WEB)
    else:
        raise AssertionError(f"Unsupported host gate {gate}")


def public_hygiene(report: Path) -> None:
    # Working tree inspection includes uncommitted code, excludes generated evidence/deps.
    ignored = {
        ".git",
        ".venv",
        ".uv-cache",
        "node_modules",
        "worklogs",
        ".harness",
        "dist",
        "build",
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
    }
    forbidden = re.compile(
        r"(?:^\.env(?:\..*)?$|\.(?:pem|key|p12|pfx)$|^id_(?:rsa|ed25519)$|^kubeconfig$)"
    )
    # Prefixes split so this scanner's own source isn't mistaken for a credential.
    patterns = [
        re.compile("-----BEGIN " + r"(?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
        re.compile("AK" + r"IA[0-9A-Z]{16}"),
        re.compile("gh" + r"[pousr]_[A-Za-z0-9]{30,}"),
        re.compile("sk" + r"-(?:proj-)?[A-Za-z0-9_-]{32,}"),
        re.compile(r"https?://[^\s/]+\.(?:internal|corp)(?:[/:\s]|$)"),
    ]
    findings, checked = [], 0
    for directory, dirs, files in os.walk(ROOT):
        dirs[:] = [name for name in dirs if name not in ignored and not name.endswith(".egg-info")]
        for name in files:
            path = Path(directory) / name
            relative = path.relative_to(ROOT).as_posix()
            if forbidden.search(name) and not name.endswith(".example"):
                findings.append({"path": relative, "reason": "forbidden secret/config file"})
                continue
            if path.is_symlink() or path.stat().st_size > 4_000_000:
                continue
            try:
                value = path.read_text(encoding="utf-8")
            except UnicodeError:
                continue
            checked += 1
            if any(pattern.search(value) for pattern in patterns):
                # Synthetic harness regression fixtures deliberately exercise redaction.
                if relative not in {
                    "harness/tests/test_harness.py",
                    "docs/setup/backend (1).md",
                }:
                    findings.append(
                        {
                            "path": relative,
                            "reason": "credential/internal-value pattern",
                        }
                    )
    (report / "hygiene.json").write_text(
        json.dumps(
            {
                "checked_text_files": checked,
                "findings": findings,
                "limits": "Pattern and filename checks are best effort; human review still required.",
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    if findings:
        print(json.dumps(findings, indent=2))
        raise AssertionError("Public hygiene findings require review")
    print(f"PASS public hygiene: {checked} text files; heuristic scan plus manual review required")


def docker_ready(mode: str = "compose") -> None:
    if doctor.main(["--mode", mode]):
        raise MissingPrerequisite("WSL/Linux local Docker prerequisites failed; see doctor output")


def docker_gate(gate: str, report: Path) -> None:
    docker_ready()
    tag = "protohub/checks:local"
    child(["docker", "build", "-f", "scripts/checks/Dockerfile", "-t", tag, "."])
    child(
        [
            "docker",
            "run",
            "--rm",
            "--network",
            "none",
            "-v",
            f"{report}:/evidence",
            "-e",
            "PROTOHUB_CHECK_EXECUTOR=host",
            "-e",
            "PROTOHUB_HARNESS_REPORT_DIR=/evidence",
            "-e",
            f"PROTOHUB_EVIDENCE_UID={os.getuid()}",
            "-e",
            f"PROTOHUB_EVIDENCE_GID={os.getgid()}",
            tag,
            "python3",
            "scripts/checks/check.py",
            gate,
        ]
    )
    if gate == "build":
        child(
            [
                "docker",
                "build",
                "-f",
                ".devcontainer/Dockerfile",
                "-t",
                "protohub/devcontainer:local",
                ".",
            ]
        )
        child(
            ["docker", "compose", "-f", "compose.yaml", "build"],
            env={**os.environ, "PROTOHUB_OWNER_ID": "checks-build-only"},
        )
        child(
            [
                "docker",
                "build",
                "-f",
                "examples/hello-web/Dockerfile",
                "-t",
                "protohub/hello-web:dev",
                ".",
            ]
        )


def preserve_evidence_owner(report: Path, uid: int, gid: int) -> None:
    """Transfer only this new report subtree; never follow generated symlinks."""
    if report.is_symlink():
        raise AssertionError("Report root cannot be a symlink")
    for path in [report, *report.rglob("*")]:
        if path.is_symlink():
            continue
        if not path.resolve().is_relative_to(report.resolve()):
            raise AssertionError("Evidence path escaped its report directory")
        path.chmod(0o700 if path.is_dir() else 0o600)
        os.chown(path, uid, gid, follow_symlinks=False)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "gate",
        choices=[
            "source",
            "contracts",
            "unit",
            "build",
            "public-hygiene",
            "integration",
            "e2e",
            "security",
        ],
    )
    parser.add_argument(
        "--executor",
        choices=["docker", "host"],
        default=os.environ.get("PROTOHUB_CHECK_EXECUTOR", "docker"),
    )
    args = parser.parse_args(argv)
    report = evidence(args.gate)
    try:
        if args.gate == "public-hygiene":
            public_hygiene(report)
        elif args.gate in {"integration", "e2e", "security"}:
            docker_ready("kind" if args.gate != "integration" else "compose")
            child(
                [
                    sys.executable,
                    str(
                        ROOT
                        / "tests"
                        / ("integration/run.py" if args.gate == "integration" else "e2e/run.py")
                    ),
                    "--gate",
                    args.gate,
                    "--report",
                    str(report),
                ]
            )
        elif args.executor == "host":
            host(args.gate, report)
        else:
            docker_gate(args.gate, report)
    except MissingPrerequisite as exc:
        print(f"BLOCKED {args.gate}: {exc}")
        return 78
    except (AssertionError, OSError, ValueError) as exc:
        print(f"FAIL {args.gate}: {exc}")
        return 1
    finally:
        if (
            os.name == "posix"
            and os.geteuid() == 0
            and os.environ.get("PROTOHUB_HARNESS_REPORT_DIR") == "/evidence"
        ):
            uid = os.environ.get("PROTOHUB_EVIDENCE_UID", "")
            gid = os.environ.get("PROTOHUB_EVIDENCE_GID", "")
            if uid.isdigit() and gid.isdigit() and int(uid) < 2**31 and int(gid) < 2**31:
                preserve_evidence_owner(report, int(uid), int(gid))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
