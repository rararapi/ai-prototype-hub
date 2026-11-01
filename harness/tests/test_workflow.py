"""Real temporary Git repositories exercise the development workflow guard."""

import importlib.util
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

SPEC = importlib.util.spec_from_file_location(
    "protohub_workflow", Path(__file__).resolve().parents[1] / "workflow.py"
)
workflow = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(workflow)


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="protohub-workflow-test-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.git("init", "--quiet")
        for path, content in {
            ".gitignore": "worklogs/\n.harness/\n",
            "allowed/app.txt": "base\n",
            "outside/user.txt": "existing\n",
            "forbidden/file.txt": "keep\n",
            "contracts/openapi.yaml": "{}\n",
        }.items():
            self.write(path, content)
        self.commit()

    def git(self, *args):
        result = subprocess.run(["git", *args], cwd=self.root, capture_output=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr.decode(errors="replace"))
        return result.stdout

    def commit(self):
        self.git("add", ".")
        self.git(
            "-c",
            "user.name=Workflow Test",
            "-c",
            "user.email=workflow@example.invalid",
            "commit",
            "--quiet",
            "-m",
            "Synthetic test fixture",
        )

    def write(self, path, content):
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return target

    def start(self, **kwargs):
        return workflow.start(
            self.root,
            "task",
            "Repair the allowed application",
            ["allowed/"],
            ["forbidden/"],
            ["unit"],
            **kwargs,
        )

    def report(self, state, **overrides):
        current = workflow.snapshot(self.root)
        report = {
            "status": "PASS",
            "complete": True,
            "interrupted": False,
            "started_at": workflow.now(),
            "finished_at": workflow.now(),
            "git_sha": current["head"],
            "git_dirty": current["dirty"],
            "git_snapshot": current,
            "git_snapshot_after": current,
            "gates": [
                {"id": gate, "status": "PASS", "returncode": 0} for gate in state["required_gates"]
            ],
        }
        report.update(overrides)
        path = self.write("worklogs/reports/run/report.json", json.dumps(report))
        return path.relative_to(self.root).as_posix(), report

    def review(self, **overrides):
        report = {
            "status": "PASS",
            "reviewer": "independent-reviewer",
            "independent": True,
            "blocking_findings": 0,
            "summary": "Reviewed scope, behavior and current checks",
            "completed_at": workflow.now(),
            "git_snapshot": workflow.snapshot(self.root),
        }
        report.update(overrides)
        path = self.write("worklogs/reviews/review.json", json.dumps(report))
        return path.relative_to(self.root).as_posix()

    def test_persisted_objective_ownership_and_baseline(self):
        state = self.start()
        stored = workflow.load(self.root, "task")
        self.assertEqual(stored["objective"], state["objective"])
        self.assertEqual(stored["owners"], {"allowed/": "coordinator"})
        self.assertFalse(stored["baseline"]["dirty"])
        self.assertEqual(workflow.check(self.root, state)["status"], "PASS")

    def test_task_ids_and_scope_traversal_are_rejected_without_overwrite(self):
        for path in ("../outside", "/absolute", "C:/drive", "allowed/../outside", "a\\b", "a/**"):
            with self.subTest(path=path), self.assertRaises(workflow.WorkflowError):
                workflow.scope_path(path)
        for name in ("../outside", "A", "a/b", "", "x" * 65):
            with self.subTest(name=name), self.assertRaises(workflow.WorkflowError):
                workflow.start(self.root, name, "Goal", ["allowed/"], [], ["unit"])
        original = self.start()
        with self.assertRaises(workflow.WorkflowError):
            self.start()
        self.assertEqual(workflow.load(self.root, "task"), original)

    def test_untracked_and_forbidden_changes_are_in_scope_checks(self):
        state = self.start()
        self.write("allowed/new file.txt", "new\n")
        self.assertEqual(workflow.check(self.root, state)["status"], "PASS")
        self.write("outside/new file.txt", "outside\n")
        self.write("forbidden/file.txt", "changed\n")
        result = workflow.check(self.root, state)
        self.assertEqual(result["status"], "FAIL")
        self.assertEqual(
            {item["path"] for item in result["violations"]},
            {"outside/new file.txt", "forbidden/file.txt"},
        )

    def test_rename_checks_both_original_and_destination(self):
        state = self.start()
        self.git("mv", "outside/user.txt", "allowed/moved.txt")
        result = workflow.check(self.root, state)
        self.assertIn("outside/user.txt", [item["path"] for item in result["violations"]])
        self.assertIn("allowed/moved.txt", result["changed_paths"])

    def test_committed_rename_and_changes_remain_bounded_by_starting_head(self):
        state = self.start()
        self.git("mv", "allowed/app.txt", "outside/moved.txt")
        self.commit()
        result = workflow.check(self.root, state)
        self.assertIn("outside/moved.txt", [item["path"] for item in result["violations"]])
        self.assertIn("allowed/app.txt", result["changed_paths"])

    def test_existing_dirty_user_changes_are_preserved_and_overwrites_detected(self):
        self.write("outside/user.txt", "preexisting user changes\n")
        state = self.start()
        result = workflow.check(self.root, state)
        self.assertEqual(result["status"], "PASS")
        self.assertIn("outside/user.txt", result["preserved_baseline_paths"])
        self.write("outside/user.txt", "existing\n")
        result = workflow.check(self.root, state)
        self.assertEqual(result["status"], "FAIL")
        self.assertIn("outside/user.txt", [item["path"] for item in result["violations"]])

    def test_contract_change_requires_decision_for_that_exact_content(self):
        state = workflow.start(
            self.root,
            "task",
            "Update the contract",
            ["contracts/"],
            [],
            ["contracts"],
            contracts=["contracts/openapi.yaml"],
        )
        self.write("contracts/openapi.yaml", '{"version": 2}\n')
        self.assertEqual(workflow.check(self.root, state)["status"], "FAIL")
        workflow.note(
            self.root, state, "contract", "Updated agreed response type", ["contracts/openapi.yaml"]
        )
        self.assertEqual(workflow.check(self.root, state)["status"], "PASS")
        self.write("contracts/openapi.yaml", '{"version": 3}\n')
        self.assertEqual(workflow.check(self.root, state)["status"], "FAIL")

    def test_overlapping_ownership_is_rejected(self):
        with self.assertRaises(workflow.WorkflowError):
            workflow.start(self.root, "task", "Goal", ["allowed/", "allowed/app.txt"], [], ["unit"])

    def test_repair_attempts_are_bounded_and_record_cause_and_next_check(self):
        state = self.start(max_repairs=2)
        workflow.repair(state, "Observed failing test", "Fix the parser", "unit")
        workflow.repair(state, "Same test still fails", "Correct rename handling", "unit")
        with self.assertRaises(workflow.WorkflowError):
            workflow.repair(state, "Still failing", "Retry without diagnosis", "unit")
        self.assertEqual(len(state["repairs"]), 2)
        self.assertEqual(state["repairs"][1]["next_check"], "unit")

    def test_repair_budget_is_an_explicit_bounded_integer(self):
        for budget in (0, -1, 11, True, 2.5):
            with self.subTest(budget=budget), self.assertRaises(workflow.WorkflowError):
                self.start(max_repairs=budget)

    def test_finish_requires_gates_and_independent_review(self):
        state = self.start()
        with self.assertRaises(workflow.WorkflowError):
            workflow.finish(self.root, state)
        source, _ = self.report(state)
        workflow.record(self.root, state, "gates", source)
        with self.assertRaises(workflow.WorkflowError):
            workflow.finish(self.root, state)
        workflow.record(self.root, state, "review", self.review())
        self.assertEqual(workflow.finish(self.root, state)["status"], "PASS")

    def test_nonpass_missing_and_skipped_required_gate_cannot_finish(self):
        state = self.start()
        for status in ("FAIL", "BLOCKED", "SKIP", "NOT_RUN"):
            with self.subTest(status=status):
                source, _ = self.report(
                    state, gates=[{"id": "unit", "status": status, "returncode": 0}]
                )
                with self.assertRaises(workflow.WorkflowError):
                    workflow.record(self.root, state, "gates", source)
        for change in (
            {"gates": []},
            {"status": "BLOCKED"},
            {"complete": False},
            {"interrupted": True},
        ):
            source, _ = self.report(state, **change)
            with self.assertRaises(workflow.WorkflowError):
                workflow.record(self.root, state, "gates", source)

    def test_dirty_bool_alone_and_changed_content_on_same_dirty_state_are_rejected(self):
        state = self.start()
        self.write("allowed/app.txt", "first change\n")
        source, report = self.report(state)
        workflow.record(self.root, state, "gates", source)
        workflow.record(self.root, state, "review", self.review())
        self.write("allowed/app.txt", "second change\n")
        self.assertTrue(workflow.snapshot(self.root)["dirty"])
        with self.assertRaises(workflow.WorkflowError):
            workflow.finish(self.root, state)
        report.pop("git_snapshot")
        self.write(source, json.dumps(report))
        with self.assertRaises(workflow.WorkflowError):
            workflow.record(self.root, state, "gates", source)

    def test_staged_and_untracked_content_affect_snapshot(self):
        clean = workflow.snapshot(self.root)
        self.write("allowed/app.txt", "staged\n")
        self.git("add", "allowed/app.txt")
        staged = workflow.snapshot(self.root)
        self.write("allowed/app.txt", "base\n")
        restored_worktree = workflow.snapshot(self.root)
        self.assertNotEqual(clean["fingerprint"], restored_worktree["fingerprint"])
        self.assertNotEqual(staged["fingerprint"], restored_worktree["fingerprint"])
        self.write("allowed/new.txt", "first\n")
        first = workflow.snapshot(self.root)
        self.write("allowed/new.txt", "second\n")
        self.assertNotEqual(first["fingerprint"], workflow.snapshot(self.root)["fingerprint"])

    def test_head_change_and_gate_mutation_are_rejected(self):
        state = self.start()
        source, report = self.report(state)
        workflow.record(self.root, state, "gates", source)
        workflow.record(self.root, state, "review", self.review())
        report["extra"] = "Changed after attachment"
        self.write(source, json.dumps(report))
        with self.assertRaises(workflow.WorkflowError):
            workflow.finish(self.root, state)
        self.write("allowed/app.txt", "committed\n")
        self.commit()
        with self.assertRaises(workflow.WorkflowError):
            workflow.record(self.root, state, "gates", source)

    def test_ignored_evidence_never_changes_source_snapshot(self):
        state = self.start()
        first = workflow.snapshot(self.root)
        self.report(state)
        self.review()
        self.assertEqual(first["fingerprint"], workflow.snapshot(self.root)["fingerprint"])

    def test_changes_during_gates_and_preworkflow_evidence_are_rejected(self):
        state = self.start()
        source, report = self.report(state)
        report["git_snapshot_after"] = {**report["git_snapshot"], "fingerprint": "different"}
        self.write(source, json.dumps(report))
        with self.assertRaises(workflow.WorkflowError):
            workflow.record(self.root, state, "gates", source)
        source, _ = self.report(state, started_at="2000-01-01T00:00:00Z")
        with self.assertRaises(workflow.WorkflowError):
            workflow.record(self.root, state, "gates", source)
        source, _ = self.report(state, finished_at=None)
        with self.assertRaises(workflow.WorkflowError):
            workflow.record(self.root, state, "gates", source)

    def test_review_must_be_independent_current_and_without_blocking_findings(self):
        state = self.start()
        for change in (
            {"independent": False},
            {"blocking_findings": 1},
            {"blocking_findings": False},
            {"status": "BLOCKED"},
            {"completed_at": "2000-01-01T00:00:00Z"},
            {"git_snapshot": None},
        ):
            with self.subTest(change=change), self.assertRaises(workflow.WorkflowError):
                workflow.record(self.root, state, "review", self.review(**change))

    def test_cli_finish_persists_and_refuses_rewriting_finished_task(self):
        self.assertEqual(
            workflow.main(
                [
                    "--root",
                    str(self.root),
                    "start",
                    "--id",
                    "task",
                    "--objective",
                    "Work on app",
                    "--allow",
                    "allowed/",
                    "--required-gate",
                    "unit",
                ]
            ),
            0,
        )
        state = workflow.load(self.root, "task")
        source, _ = self.report(state)
        self.assertEqual(
            workflow.main(
                ["--root", str(self.root), "record-gates", "--id", "task", "--file", source]
            ),
            0,
        )
        self.assertEqual(
            workflow.main(
                ["--root", str(self.root), "record-review", "--id", "task", "--file", self.review()]
            ),
            0,
        )
        self.assertEqual(workflow.main(["--root", str(self.root), "finish", "--id", "task"]), 0)
        self.assertEqual(workflow.load(self.root, "task")["status"], "finished")
        self.assertEqual(
            workflow.main(
                [
                    "--root",
                    str(self.root),
                    "repair",
                    "--id",
                    "task",
                    "--cause",
                    "Failure",
                    "--action",
                    "Fix",
                    "--next-check",
                    "unit",
                ]
            ),
            1,
        )

    @unittest.skipIf(os.name == "nt", "Windows symlink creation depends on OS permission")
    def test_evidence_and_changed_parent_symlink_escape_are_rejected(self):
        state = self.start()
        with tempfile.TemporaryDirectory(prefix="protohub-workflow-outside-") as temporary:
            outside = Path(temporary)
            (outside / "record.json").write_text("{}")
            (self.root / "worklogs/escape").symlink_to(outside, target_is_directory=True)
            with self.assertRaises(workflow.WorkflowError):
                workflow.record(self.root, state, "gates", "worklogs/escape/record.json")

    def test_load_migrates_legacy_workflow_without_rewriting_record(self):
        self.start()
        record = self.root / "worklogs/workflows/task/workflow.json"
        original = record.read_bytes()
        (self.root / "worklogs").rename(self.root / ".harness")
        loaded = workflow.load(self.root, "task")
        self.assertEqual(loaded["id"], "task")
        self.assertEqual(record.read_bytes(), original)
        self.assertFalse((self.root / ".harness").exists())

    def test_unignored_destination_refuses_before_migrating_legacy_records(self):
        self.write(".gitignore", ".harness/\n")
        self.commit()
        owner = self.write(".harness/local/owner.json", "original-owner")
        with self.assertRaisesRegex(workflow.WorkflowError, "ignore"):
            self.start()
        self.assertEqual(owner.read_text(), "original-owner")
        self.assertFalse((self.root / "worklogs").exists())

    def test_source_snapshot_excludes_current_and_legacy_generated_records(self):
        before = workflow.snapshot(self.root)
        self.write("worklogs/private.log", "synthetic-work-record")
        self.write(".harness/private.log", "synthetic-legacy-record")
        after = workflow.snapshot(self.root)
        self.assertEqual(before["fingerprint"], after["fingerprint"])
        self.assertFalse(after["dirty"])


if __name__ == "__main__":
    unittest.main()
