#!/usr/bin/env python3
"""Local agent workflow: persist intent, check scope, and require current evidence.

This is workflow assistance, not a security sandbox or tamper-proof attestation.
Only ignored workflow records are written; Git operations are read-only.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parent))
from local_paths import LocalPathError, worklogs_dir  # noqa: E402

DEFAULT_GATES = [
    "harness-self",
    "doctor-compose",
    "doctor-kind",
    "source",
    "contracts",
    "unit",
    "build",
    "public-hygiene",
    "integration",
    "e2e",
    "security",
]
IDENTIFIER = re.compile(r"[a-z0-9][a-z0-9_-]{0,63}\Z")


class WorkflowError(Exception):
    pass


def records_root(root: Path) -> Path:
    try:
        return worklogs_dir(root)
    except LocalPathError as exc:
        raise WorkflowError(str(exc)) from None


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def git(root: Path, *args: str) -> bytes:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=root,
            capture_output=True,
            timeout=20,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise WorkflowError("Read-only Git inspection could not finish") from exc
    if result.returncode:
        raise WorkflowError("Read-only Git inspection failed; use a repository with a HEAD commit")
    return result.stdout


def repository(root: Path) -> Path:
    root = root.resolve()
    actual = Path(os.fsdecode(git(root, "rev-parse", "--show-toplevel")).strip()).resolve()
    if actual != root:
        raise WorkflowError("--root must name the Git repository root")
    return root


def scope_path(value: str, *, directory: bool | None = None) -> str:
    """Scope is an exact file or a trailing-slash directory prefix; never a glob."""
    if not isinstance(value, str) or not value or "\\" in value or "\x00" in value:
        raise WorkflowError("Use nonempty repository-relative POSIX paths")
    if value == ".":
        return "."
    if (
        PurePosixPath(value).is_absolute()
        or ":" in value
        or "//" in value
        or any(part in {".", "..", ""} for part in value.rstrip("/").split("/"))
        or any(character in value for character in "*?[]")
    ):
        raise WorkflowError("Scope paths cannot be absolute, traversals, or glob patterns")
    is_directory = value.endswith("/") if directory is None else directory
    return value.rstrip("/") + ("/" if is_directory else "")


def matches(path: str, rule: str) -> bool:
    return rule == "." or path == rule.rstrip("/") or (rule.endswith("/") and path.startswith(rule))


def status_paths(raw: bytes) -> tuple[list[dict], set[str]]:
    entries, paths = [], set()
    values = raw.split(b"\0")
    index = 0
    while index < len(values) and values[index]:
        token = values[index]
        index += 1
        if len(token) < 4 or token[2:3] != b" ":
            raise WorkflowError("Unexpected Git porcelain format")
        code, path = os.fsdecode(token[:2]), scope_path(os.fsdecode(token[3:]))
        entry = {"status": code, "path": path}
        paths.add(path)
        if "R" in code or "C" in code:
            if index >= len(values) or not values[index]:
                raise WorkflowError("Incomplete Git rename record")
            original = scope_path(os.fsdecode(values[index]))
            index += 1
            entry["original_path"] = original
            paths.add(original)
        entries.append(entry)
    return entries, paths


def committed_paths(root: Path, baseline: str, head: str) -> set[str]:
    values = git(
        root,
        "diff",
        "--name-status",
        "-z",
        "--find-renames",
        "--no-ext-diff",
        "--no-textconv",
        baseline,
        head,
        "--",
    ).split(b"\0")
    index, result = 0, set()
    while index < len(values) and values[index]:
        code = values[index][:1]
        index += 1
        count = 2 if code in {b"R", b"C"} else 1
        for _ in range(count):
            if index >= len(values) or not values[index]:
                raise WorkflowError("Incomplete committed diff record")
            result.add(scope_path(os.fsdecode(values[index])))
            index += 1
    return result


def index_entries(root: Path) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for token in git(root, "ls-files", "--stage", "-z").split(b"\0"):
        if not token:
            continue
        metadata, path = token.split(b"\t", 1)
        if metadata.startswith(b"160000 "):
            raise WorkflowError(
                "Submodules require a separate workflow; flat-repository checks only"
            )
        result.setdefault(os.fsdecode(path), []).append(os.fsdecode(metadata))
    return result


def file_state(root: Path, path: str, index: dict[str, list[str]]) -> dict:
    candidate = root / path
    if not candidate.parent.resolve().is_relative_to(root):
        raise WorkflowError("Changed path traverses a symlink outside the repository")
    value = {"index": index.get(path, [])}
    try:
        metadata = candidate.lstat()
    except FileNotFoundError:
        return {**value, "kind": "missing"}
    if stat.S_ISLNK(metadata.st_mode):
        return {**value, "kind": "symlink", "sha256": digest(os.fsencode(os.readlink(candidate)))}
    if not stat.S_ISREG(metadata.st_mode):
        raise WorkflowError("Unsupported changed file type; refusing an incomplete snapshot")
    hasher = hashlib.sha256()
    with candidate.open("rb") as source:
        while chunk := source.read(65536):
            hasher.update(chunk)
    return {
        **value,
        "kind": "file",
        "sha256": hasher.hexdigest(),
        "mode": stat.S_IMODE(metadata.st_mode),
    }


def _snapshot(root: Path) -> dict:
    head = git(root, "rev-parse", "HEAD").decode().strip()
    status_before = git(root, "status", "--porcelain=v1", "-z", "--untracked-files=all")
    changes, paths = status_paths(status_before)
    index = index_entries(root)
    data = {
        "head": head,
        "dirty": bool(changes),
        "changes": changes,
        "index_diff_sha256": digest(
            git(root, "diff", "--cached", "--binary", "--no-ext-diff", "--no-textconv", "--")
        ),
        "worktree_diff_sha256": digest(
            git(root, "diff", "--binary", "--no-ext-diff", "--no-textconv", "--")
        ),
        "files": {path: file_state(root, path, index) for path in sorted(paths)},
    }
    if (
        git(root, "rev-parse", "HEAD").decode().strip() != head
        or git(root, "status", "--porcelain=v1", "-z", "--untracked-files=all") != status_before
    ):
        raise WorkflowError("Git state changed during inspection; retry after edits settle")
    data["fingerprint"] = digest(json.dumps(data, sort_keys=True).encode())
    return data


def snapshot(root: Path) -> dict:
    """For the gate runner: capture before AND after gates, excluding ignored evidence."""
    root = root.resolve()
    first, second = _snapshot(root), _snapshot(root)
    if first["fingerprint"] != second["fingerprint"]:
        raise WorkflowError("File content changed during inspection; retry after edits settle")
    return second


def _folder(root: Path, task_id: str) -> Path:
    if not isinstance(task_id, str) or not IDENTIFIER.fullmatch(task_id):
        raise WorkflowError(
            "Task ID must be 1-64 lowercase letters, digits, hyphens or underscores"
        )
    result = records_root(root) / "workflows" / task_id
    if not result.resolve().is_relative_to(root):
        raise WorkflowError("Workflow evidence directory escapes the repository")
    return result


def _write(path: Path, value: dict) -> None:
    temporary = path.with_name(path.name + "." + uuid4().hex + ".tmp")
    with temporary.open("x", encoding="utf-8") as output:
        json.dump(value, output, indent=2, ensure_ascii=True)
        output.write("\n")
    temporary.chmod(0o600)
    temporary.replace(path)


def load(root: Path, task_id: str) -> dict:
    path = _folder(root, task_id) / "workflow.json"
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise WorkflowError("Workflow does not exist or its record is invalid") from exc
    if (
        not isinstance(state, dict)
        or state.get("schema_version") != 1
        or state.get("id") != task_id
        or state.get("root") != str(root)
    ):
        raise WorkflowError("Workflow identity does not match this repository")
    return state


@contextmanager
def update(root: Path, task_id: str):
    folder = _folder(root, task_id)
    lock = folder / ".lock"
    try:
        descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except OSError as exc:
        raise WorkflowError("Workflow is unavailable or another command holds its lock") from exc
    os.close(descriptor)
    try:
        state = load(root, task_id)
        if state["status"] != "active":
            raise WorkflowError("Finished workflows are immutable; create a successor task")
        yield state
        state["updated_at"] = now()
        _write(folder / "workflow.json", state)
    finally:
        lock.unlink()


def start(
    root: Path,
    task_id: str,
    objective: str,
    allowed: list[str],
    forbidden: list[str],
    required_gates: list[str],
    max_repairs: int = 3,
    owners: dict | None = None,
    contracts: list[str] | None = None,
) -> dict:
    if not objective.strip() or len(objective) > 4000:
        raise WorkflowError("A concise, nonempty objective is required")
    if (
        not allowed
        or not required_gates
        or type(max_repairs) is not int
        or not 1 <= max_repairs <= 10
    ):
        raise WorkflowError(
            "Allowed paths, required gates and a repair budget of 1-10 are required"
        )
    allowed = list(dict.fromkeys(scope_path(path) for path in allowed))
    forbidden = list(
        dict.fromkeys([".git/", "worklogs/", ".harness/", *[scope_path(p) for p in forbidden]])
    )
    if any(not IDENTIFIER.fullmatch(name) for name in required_gates):
        raise WorkflowError("Invalid required gate ID")
    ownership = owners or {path: "coordinator" for path in allowed}
    if set(ownership) != set(allowed) or any(
        not str(owner).strip() for owner in ownership.values()
    ):
        raise WorkflowError("Assign one owner to each exact allowed scope rule")
    for first in allowed:
        for second in allowed:
            if first != second and (
                matches(first.rstrip("/"), second) or matches(second.rstrip("/"), first)
            ):
                raise WorkflowError("Allowed rules overlap; use one unambiguous owner per path")
    folder = _folder(root, task_id)
    ignored = subprocess.run(
        ["git", "check-ignore", "-q", str(folder / "workflow.json")], cwd=root, check=False
    )
    if ignored.returncode != 0:
        raise WorkflowError("Add worklogs/ to repository ignore rules before creating a workflow")
    baseline = snapshot(root)
    contract_hashes = {}
    for value in contracts or []:
        path = scope_path(value, directory=False)
        state = file_state(root, path, index_entries(root))
        if state["kind"] != "file":
            raise WorkflowError("Contract references must be existing regular files")
        contract_hashes[path] = state["sha256"]
    state = {
        "schema_version": 1,
        "id": task_id,
        "root": str(root),
        "objective": objective,
        "status": "active",
        "created_at": now(),
        "updated_at": now(),
        "baseline": baseline,
        "allowed_paths": allowed,
        "forbidden_paths": forbidden,
        "owners": ownership,
        "contracts": contract_hashes,
        "required_gates": list(dict.fromkeys(required_gates)),
        "max_repairs": max_repairs,
        "repairs": [],
        "decisions": [],
        "gate_evidence": [],
        "review_evidence": [],
    }
    try:
        folder.mkdir(parents=True, exist_ok=False, mode=0o700)
    except FileExistsError as exc:
        raise WorkflowError("Workflow ID already exists; refusing to overwrite it") from exc
    _write(folder / "workflow.json", state)
    return state


def check(root: Path, state: dict) -> dict:
    current = snapshot(root)
    committed = committed_paths(root, state["baseline"]["head"], current["head"])
    paths = set(current["files"]) | committed | set(state["baseline"]["files"])
    violations, preserved, changed = [], [], []
    index = index_entries(root)
    for path in sorted(paths):
        baseline_state = state["baseline"]["files"].get(path)
        current_state = current["files"].get(path) or file_state(root, path, index)
        if baseline_state is not None and current_state == baseline_state and path not in committed:
            preserved.append(path)
            continue
        changed.append(path)
        if any(matches(path, rule) for rule in state["forbidden_paths"]):
            violations.append({"path": path, "reason": "forbidden path changed"})
        elif not any(matches(path, rule) for rule in state["allowed_paths"]):
            violations.append({"path": path, "reason": "outside declared scope"})
    for path, baseline_hash in state["contracts"].items():
        current_hash = file_state(root, path, index).get("sha256")
        if current_hash != baseline_hash and not any(
            decision["kind"] == "contract" and decision["contract_hashes"].get(path) == current_hash
            for decision in state["decisions"]
        ):
            violations.append(
                {"path": path, "reason": "contract changed without a recorded decision"}
            )
    return {
        "status": "PASS" if not violations else "FAIL",
        "snapshot": current,
        "changed_paths": changed,
        "preserved_baseline_paths": preserved,
        "violations": violations,
    }


def note(root: Path, state: dict, kind: str, summary: str, paths: list[str]) -> None:
    if (
        kind not in {"implementation", "contract", "authorization"}
        or not summary.strip()
        or len(summary) > 4000
    ):
        raise WorkflowError("A decision kind and nonempty summary are required")
    normalized = [scope_path(path, directory=False) for path in paths]
    hashes = {}
    if kind == "contract":
        if not normalized or any(path not in state["contracts"] for path in normalized):
            raise WorkflowError("A contract decision must name registered contract files")
        index = index_entries(root)
        hashes = {path: file_state(root, path, index).get("sha256") for path in normalized}
    state["decisions"].append(
        {
            "at": now(),
            "kind": kind,
            "summary": summary,
            "paths": normalized,
            "contract_hashes": hashes,
        }
    )


def repair(state: dict, cause: str, action: str, next_check: str) -> None:
    if not all(value.strip() and len(value) <= 4000 for value in (cause, action, next_check)):
        raise WorkflowError("Record the observed cause, bounded repair and next check")
    if len(state["repairs"]) >= state["max_repairs"]:
        raise WorkflowError(
            "Repair budget exhausted; diagnose the unchanged blocker before replanning"
        )
    state["repairs"].append(
        {
            "attempt": len(state["repairs"]) + 1,
            "at": now(),
            "cause": cause,
            "action": action,
            "next_check": next_check,
        }
    )


def artifact(root: Path, value: str) -> tuple[Path, dict, str]:
    path = (root / value).resolve()
    evidence_root = records_root(root).resolve()
    if not evidence_root.is_relative_to(root) or not path.is_relative_to(evidence_root):
        raise WorkflowError("Evidence must be inside this repository's ignored worklogs/")
    try:
        if path.stat().st_size > 8 * 1024 * 1024:
            raise WorkflowError("Evidence JSON exceeds the bounded 8 MiB size")
        raw = path.read_bytes()
        data = json.loads(raw)
    except (OSError, ValueError) as exc:
        raise WorkflowError("Evidence JSON is unavailable or invalid") from exc
    if not isinstance(data, dict):
        raise WorkflowError("Evidence must be a JSON object")
    return path, data, digest(raw)


def same_snapshot(evidence: object, current: dict) -> bool:
    return isinstance(evidence, dict) and all(
        evidence.get(key) == current[key] for key in ("head", "dirty", "fingerprint")
    )


def evidence_time(value: str, state: dict) -> None:
    try:
        observed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        started = datetime.fromisoformat(state["created_at"])
        if observed.tzinfo is None or observed < started or observed > datetime.now(timezone.utc):
            raise ValueError
    except (ValueError, TypeError, AttributeError) as exc:
        raise WorkflowError("Evidence predates this workflow or has an invalid timestamp") from exc


def validate_gates(report: dict, state: dict, current: dict) -> None:
    if (
        report.get("status") != "PASS"
        or report.get("complete") is not True
        or report.get("interrupted") is not False
    ):
        raise WorkflowError("Required gate run did not complete with PASS")
    evidence_time(report.get("started_at"), state)
    evidence_time(report.get("finished_at"), state)
    if datetime.fromisoformat(
        report["finished_at"].replace("Z", "+00:00")
    ) < datetime.fromisoformat(report["started_at"].replace("Z", "+00:00")):
        raise WorkflowError("Gate completion time precedes its start")
    if (
        report.get("git_sha") != current["head"]
        or type(report.get("git_dirty")) is not bool
        or report.get("git_dirty") != current["dirty"]
        or not same_snapshot(report.get("git_snapshot"), current)
        or not same_snapshot(report.get("git_snapshot_after"), current)
    ):
        raise WorkflowError("Gate evidence is stale or lacks matching before/after Git snapshots")
    gates = report.get("gates")
    if not isinstance(gates, list) or any(not isinstance(gate, dict) for gate in gates):
        raise WorkflowError("Gate evidence has an invalid gate list")
    by_id = {gate.get("id"): gate for gate in gates}
    if len(by_id) != len(gates):
        raise WorkflowError("Gate evidence contains duplicate IDs")
    for required in state["required_gates"]:
        gate = by_id.get(required, {})
        if (
            gate.get("status") != "PASS"
            or type(gate.get("returncode")) is not int
            or gate["returncode"] != 0
        ):
            raise WorkflowError(f"Required gate {required} has no passing evidence")


def validate_review(review: dict, state: dict, current: dict) -> None:
    if (
        review.get("status") != "PASS"
        or review.get("independent") is not True
        or not isinstance(review.get("reviewer"), str)
        or not review["reviewer"].strip()
        or type(review.get("blocking_findings")) is not int
        or review["blocking_findings"] != 0
        or not review.get("summary")
    ):
        raise WorkflowError(
            "An independent review with no unresolved blocking findings is required"
        )
    evidence_time(review.get("completed_at"), state)
    if not same_snapshot(review.get("git_snapshot"), current):
        raise WorkflowError("Review evidence does not match the current code snapshot")


def record(root: Path, state: dict, kind: str, source: str) -> None:
    result = check(root, state)
    if result["status"] != "PASS":
        raise WorkflowError("Resolve scope/contract violations before recording evidence")
    path, data, content_hash = artifact(root, source)
    validator = validate_gates if kind == "gates" else validate_review
    validator(data, state, result["snapshot"])
    target = "gate_evidence" if kind == "gates" else "review_evidence"
    state[target].append(
        {
            "path": path.relative_to(root).as_posix(),
            "sha256": content_hash,
            "recorded_at": now(),
            "snapshot": result["snapshot"]["fingerprint"],
        }
    )


def finish(root: Path, state: dict) -> dict:
    result = check(root, state)
    if result["status"] != "PASS":
        raise WorkflowError("Workflow cannot finish with scope or contract violations")
    for key, validator in (("gate_evidence", validate_gates), ("review_evidence", validate_review)):
        valid = False
        for item in reversed(state[key]):
            try:
                _, data, content_hash = artifact(root, item["path"])
                if content_hash != item["sha256"]:
                    continue
                validator(data, state, result["snapshot"])
                valid = True
                break
            except WorkflowError:
                continue
        if not valid:
            raise WorkflowError(f"Workflow cannot finish without current passing {key}")
    if snapshot(root)["fingerprint"] != result["snapshot"]["fingerprint"]:
        raise WorkflowError("Files changed during finish; rerun the required evidence")
    state.update(status="finished", finished_at=now(), verified_snapshot=result["snapshot"])
    return {
        "status": "PASS",
        "id": state["id"],
        "head": result["snapshot"]["head"],
        "dirty": result["snapshot"]["dirty"],
        "fingerprint": result["snapshot"]["fingerprint"],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    commands = parser.add_subparsers(dest="command", required=True)
    create = commands.add_parser("start")
    create.add_argument("--id", required=True)
    create.add_argument("--objective", required=True)
    create.add_argument("--allow", action="append", required=True)
    create.add_argument("--forbid", action="append", default=[])
    create.add_argument("--owner", action="append", default=[], help="exact scope rule=owner")
    create.add_argument("--contract", action="append", default=[])
    create.add_argument("--required-gate", action="append", default=None)
    create.add_argument("--max-repairs", type=int, default=3)
    for name in ("check", "show", "finish"):
        commands.add_parser(name).add_argument("--id", required=True)
    for name in ("record-gates", "record-review"):
        command = commands.add_parser(name)
        command.add_argument("--id", required=True)
        command.add_argument("--file", required=True)
    decision = commands.add_parser("note")
    decision.add_argument("--id", required=True)
    decision.add_argument(
        "--kind", choices=["implementation", "contract", "authorization"], default="implementation"
    )
    decision.add_argument("--summary", required=True)
    decision.add_argument("--path", action="append", default=[])
    retry = commands.add_parser("repair")
    retry.add_argument("--id", required=True)
    retry.add_argument("--cause", required=True)
    retry.add_argument("--action", required=True)
    retry.add_argument("--next-check", required=True)
    commands.add_parser("snapshot")
    args = parser.parse_args(argv)
    try:
        root = repository(args.root)
        if args.command == "snapshot":
            output = snapshot(root)
        elif args.command == "start":
            ownership = {}
            for assignment in args.owner:
                path, separator, owner = assignment.partition("=")
                if not separator or path in ownership:
                    raise WorkflowError("Owner assignments require unique path=owner pairs")
                ownership[scope_path(path)] = owner
            output = start(
                root,
                args.id,
                args.objective,
                args.allow,
                args.forbid,
                args.required_gate or DEFAULT_GATES,
                args.max_repairs,
                ownership or None,
                args.contract,
            )
        elif args.command in {"check", "show"}:
            state = load(root, args.id)
            output = check(root, state) if args.command == "check" else state
            if args.command == "check" and output["status"] != "PASS":
                print(json.dumps(output, indent=2))
                return 1
        else:
            with update(root, args.id) as state:
                if args.command == "finish":
                    output = finish(root, state)
                elif args.command == "note":
                    note(root, state, args.kind, args.summary, args.path)
                    output = {"status": "RECORDED", "decisions": len(state["decisions"])}
                elif args.command == "repair":
                    repair(state, args.cause, args.action, args.next_check)
                    output = {
                        "status": "RECORDED",
                        "attempts": len(state["repairs"]),
                        "budget": state["max_repairs"],
                    }
                else:
                    record(
                        root,
                        state,
                        "gates" if args.command == "record-gates" else "review",
                        args.file,
                    )
                    output = {"status": "RECORDED", "kind": args.command}
        print(json.dumps(output, indent=2))
        return 0
    except (WorkflowError, OSError, ValueError, KeyError, TypeError) as exc:
        print(f"REFUSED workflow: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
