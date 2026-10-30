#!/usr/bin/env python3
"""Validate installed project skills against reviewed sources and file hashes; no network."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def validate(root: Path) -> list[str]:
    errors: list[str] = []
    root = root.resolve()
    data = json.loads((root / "harness/skills.lock.json").read_text(encoding="utf-8"))
    if (
        type(data.get("schema_version")) is not int
        or data["schema_version"] != 1
        or not data.get("skills")
    ):
        return ["Missing nonempty skill manifest"]
    names = set()
    expected_directories = set()
    for skill in data["skills"]:
        name = skill["name"]
        if not re.fullmatch(r"[a-z0-9-]{1,64}", name) or name in names:
            errors.append("Invalid or duplicate skill name")
        names.add(name)
        directory = root / skill["directory"]
        expected_directories.add(directory.name)
        if (
            directory != root / ".agents/skills" / name
            or directory.is_symlink()
            or not directory.resolve().is_relative_to(root)
        ):
            errors.append(f"Unsafe skill directory: {name}")
            continue
        source = skill["source"]
        if source["kind"] == "github" and not re.fullmatch(r"[a-f0-9]{40}", source.get("ref", "")):
            errors.append(f"Unpinned source: {name}")
        reference = skill.get("reference_source")
        if reference and not re.fullmatch(r"[a-f0-9]{40}", reference.get("ref", "")):
            errors.append(f"Unpinned supporting reference: {name}")
        if not skill.get("license") or (
            source["kind"] == "github" and not skill.get("license_evidence")
        ):
            errors.append(f"Missing license evidence: {name}")
        manifest = directory / "SKILL.md"
        if not manifest.is_file():
            errors.append(f"Missing SKILL.md: {name}")
            continue
        text = manifest.read_text(encoding="utf-8")
        if not re.search(rf"(?m)^name:\s*[\"']?{re.escape(name)}[\"']?\s*$", text) or not re.search(
            r"(?m)^description:\s*\S", text
        ):
            errors.append(f"Invalid discovery metadata: {name}")
        actual = {p.relative_to(root).as_posix() for p in directory.rglob("*") if p.is_file()}
        if actual != set(skill["files"]):
            errors.append(f"Unreviewed added or missing skill files: {name}")
        for path, expected in skill["files"].items():
            target = root / path
            if not target.resolve().is_relative_to(directory.resolve()) or target.is_symlink():
                errors.append(f"Unsafe skill file path: {name}")
            elif (
                not target.is_file() or hashlib.sha256(target.read_bytes()).hexdigest() != expected
            ):
                errors.append(f"Changed skill file: {path}")
        for path in skill.get("license_evidence", []):
            target = root / path
            if not target.resolve().is_relative_to(root) or not target.is_file():
                errors.append(f"Missing license notice: {name}")
    skill_root = root / ".agents/skills"
    actual_directories = {p.name for p in skill_root.iterdir() if p.is_dir()}
    if actual_directories != expected_directories:
        errors.append("Installed skill set differs from reviewed manifest")
    for path, expected in data.get("notices", {}).items():
        target = root / path
        if (
            not target.resolve().is_relative_to(root)
            or target.is_symlink()
            or not target.is_file()
            or hashlib.sha256(target.read_bytes()).hexdigest() != expected
        ):
            errors.append(f"Changed upstream notice: {path}")
    return errors


if __name__ == "__main__":
    findings = validate(ROOT)
    if findings:
        print("\n".join(findings))
        raise SystemExit(1)
    print("PASS project skills: discovery, pinned sources, licenses and file hashes")
