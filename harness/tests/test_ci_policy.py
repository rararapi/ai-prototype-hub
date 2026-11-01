"""Guard CI coverage and event routing without adding YAML dependencies to self-tests."""

import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def section(document, name, indent):
    """Read a mapping block from this workflow's deliberately simple block YAML."""
    prefix = " " * indent
    match = re.search(rf"(?m)^{prefix}{re.escape(name)}:\n", document)
    if not match:
        raise AssertionError(f"Missing block: {name}")
    lines = []
    for line in document[match.end() :].splitlines():
        if line.strip() and not line.lstrip().startswith("#"):
            if len(line) - len(line.lstrip()) <= indent:
                break
        lines.append(line)
    return "\n".join(lines)


class CiPolicyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workflow = (ROOT / ".github/workflows/verify.yml").read_text()

    def test_events_avoid_branch_push_pr_duplicates_and_allow_manual_full(self):
        events = section(self.workflow, "on", 0)
        self.assertEqual(
            re.findall(r"(?m)^  ([a-z_]+):", events),
            ["pull_request", "push", "workflow_dispatch"],
        )
        self.assertEqual(section(events, "push", 2).strip(), "branches: [main]")
        # PRs must not silently lose coverage through path or branch filters.
        self.assertFalse(section(events, "pull_request", 2).strip())

    def test_pr_runs_portable_checks_without_cluster_setup(self):
        job = section(self.workflow, "devcontainer", 2)
        self.assertIn("if: github.event_name == 'pull_request'", job)
        self.assertIn("runCmd: make check-dev", job)
        self.assertNotIn("make verify", job)
        self.assertNotIn("kind.sigs.k8s.io", job)

    def test_main_and_manual_keep_real_full_verification(self):
        job = section(self.workflow, "verify", 2)
        self.assertIn(
            "if: github.event_name == 'push' || github.event_name == 'workflow_dispatch'",
            job,
        )
        self.assertIn("run: make verify", job)
        self.assertIn("sha256sum --check", job)
        self.assertIn("kind.sigs.k8s.io", job)
        self.assertIn("path: worklogs/reports/", job)
        self.assertNotIn("continue-on-error", self.workflow)

    def test_quick_and_full_remain_distinct_with_runtime_gates_required(self):
        manifest = json.loads((ROOT / "harness/gates.json").read_text())
        full = set(manifest["groups"]["full"])
        self.assertTrue({"integration", "e2e", "security", "doctor-kind"} <= full)
        self.assertTrue(
            {
                "harness-self",
                "public-hygiene",
                "source-host",
                "contracts-host",
                "unit-host",
                "build-host",
            }
            <= set(manifest["groups"]["dev"])
        )
        gates = {gate["id"]: gate for gate in manifest["gates"]}
        self.assertIn("doctor-compose", gates["doctor-kind"]["depends_on"])
        for gate in ("integration", "e2e", "security"):
            self.assertIn(f"scripts/checks/{gate}.sh", gates[gate]["argv"])

    def test_untrusted_pr_keeps_read_only_permissions_and_cancellation(self):
        self.assertEqual(section(self.workflow, "permissions", 0).strip(), "contents: read")
        concurrency = section(self.workflow, "concurrency", 0)
        self.assertIn("github.ref", concurrency)
        self.assertIn("cancel-in-progress: true", concurrency)
        self.assertNotIn("pull_request_target", self.workflow)


if __name__ == "__main__":
    unittest.main()
