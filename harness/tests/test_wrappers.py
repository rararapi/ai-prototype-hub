"""Gate failures may never masquerade as missing prerequisites."""

import importlib.util
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

spec = importlib.util.spec_from_file_location(
    "checks", Path(__file__).resolve().parents[2] / "scripts/checks/check.py"
)
checks = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checks)


class WrapperTests(unittest.TestCase):
    def test_cli_helpers_import_with_the_harness_interpreter(self):
        root = Path(__file__).resolve().parents[2]
        for path in ("scripts/local/manage.py", "scripts/checks/check.py"):
            result = subprocess.run(
                [sys.executable, str(root / path), "--help"],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_build_supplies_owner_and_repository_root_context(self):
        calls = []
        with (
            patch.object(checks, "docker_ready"),
            patch.object(
                checks,
                "child",
                side_effect=lambda argv, *args, **kwargs: calls.append((argv, kwargs)),
            ),
        ):
            checks.docker_gate("build", Path("/tmp/evidence"))
        compose = next(call for call in calls if call[0][:2] == ["docker", "compose"])
        self.assertTrue(compose[1]["env"]["PROTOHUB_OWNER_ID"])
        sample = next(call for call in calls if "examples/hello-web/Dockerfile" in call[0])
        self.assertEqual(sample[0][-1], ".")

    def test_child_exit_78_is_failure(self):
        with patch.object(
            checks.subprocess, "run", return_value=subprocess.CompletedProcess([], 78)
        ):
            with self.assertRaises(SystemExit) as result:
                checks.child(["test"])
            self.assertEqual(result.exception.code, 1)

    def test_assertion_failure_is_not_blocked(self):
        with (
            patch.object(checks, "evidence", return_value=Path("/tmp")),
            patch.object(checks, "public_hygiene", side_effect=AssertionError("bad")),
        ):
            self.assertEqual(checks.main(["public-hygiene"]), 1)

    def test_preflight_missing_is_blocked(self):
        with (
            patch.object(checks, "evidence", return_value=Path("/tmp")),
            patch.object(checks, "docker_ready", side_effect=checks.MissingPrerequisite("docker")),
        ):
            self.assertEqual(checks.main(["integration"]), 78)


if __name__ == "__main__":
    unittest.main()
