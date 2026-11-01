"""Generated records migrate without losing ownership, history or privacy guards."""

import contextlib
import importlib.util
import io
import json
import os
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("worklogs_paths", ROOT / "harness/local_paths.py")
paths = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(paths)
LocalPathError, worklogs_dir = paths.LocalPathError, paths.worklogs_dir


class LocalPathsTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="protohub-worklogs-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()

    def test_fresh_path_is_lazy_without_creating_directories(self):
        self.assertEqual(worklogs_dir(self.root), self.root / "worklogs")
        self.assertEqual(list(self.root.iterdir()), [])

    def test_atomic_move_preserves_bytes_inode_permissions_and_historical_paths(self):
        record = self.root / ".harness/local/kind/protohub-test/state.json"
        record.parent.mkdir(parents=True)
        original = b'{"node_id":"retained", "path":".harness/original.json"}\n'
        record.write_bytes(original)
        record.chmod(0o600)
        before = record.stat()
        archive = self.root / ".harness/reports/nested/.harness/trace.bin"
        archive.parent.mkdir(parents=True)
        archive.write_bytes(b"\x00\x01synthetic-trace")
        target = worklogs_dir(self.root)
        moved = target / record.relative_to(self.root / ".harness")
        self.assertEqual(moved.read_bytes(), original)
        self.assertEqual(moved.stat().st_ino, before.st_ino)
        if os.name == "posix":
            self.assertEqual(stat.S_IMODE(moved.stat().st_mode), 0o600)
            self.assertEqual(moved.stat().st_uid, before.st_uid)
        self.assertEqual(
            (target / "reports/nested/.harness/trace.bin").read_bytes(), b"\x00\x01synthetic-trace"
        )
        self.assertFalse((self.root / ".harness").exists())
        self.assertEqual(worklogs_dir(self.root), target)
        self.assertEqual(moved.read_bytes(), original)

    def test_both_roots_are_preserved_and_never_merged(self):
        for name in (".harness", "worklogs"):
            (self.root / name).mkdir()
            (self.root / name / "owner.json").write_text(name)
        with self.assertRaisesRegex(LocalPathError, "Both"):
            worklogs_dir(self.root)
        for name in (".harness", "worklogs"):
            self.assertEqual((self.root / name / "owner.json").read_text(), name)

    def test_symlink_and_file_roots_do_not_touch_external_targets(self):
        for name in (".harness", "worklogs"):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as outside:
                target = self.root / name
                target.symlink_to(outside, target_is_directory=True)
                with self.assertRaisesRegex(LocalPathError, "ordinary"):
                    worklogs_dir(self.root)
                self.assertEqual(list(Path(outside).iterdir()), [])
                target.unlink()
                target.write_text("retained-file")
                with self.assertRaises(LocalPathError):
                    worklogs_dir(self.root)
                self.assertEqual(target.read_text(), "retained-file")
                target.unlink()

    def test_git_checkout_requires_ignored_destination_before_any_move(self):
        subprocess.run(["git", "init", "--quiet", str(self.root)], check=True)
        (self.root / ".gitignore").write_text(".harness/\n")
        legacy = self.root / ".harness"
        legacy.mkdir()
        (legacy / "owner.json").write_text("retained-owner")
        (legacy / "private.log").write_text("retained-private-record")
        for rules in (".harness/\n", ".harness/\n*.json\n"):
            (self.root / ".gitignore").write_text(rules)
            with self.assertRaisesRegex(LocalPathError, "ignore"):
                worklogs_dir(self.root)
            self.assertTrue(legacy.is_dir())
            self.assertFalse((self.root / "worklogs").exists())
            self.assertEqual((legacy / "private.log").read_text(), "retained-private-record")
        (self.root / ".gitignore").write_text(".harness/\nworklogs/\n")
        target = worklogs_dir(self.root)
        self.assertEqual((target / "owner.json").read_text(), "retained-owner")

    def test_hygiene_excludes_new_and_legacy_generated_records(self):
        spec = importlib.util.spec_from_file_location(
            "worklogs_checks", ROOT / "scripts/checks/check.py"
        )
        checks = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(checks)
        (self.root / "README.md").write_text("Synthetic source fixture")
        for name in (".harness", "worklogs"):
            directory = self.root / name
            directory.mkdir()
            (directory / "record.log").write_text("sk" + "-" + "A" * 40)
        report = self.root / "worklogs/checks"
        report.mkdir()
        with patch.object(checks, "ROOT", self.root), contextlib.redirect_stdout(io.StringIO()):
            checks.public_hygiene(report)
        result = json.loads((report / "hygiene.json").read_text())
        self.assertEqual(result["findings"], [])

    def test_current_and_legacy_records_are_excluded_from_docker_context(self):
        rules = set((ROOT / ".dockerignore").read_text().splitlines())
        self.assertTrue({"worklogs", ".harness"}.issubset(rules))
