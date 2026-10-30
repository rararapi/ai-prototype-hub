#!/usr/bin/env python3
"""Fail-closed, bounded-output, stdlib-only verification runner."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

MAX_LOG_BYTES = 1024 * 1024


def redact(value: str) -> str:
    value = re.sub(
        r"-----BEGIN [^-]*PRIVATE KEY-----[\s\S]*?(?:-----END [^-]*PRIVATE KEY-----|\Z)",
        "[REDACTED]",
        value,
    )
    for key, secret in os.environ.items():
        if re.search(r"SECRET|TOKEN|PASSWORD|API_KEY|DATABASE_URL", key, re.I) and len(secret) >= 6:
            value = value.replace(secret, "[REDACTED]")
    value = re.sub(
        r"(?im)((?:password|token|secret|authorization|api_key)\s*[=:]\s*)[^\s,;]+",
        r"\1[REDACTED]",
        value,
    )
    value = re.sub(r"(?i)(postgres(?:ql)?(?:\+\w+)?://)[^\s/@]+:[^\s/@]+@", r"\1[REDACTED]@", value)
    return value


class BoundedCapture:
    def __init__(self, limit: int = MAX_LOG_BYTES):
        self.limit = limit
        self.data = bytearray()
        self.truncated = False

    def add(self, chunk: bytes) -> None:
        space = self.limit - len(self.data)
        self.data.extend(chunk[:space])
        self.truncated |= len(chunk) > space

    def safe_log(self) -> str:
        value = self.data.decode("utf-8", errors="replace")
        if self.truncated:
            value = value[: value.rfind("\n") + 1] if "\n" in value else ""
            return redact(value) + "\n[LOG TRUNCATED; output was drained]\n"
        return redact(value)


def stop_group(process: subprocess.Popen, cleanup_grace_seconds: float = 0.1) -> None:
    if os.name == "posix":
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        deadline = time.monotonic() + cleanup_grace_seconds
        while time.monotonic() < deadline:
            # Reap the wrapper, but wait for its whole group: a fixture descendant
            # may still be removing Docker resources after the wrapper has exited.
            process.poll()
            try:
                os.killpg(process.pid, 0)
            except ProcessLookupError:
                break
            time.sleep(min(0.02, max(0, deadline - time.monotonic())))
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    else:
        # Only this runner's newly created child tree, never a name-wide kill.
        killer = subprocess.Popen(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        killer.wait(timeout=10)
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def execute(
    argv: list[str],
    cwd: Path,
    timeout: float,
    env: dict[str, str],
    interrupted: list,
    cleanup_grace_seconds: float = 0.1,
) -> dict:
    capture = BoundedCapture()
    argv = [sys.executable if argv[0] == "python3" else argv[0], *argv[1:]]
    if not Path(argv[0]).is_file() and shutil.which(argv[0]) is None:
        return {
            "returncode": None,
            "reason": "Required executable is unavailable",
            "status": "BLOCKED",
            "output": "",
            "output_truncated": False,
        }
    started = time.monotonic()
    try:
        process = subprocess.Popen(
            argv,
            cwd=cwd,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            start_new_session=os.name == "posix",
        )
    except OSError:
        return {
            "returncode": None,
            "reason": "Executable could not be started",
            "status": "BLOCKED",
            "output": "",
            "output_truncated": False,
        }

    def drain():
        try:
            while chunk := process.stdout.read(65536):
                capture.add(chunk)
        finally:
            process.stdout.close()

    reader = threading.Thread(target=drain, daemon=True)
    reader.start()
    reason = ""
    while process.poll() is None:
        if interrupted or time.monotonic() - started > timeout:
            reason = "Interrupted" if interrupted else "Time limit exceeded"
            stop_group(process, cleanup_grace_seconds)
            break
        time.sleep(min(0.02, timeout))
    reader.join(timeout=3)
    if reader.is_alive():
        stop_group(process, cleanup_grace_seconds)
        reader.join(timeout=3)
        reason = reason or "Child output did not close"
    return {
        "returncode": process.returncode,
        "reason": reason,
        "status": "FAIL" if reason or process.returncode else "PASS",
        "output": capture.safe_log(),
        "output_truncated": capture.truncated,
    }


def contained(root: Path, relative: str) -> Path:
    if not isinstance(relative, str) or Path(relative).is_absolute():
        raise ValueError("Paths must be repository-relative")
    value = (root / relative).resolve()
    if not value.is_relative_to(root):
        raise ValueError("Path escapes repository")
    return value


def validate_manifest(root: Path, manifest: dict, group: str) -> list[dict]:
    if not isinstance(manifest, dict):
        raise ValueError("Manifest must be an object")
    if type(manifest.get("schema_version")) is not int or manifest["schema_version"] != 1:
        raise ValueError("Unsupported schema_version")
    groups, gates = manifest.get("groups"), manifest.get("gates")
    if not isinstance(groups, dict) or not isinstance(gates, list) or not gates:
        raise ValueError("Groups and nonempty gates are required")
    by_id = {}
    for gate in gates:
        if not isinstance(gate, dict):
            raise ValueError("Gate must be an object")
        name = gate.get("id")
        if not isinstance(name, str) or not re.fullmatch(r"[a-zA-Z0-9_-]+", name) or name in by_id:
            raise ValueError("Invalid or duplicate gate ID")
        argv = gate.get("argv")
        if (
            not isinstance(argv, list)
            or not argv
            or not all(isinstance(v, str) and v and "\x00" not in v for v in argv)
        ):
            raise ValueError("argv must be a nonempty string array")
        timeout = gate.get("timeout_seconds")
        if type(timeout) not in (int, float) or not 0 < timeout <= 7200:
            raise ValueError("Invalid timeout")
        cleanup_grace = gate.get("cleanup_grace_seconds", 0.1)
        if type(cleanup_grace) not in (int, float) or not 0.1 <= cleanup_grace <= 60:
            raise ValueError("Invalid cleanup grace period")
        contained(root, gate.get("cwd", "."))
        for key in ("required_paths", "depends_on"):
            if not isinstance(gate.get(key), list) or not all(
                isinstance(v, str) for v in gate[key]
            ):
                raise ValueError("Invalid path/dependency list")
        for path in gate["required_paths"]:
            contained(root, path)
        if "blocked_exit_codes" in gate:
            codes = gate["blocked_exit_codes"]
            if (
                not isinstance(codes, list)
                or any(type(v) is not int or not 1 <= v <= 255 for v in codes)
                or len(set(codes)) != len(codes)
            ):
                raise ValueError("Invalid blocked exit codes")
        by_id[name] = gate
    selected = groups.get(group)
    if not isinstance(selected, list) or not selected:
        raise ValueError("Group is missing or empty")
    result, visiting, visited = [], set(), set()

    def visit(name):
        if name in visiting or name not in by_id:
            raise ValueError("Cyclic or unknown dependency")
        if name in visited:
            return
        visiting.add(name)
        for dependency in by_id[name]["depends_on"]:
            visit(dependency)
        visiting.remove(name)
        visited.add(name)
        result.append(by_id[name])

    for name in selected:
        visit(name)
    return result


def private_write(path: Path, value: str) -> None:
    path.write_text(value, encoding="utf-8")
    path.chmod(0o600)


def run(root: Path, group: str, manifest_path: str = "harness/gates.json") -> dict:
    root = root.resolve()
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:8]
    directory = root / ".harness" / "reports" / run_id
    directory.mkdir(parents=True, mode=0o700)
    directory.chmod(0o700)
    report = {
        "run_id": run_id,
        "group": group,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "gates": [],
        "interrupted": False,
        "interrupted_by": None,
        "complete": True,
        "report_path": str(directory / "report.json"),
    }
    try:
        gates = validate_manifest(
            root,
            json.loads(contained(root, manifest_path).read_text(encoding="utf-8")),
            group,
        )
    except (ValueError, OSError, TypeError, KeyError):
        report.update(
            status="BLOCKED",
            gates=[
                {
                    "id": "manifest",
                    "status": "BLOCKED",
                    "reason": "Invalid, missing or unsafe manifest",
                    "returncode": None,
                }
            ],
        )
        private_write(directory / "report.json", json.dumps(report, indent=2))
        return report
    interrupted: list = []
    old_handlers = {}

    def on_signal(signum, _frame):
        if not interrupted:
            interrupted.append(signum)

    if threading.current_thread() is threading.main_thread():
        for sig in (signal.SIGINT, signal.SIGTERM):
            old_handlers[sig] = signal.signal(sig, on_signal)
    try:
        git = execute(["git", "rev-parse", "HEAD"], root, 3, dict(os.environ), [])
        dirty = execute(["git", "status", "--porcelain"], root, 3, dict(os.environ), [])
        report.update(
            git_sha=git["output"].strip() if git["status"] == "PASS" else None,
            git_dirty=bool(dirty["output"]) if dirty["status"] == "PASS" else None,
        )
        statuses = {}
        for gate in gates:
            started = time.monotonic()
            entry = {
                "id": gate["id"],
                "returncode": None,
                "reason": "",
                "status": "BLOCKED",
                "output_truncated": False,
            }
            missing = [
                path for path in gate["required_paths"] if not contained(root, path).exists()
            ]
            if interrupted:
                entry["reason"] = "Previous gate interrupted"
            elif any(statuses.get(dependency) != "PASS" for dependency in gate["depends_on"]):
                entry["reason"] = "Required gate did not pass"
            elif missing or not contained(root, gate["cwd"]).is_dir():
                entry["reason"] = "Required path or working directory is unavailable"
            else:
                env = dict(os.environ)
                env.update(
                    PROTOHUB_HARNESS_RUN_ID=run_id,
                    PROTOHUB_HARNESS_REPORT_DIR=str(directory),
                    PROTOHUB_HARNESS_GATE_ID=gate["id"],
                )
                result = execute(
                    gate["argv"],
                    contained(root, gate["cwd"]),
                    gate["timeout_seconds"],
                    env,
                    interrupted,
                    gate.get("cleanup_grace_seconds", 0.1),
                )
                output = result.pop("output")
                entry.update(result)
                if (
                    entry["returncode"] in gate.get("blocked_exit_codes", [])
                    and not entry["reason"]
                ):
                    entry.update(
                        status="BLOCKED",
                        reason="Prerequisite unavailable (declared exit code)",
                    )
                if interrupted:
                    entry.update(status="FAIL", reason="Interrupted")
                entry["log"] = gate["id"] + ".log"
                private_write(directory / entry["log"], output)
            entry["duration_seconds"] = round(time.monotonic() - started, 3)
            statuses[gate["id"]] = entry["status"]
            report["gates"].append(entry)
            print(f"{entry['status']} {gate['id']}: {entry['reason']}", flush=True)
        report["status"] = (
            "FAIL"
            if "FAIL" in statuses.values()
            else "BLOCKED"
            if "BLOCKED" in statuses.values()
            else "PASS"
        )
        if interrupted:
            report.update(
                interrupted=True,
                complete=False,
                interrupted_by=signal.Signals(interrupted[0]).name,
                status="FAIL",
            )
        report["finished_at"] = datetime.now(timezone.utc).isoformat()
        private_write(directory / "report.json", json.dumps(report, indent=2))
    finally:
        for sig, handler in old_handlers.items():
            signal.signal(sig, handler)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--group", default="quick")
    parser.add_argument("--manifest", default="harness/gates.json")
    args = parser.parse_args()
    report = run(Path(__file__).resolve().parents[1], args.group, args.manifest)
    print(report["report_path"])
    return {"PASS": 0, "FAIL": 1, "BLOCKED": 2}[report["status"]]


if __name__ == "__main__":
    raise SystemExit(main())
