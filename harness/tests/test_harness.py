"""Stdlib self-tests. Run: python3 -m unittest discover -s harness/tests -v."""

import importlib.util
import io
import json
import os
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

SPEC = importlib.util.spec_from_file_location(
    "protohub_harness", Path(__file__).resolve().parents[1] / "run.py"
)
harness = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(harness)
DOCTOR_SPEC = importlib.util.spec_from_file_location(
    "protohub_doctor", Path(__file__).resolve().parents[1] / "doctor.py"
)
doctor = importlib.util.module_from_spec(DOCTOR_SPEC)
DOCTOR_SPEC.loader.exec_module(doctor)


class HarnessTests(unittest.TestCase):
    def test_source_changes_cannot_pass_while_dirty_stays_true(self):
        (self.root / ".gitignore").write_text(".harness/\n", encoding="utf-8")
        (self.root / "owned.txt").write_text("before", encoding="utf-8")
        for argv in (
            ["git", "init", "-q"],
            ["git", "add", ".gitignore", "owned.txt"],
            [
                "git",
                "-c",
                "user.name=Fixture",
                "-c",
                "user.email=fixture@example.invalid",
                "commit",
                "-qm",
                "fixture",
            ],
        ):
            subprocess.run(argv, cwd=self.root, capture_output=True, check=True)
        result = self.run_gates(
            [self.gate(code="from pathlib import Path; Path('owned.txt').write_text('after')")]
        )
        self.assertEqual(result["gates"][0]["status"], "PASS")
        self.assertEqual(result["status"], "FAIL")
        self.assertTrue(result["git_snapshot"]["dirty"])
        self.assertTrue(result["git_snapshot_after"]["dirty"])
        self.assertNotEqual(
            result["git_snapshot"]["fingerprint"], result["git_snapshot_after"]["fingerprint"]
        )

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="protohub-harness-test-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def gate(self, gate_id="check", code="print('ok')", **overrides):
        gate = {
            "id": gate_id,
            "argv": [sys.executable, "-c", code],
            "cwd": ".",
            "timeout_seconds": 5,
            "required_paths": [],
            "depends_on": [],
        }
        gate.update(overrides)
        return gate

    def run_gates(self, gates, group_ids=None):
        manifest = {
            "schema_version": 1,
            "groups": {"quick": group_ids or [gate["id"] for gate in gates]},
            "gates": gates,
        }
        (self.root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        return harness.run(self.root, "quick", "manifest.json")

    def test_success_and_private_report(self):
        result = self.run_gates([self.gate()])
        self.assertEqual(result["status"], "PASS")
        report = Path(result["report_path"])
        self.assertTrue(report.is_file())
        self.assertEqual(report.stat().st_mode & 0o077, 0)
        self.assertEqual(report.parent.stat().st_mode & 0o077, 0)
        self.assertEqual(result["gates"][0]["returncode"], 0)

    def test_nonzero_exit_fails(self):
        result = self.run_gates([self.gate(code="raise SystemExit(7)")])
        self.assertEqual(result["status"], "FAIL")
        self.assertEqual(result["gates"][0]["returncode"], 7)

    def test_exit_two_is_failure_unless_explicitly_declared(self):
        result = self.run_gates([self.gate(code="raise SystemExit(2)")])
        self.assertEqual(result["status"], "FAIL")
        result = self.run_gates([self.gate(code="raise SystemExit(2)", blocked_exit_codes=[2])])
        self.assertEqual(result["status"], "BLOCKED")
        self.assertEqual(result["gates"][0]["returncode"], 2)

    def test_declared_blocked_status_propagates_to_dependencies(self):
        result = self.run_gates(
            [
                self.gate("prerequisite", code="raise SystemExit(78)", blocked_exit_codes=[78]),
                self.gate(
                    "dependent",
                    code="raise RuntimeError('must not run')",
                    depends_on=["prerequisite"],
                ),
            ]
        )
        self.assertEqual([gate["status"] for gate in result["gates"]], ["BLOCKED", "BLOCKED"])
        self.assertIsNone(result["gates"][1]["returncode"])

    def test_blocked_exit_codes_schema_is_strict(self):
        for codes in (2, None, [True], [0], [-1], [256], [2, 2], ["2"], [2.0]):
            with self.subTest(codes=codes):
                result = self.run_gates([self.gate(blocked_exit_codes=codes)])
                self.assertEqual(result["gates"][0]["id"], "manifest")
                self.assertEqual(result["status"], "BLOCKED")

    def test_missing_required_path_is_blocked(self):
        result = self.run_gates([self.gate(required_paths=["tests/not-created-yet.py"])])
        self.assertEqual(result["status"], "BLOCKED")
        self.assertIsNone(result["gates"][0]["returncode"])

    def test_missing_command_is_blocked(self):
        result = self.run_gates([self.gate(argv=["protohub-definitely-missing-executable-48c3"])])
        self.assertEqual(result["status"], "BLOCKED")

    def test_missing_working_directory_is_blocked(self):
        result = self.run_gates([self.gate(cwd="missing-directory")])
        self.assertEqual(result["status"], "BLOCKED")

    def test_dependency_failure_blocks_without_running(self):
        result = self.run_gates(
            [
                self.gate("first", code="raise SystemExit(1)"),
                self.gate(
                    "second",
                    code="from pathlib import Path; Path('must-not-exist').touch()",
                    depends_on=["first"],
                ),
            ]
        )
        self.assertEqual([item["status"] for item in result["gates"]], ["FAIL", "BLOCKED"])
        self.assertFalse((self.root / "must-not-exist").exists())

    def test_dependencies_are_added_in_order(self):
        result = self.run_gates(
            [self.gate("dependent", depends_on=["base"]), self.gate("base")],
            ["dependent"],
        )
        self.assertEqual([item["id"] for item in result["gates"]], ["base", "dependent"])
        self.assertEqual(result["status"], "PASS")

    def test_timeout_fails(self):
        started = time.monotonic()
        result = self.run_gates(
            [self.gate(code="import time; time.sleep(10)", timeout_seconds=0.05)]
        )
        self.assertEqual(result["status"], "FAIL")
        self.assertIn("Time limit", result["gates"][0]["reason"])
        self.assertLess(time.monotonic() - started, 4)

    def test_timeout_terminates_descendant_group(self):
        child = (
            "import time; from pathlib import Path; time.sleep(0.4); Path('escaped-child').touch()"
        )
        parent = (
            "import subprocess, sys, time; subprocess.Popen([sys.executable, '-c', "
            + repr(child)
            + "]); time.sleep(10)"
        )
        result = self.run_gates([self.gate(code=parent, timeout_seconds=0.08)])
        self.assertEqual(result["status"], "FAIL")
        time.sleep(0.5)
        self.assertFalse((self.root / "escaped-child").exists())

    def test_cleanup_grace_schema_is_strict(self):
        for seconds in (None, True, "1", 0, -1, 0.09, 60.1, float("nan")):
            with self.subTest(seconds=seconds):
                result = self.run_gates([self.gate(cleanup_grace_seconds=seconds)])
                self.assertEqual(result["status"], "BLOCKED")
                self.assertEqual(result["gates"][0]["id"], "manifest")

    def slow_fixture_wrapper(self):
        # The wrapper dies promptly, while its descendant removes an external
        # resource. Waiting only for the wrapper would kill that cleanup too early.
        child = "\n".join(
            [
                "import signal, time",
                "from pathlib import Path",
                "def cleanup(signum, frame):",
                "    time.sleep(0.35)",
                "    Path('external-resource').unlink()",
                "    Path('fixture-cleaned').touch()",
                "    raise SystemExit(0)",
                "signal.signal(signal.SIGTERM, cleanup)",
                "Path('external-resource').touch()",
                "Path('fixture-ready').touch()",
                "time.sleep(30)",
            ]
        )
        return "\n".join(
            [
                "import signal, subprocess, sys, time",
                "signal.signal(signal.SIGTERM, lambda *args: sys.exit(0))",
                f"subprocess.Popen([sys.executable, '-c', {child!r}])",
                "time.sleep(30)",
            ]
        )

    def test_timeout_allows_descendant_fixture_cleanup_after_wrapper_exits(self):
        result = self.run_gates(
            [
                self.gate(
                    code=self.slow_fixture_wrapper(),
                    timeout_seconds=0.6,
                    cleanup_grace_seconds=1.5,
                )
            ]
        )
        self.assertTrue((self.root / "fixture-ready").exists(), "fixture did not start")
        self.assertTrue((self.root / "fixture-cleaned").exists(), "cleanup was killed too soon")
        self.assertFalse((self.root / "external-resource").exists())
        self.assertEqual(result["status"], "FAIL")
        self.assertIn("Time limit", result["gates"][0]["reason"])

    def test_integration_sigterm_cleans_only_its_owned_external_fixture(self):
        fake_bin = self.root / "bin"
        fake_bin.mkdir()
        report = self.root / "integration-evidence"
        report.mkdir()
        resource = self.root / "external-compose-resource"
        ready = self.root / "compose-ready"
        cleaned = self.root / "compose-cleaned"
        fake_docker = fake_bin / "docker"
        fake_docker.write_text(
            "\n".join(
                [
                    f"#!{sys.executable}",
                    "import json, os, sys, time",
                    "from pathlib import Path",
                    "argv = sys.argv[1:]",
                    "resource = Path(os.environ['FIXTURE_EXTERNAL_RESOURCE'])",
                    "if argv[:2] == ['ps', '-aq']:",
                    "    raise SystemExit(0)",
                    "if not argv or argv[0] != 'compose':",
                    "    raise SystemExit(2)",
                    "project = argv[argv.index('-p') + 1]",
                    "if 'up' in argv:",
                    "    resource.write_text(project)",
                    "    Path(os.environ['FIXTURE_READY']).touch()",
                    "    time.sleep(30)",
                    "elif 'down' in argv:",
                    "    assert resource.read_text() == project",
                    "    time.sleep(0.35)",
                    "    resource.unlink()",
                    "    Path(os.environ['FIXTURE_CLEANED']).write_text(project)",
                    "else:",
                    "    raise SystemExit(2)",
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        fake_docker.chmod(0o755)
        script = Path(harness.__file__).resolve().parents[1] / "tests/integration/run.py"
        with mock.patch.dict(
            os.environ,
            {
                "PATH": str(fake_bin) + os.pathsep + os.environ.get("PATH", ""),
                "FIXTURE_EXTERNAL_RESOURCE": str(resource),
                "FIXTURE_READY": str(ready),
                "FIXTURE_CLEANED": str(cleaned),
            },
        ):
            result = self.run_gates(
                [
                    self.gate(
                        argv=[
                            sys.executable,
                            str(script),
                            "--gate",
                            "integration",
                            "--report",
                            str(report),
                        ],
                        timeout_seconds=0.8,
                        cleanup_grace_seconds=1.5,
                    )
                ]
            )
        self.assertTrue(ready.exists(), "integration fixture did not start")
        self.assertTrue(cleaned.exists(), "integration finally cleanup did not finish")
        self.assertFalse(resource.exists())
        identity = json.loads((report / "fixture.json").read_text(encoding="utf-8"))
        self.assertEqual(cleaned.read_text(), identity["project"])
        self.assertEqual(result["status"], "FAIL")
        self.assertIn("Time limit", result["gates"][0]["reason"])

    def test_interrupt_allows_descendant_fixture_cleanup_after_wrapper_exits(self):
        manifest = {
            "schema_version": 1,
            "groups": {"quick": ["fixture"]},
            "gates": [
                self.gate(
                    "fixture",
                    code=self.slow_fixture_wrapper(),
                    timeout_seconds=10,
                    cleanup_grace_seconds=1.5,
                ),
            ],
        }
        (self.root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        code = (
            "import sys; from pathlib import Path; sys.path.insert(0, "
            + repr(str(Path(harness.__file__).parent))
            + "); import run; report=run.run(Path("
            + repr(str(self.root))
            + "), 'quick', 'manifest.json'); raise SystemExit(0 if report['status']=='PASS' else 1)"
        )
        process = subprocess.Popen(
            [sys.executable, "-c", code],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        try:
            deadline = time.monotonic() + 4
            while not (self.root / "fixture-ready").exists() and time.monotonic() < deadline:
                self.assertIsNone(process.poll(), "runner exited before fixture startup")
                time.sleep(0.02)
            self.assertTrue((self.root / "fixture-ready").exists())
            process.send_signal(signal.SIGTERM)
            process.communicate(timeout=5)
            self.assertNotEqual(process.returncode, 0)
            self.assertTrue((self.root / "fixture-cleaned").exists())
            self.assertFalse((self.root / "external-resource").exists())
            paths = list((self.root / ".harness/reports").glob("*/report.json"))
            self.assertEqual(len(paths), 1)
            result = json.loads(paths[0].read_text(encoding="utf-8"))
            self.assertTrue(result["interrupted"])
            self.assertFalse(result["complete"])
            self.assertEqual(result["status"], "FAIL")
        finally:
            if process.poll() is None:
                process.kill()
            process.wait(timeout=2)
            process.stdout.close()

    def test_cwd_and_required_path_escape_are_rejected(self):
        for override in (
            {"cwd": "../outside"},
            {"required_paths": ["../outside"]},
            {"cwd": "/tmp"},
        ):
            with self.subTest(override=override):
                result = self.run_gates([self.gate(**override)])
                self.assertEqual(result["status"], "BLOCKED")
                self.assertEqual(result["gates"][0]["id"], "manifest")

    def test_manifest_escape_is_rejected(self):
        result = harness.run(self.root, "quick", "../outside.json")
        self.assertEqual(result["status"], "BLOCKED")

    def test_symlink_escape_is_rejected(self):
        (self.root / "outside").symlink_to(self.root.parent, target_is_directory=True)
        result = self.run_gates([self.gate(cwd="outside")])
        self.assertEqual(result["status"], "BLOCKED")

    def test_invalid_json_is_blocked(self):
        (self.root / "manifest.json").write_text("not JSON", encoding="utf-8")
        result = harness.run(self.root, "quick", "manifest.json")
        self.assertEqual(result["status"], "BLOCKED")

    def test_invalid_schema_is_blocked(self):
        invalid = [
            {
                "schema_version": 2,
                "groups": {"quick": ["check"]},
                "gates": [self.gate()],
            },
            {
                "schema_version": True,
                "groups": {"quick": ["check"]},
                "gates": [self.gate()],
            },
            {"schema_version": 1, "groups": {"quick": []}, "gates": []},
            {
                "schema_version": 1,
                "groups": {"quick": ["check"]},
                "gates": [self.gate(argv="echo ok")],
            },
            {
                "schema_version": 1,
                "groups": {"quick": ["check"]},
                "gates": [self.gate(timeout_seconds=True)],
            },
            {
                "schema_version": 1,
                "groups": {"quick": ["check"]},
                "gates": [self.gate(), self.gate()],
            },
        ]
        for manifest in invalid:
            with self.subTest(manifest=manifest):
                (self.root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
                result = harness.run(self.root, "quick", "manifest.json")
                self.assertEqual(result["status"], "BLOCKED")

    def test_cycle_and_unknown_dependency_are_blocked(self):
        for gates in (
            [self.gate(depends_on=["missing"])],
            [
                self.gate("first", depends_on=["second"]),
                self.gate("second", depends_on=["first"]),
            ],
        ):
            with self.subTest(gates=gates):
                result = self.run_gates(gates)
                self.assertEqual(result["status"], "BLOCKED")

    def test_secret_values_are_redacted(self):
        secret = "protohub-test-sensitive-value-91a"
        with mock.patch.dict(os.environ, {"PROTOHUB_TEST_TOKEN": secret}):
            result = self.run_gates(
                [self.gate(code="import os; print(os.environ['PROTOHUB_TEST_TOKEN'])")]
            )
        log = Path(result["report_path"]).parent / result["gates"][0]["log"]
        self.assertNotIn(secret, log.read_text(encoding="utf-8"))
        self.assertIn("[REDACTED]", log.read_text(encoding="utf-8"))

    def test_capture_stays_bounded_and_drains_large_output(self):
        capture = harness.BoundedCapture(limit=64)
        for _ in range(100):
            capture.add(b"x" * 4096)
        self.assertEqual(len(capture.data), 64)
        self.assertTrue(capture.truncated)
        # This patch also guards git metadata: no subprocess output is read
        # through communicate(), which would allocate the entire output.
        with mock.patch.object(
            subprocess.Popen,
            "communicate",
            side_effect=AssertionError("unbounded capture"),
        ):
            result = self.run_gates(
                [
                    self.gate(
                        code="import os; [os.write(1, b'x' * 65535 + b'\\n') for _ in range(96)]; print('drained')"
                    )
                ]
            )
        self.assertEqual(result["status"], "PASS")
        self.assertTrue(result["gates"][0]["output_truncated"])
        report_dir = Path(result["report_path"]).parent
        log = report_dir / result["gates"][0]["log"]
        self.assertLessEqual(log.stat().st_size, harness.MAX_LOG_BYTES + 100)
        self.assertIn("LOG TRUNCATED", log.read_text(encoding="utf-8"))
        self.assertEqual({path.name for path in report_dir.iterdir()}, {"check.log", "report.json"})

    def test_incomplete_secret_line_is_not_saved_after_truncation(self):
        capture = harness.BoundedCapture(limit=16)
        capture.add(b"ok\npassword=secret-that-exceeds-the-limit")
        self.assertEqual(capture.safe_log(), "ok\n\n[LOG TRUNCATED; output was drained]\n")
        self.assertNotIn(
            "private-bytes",
            harness.redact("-----BEGIN PRIVATE KEY-----\nprivate-bytes"),
        )

    def test_gate_receives_actual_run_evidence_directory(self):
        code = "import os, json; from pathlib import Path; root=Path(os.environ['PROTOHUB_HARNESS_REPORT_DIR']); assert root.is_absolute(); (root/'evidence.json').write_text(json.dumps({key:os.environ[key] for key in ['PROTOHUB_HARNESS_GATE_ID','PROTOHUB_HARNESS_RUN_ID']}))"
        with mock.patch.dict(
            os.environ,
            {
                "PROTOHUB_HARNESS_REPORT_DIR": "/untrusted-directory",
                "PROTOHUB_HARNESS_GATE_ID": "untrusted-gate",
                "PROTOHUB_HARNESS_RUN_ID": "untrusted-run",
            },
        ):
            result = self.run_gates([self.gate("actual-gate", code=code)])
        self.assertEqual(result["status"], "PASS")
        report_dir = Path(result["report_path"]).parent
        evidence = json.loads((report_dir / "evidence.json").read_text(encoding="utf-8"))
        self.assertEqual(evidence["PROTOHUB_HARNESS_GATE_ID"], "actual-gate")
        self.assertEqual(evidence["PROTOHUB_HARNESS_RUN_ID"], report_dir.name)

    def check_signal_interrupt(self, signum):
        child = "import signal, time; from pathlib import Path; signal.signal(signal.SIGTERM, signal.SIG_IGN); Path('ready').touch(); time.sleep(1.0); Path('survived').touch()"
        parent = (
            "import os, subprocess, sys, time; from pathlib import Path; Path('gate-pid').write_text(str(os.getpid())); subprocess.Popen([sys.executable, '-c', "
            + repr(child)
            + "]); time.sleep(30)"
        )
        gates = [
            self.gate("running", code=parent, timeout_seconds=10),
            self.gate("later", code="from pathlib import Path; Path('later-ran').touch()"),
        ]
        manifest = {
            "schema_version": 1,
            "groups": {"quick": [gate["id"] for gate in gates]},
            "gates": gates,
        }
        (self.root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        code = (
            "import sys; from pathlib import Path; sys.path.insert(0, "
            + repr(str(Path(harness.__file__).parent))
            + "); import run; report=run.run(Path("
            + repr(str(self.root))
            + "), 'quick', 'manifest.json'); raise SystemExit(0 if report['status']=='PASS' else 1)"
        )
        process = subprocess.Popen(
            [sys.executable, "-c", code],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        try:
            deadline = time.monotonic() + 4
            while (
                not (self.root / "ready").exists()
                and process.poll() is None
                and time.monotonic() < deadline
            ):
                time.sleep(0.02)
            self.assertTrue((self.root / "ready").exists(), "gate did not start in time")
            process.send_signal(signum)
            output, _ = process.communicate(timeout=5)
            self.assertNotEqual(process.returncode, 0, output.decode(errors="replace"))
            reports = list((self.root / ".harness" / "reports").glob("*/report.json"))
            self.assertEqual(len(reports), 1)
            result = json.loads(reports[0].read_text(encoding="utf-8"))
            self.assertEqual(result["status"], "FAIL")
            self.assertTrue(result["interrupted"])
            self.assertFalse(result["complete"])
            self.assertEqual(result["interrupted_by"], signal.Signals(signum).name)
            self.assertEqual([gate["status"] for gate in result["gates"]], ["FAIL", "BLOCKED"])
            self.assertFalse((self.root / "later-ran").exists())
            time.sleep(1.1)
            self.assertFalse(
                (self.root / "survived").exists(),
                "a TERM-resistant descendant survived",
            )
        finally:
            if process.poll() is None:
                process.kill()
            process.wait(timeout=2)
            process.stdout.close()
            pid_file = self.root / "gate-pid"
            if pid_file.exists():
                try:
                    os.killpg(int(pid_file.read_text(encoding="utf-8")), signal.SIGKILL)
                except ProcessLookupError:
                    pass

    def test_sigint_records_incomplete_report_and_stops_process_group(self):
        self.check_signal_interrupt(signal.SIGINT)

    def test_sigterm_records_incomplete_report_and_stops_process_group(self):
        self.check_signal_interrupt(signal.SIGTERM)

    def test_command_arguments_are_not_shell_interpreted(self):
        result = self.run_gates(
            [
                self.gate(
                    argv=[
                        sys.executable,
                        "-c",
                        "import sys; print(sys.argv[1])",
                        "$(touch should-not-exist)",
                    ]
                )
            ]
        )
        self.assertEqual(result["status"], "PASS")
        self.assertFalse((self.root / "should-not-exist").exists())


class DoctorTests(unittest.TestCase):
    def call_doctor(
        self,
        environment=None,
        endpoint="unix:///var/run/docker.sock",
        inspect_fails=False,
        server="linux",
        cgroup="2",
        missing_docker=False,
        mode="compose",
        operation="start",
    ):
        commands = []

        def fake_run(argv, **kwargs):
            commands.append(argv)
            stdout, returncode = "version", 0
            if argv[:3] == ["docker", "context", "show"]:
                stdout = "saved-context\n"
            elif argv[:3] == ["docker", "context", "inspect"]:
                stdout, returncode = json.dumps(endpoint), int(inspect_fails)
            elif argv[:2] == ["docker", "info"]:
                stdout = cgroup if argv[-1] == "{{.CgroupVersion}}" else server
            return subprocess.CompletedProcess(argv, returncode, stdout, "")

        output = io.StringIO()
        with (
            mock.patch.dict(os.environ, environment or {}, clear=True),
            mock.patch.object(doctor.platform, "system", return_value="Linux"),
            mock.patch.object(doctor.platform, "release", return_value="test-kernel"),
            mock.patch.object(
                doctor.shutil,
                "which",
                side_effect=lambda name: (
                    None if missing_docker and name == "docker" else "/test/" + name
                ),
            ),
            mock.patch.object(doctor.subprocess, "run", side_effect=fake_run),
            mock.patch("sys.stdout", output),
        ):
            code = doctor.main(["--mode", mode, "--operation", operation])
        return code, output.getvalue(), commands

    def test_saved_context_with_local_socket_passes_without_context_mutation(self):
        code, output, commands = self.call_doctor()
        self.assertEqual(code, 0)
        self.assertTrue(any(command[:2] == ["docker", "info"] for command in commands))
        self.assertFalse(any(command[:3] == ["docker", "context", "use"] for command in commands))
        self.assertNotIn("/var/run/docker.sock", output)
        self.assertNotIn("saved-context", output)

    def test_remote_docker_host_is_blocked_without_server_contact(self):
        for endpoint in (
            "ssh://user:credential@remote.example",
            "tcp://localhost:2375",
        ):
            with self.subTest(endpoint=endpoint):
                code, output, commands = self.call_doctor({"DOCKER_HOST": endpoint})
                self.assertEqual(code, 2)
                self.assertFalse(any(command[:2] == ["docker", "info"] for command in commands))
                self.assertNotIn(endpoint, output)
                self.assertNotIn("credential", output)

    def test_docker_context_overrides_docker_host(self):
        code, output, commands = self.call_doctor(
            {"DOCKER_CONTEXT": "chosen-local", "DOCKER_HOST": "ssh://remote.example"}
        )
        self.assertEqual(code, 0)
        self.assertTrue(
            any(
                command[:3] == ["docker", "context", "inspect"] and command[-1] == "chosen-local"
                for command in commands
            )
        )
        self.assertNotIn("chosen-local", output)

    def test_remote_context_is_not_overridden_by_local_docker_host(self):
        code, _, commands = self.call_doctor(
            {"DOCKER_CONTEXT": "remote", "DOCKER_HOST": "unix:///var/run/docker.sock"},
            endpoint="ssh://remote.example",
        )
        self.assertEqual(code, 2)
        self.assertFalse(any(command[:2] == ["docker", "info"] for command in commands))

    def test_docker_host_overrides_saved_context(self):
        code, _, commands = self.call_doctor(
            {"DOCKER_HOST": "unix:///run/user/1000/docker.sock"},
            endpoint="tcp://remote.example:2376",
        )
        self.assertEqual(code, 0)
        self.assertFalse(any(command[:2] == ["docker", "context"] for command in commands))

    def test_remote_saved_context_is_blocked(self):
        code, _, commands = self.call_doctor(endpoint="tcp://remote.example:2376")
        self.assertEqual(code, 2)
        self.assertFalse(any(command[:2] == ["docker", "info"] for command in commands))

    def test_unverifiable_or_malformed_endpoint_is_blocked(self):
        for endpoint in (
            "unix://remote/run/docker.sock",
            "unix:///run/docker.sock?token=credential",
            "unix:///",
            "unix:///run/\nsock",
            None,
        ):
            with self.subTest(endpoint=endpoint):
                code, output, commands = self.call_doctor(endpoint=endpoint)
                self.assertEqual(code, 2)
                self.assertFalse(any(command[:2] == ["docker", "info"] for command in commands))
                self.assertNotIn("credential", output)
        code, _, commands = self.call_doctor(inspect_fails=True)
        self.assertEqual(code, 2)
        self.assertFalse(any(command[:2] == ["docker", "info"] for command in commands))

    def test_missing_docker_and_non_linux_server_are_blocked(self):
        self.assertEqual(self.call_doctor(missing_docker=True)[0], 2)
        self.assertEqual(self.call_doctor(server="windows")[0], 2)

    def test_kind_mode_checks_kind_and_kubectl_client(self):
        code, _, commands = self.call_doctor(mode="kind")
        self.assertEqual(code, 0)
        self.assertIn(["kind", "version"], commands)
        self.assertIn(["kubectl", "version", "--client=true"], commands)

    def test_cgroup_v1_blocks_kind_but_allows_mock(self):
        self.assertEqual(self.call_doctor(cgroup="1", mode="compose")[0], 0)
        code, output, commands = self.call_doctor(cgroup="1", mode="kind")
        self.assertEqual(code, 2)
        self.assertIn("requires cgroup v2", output)
        self.assertIn(["docker", "info", "--format", "{{.CgroupVersion}}"], commands)
        cleanup_code, _, cleanup_commands = self.call_doctor(
            cgroup="1", mode="kind", operation="cleanup"
        )
        self.assertEqual(cleanup_code, 0)
        self.assertNotIn(["docker", "info", "--format", "{{.CgroupVersion}}"], cleanup_commands)

    def test_kind_never_contacts_remote_daemon_even_for_cgroup_probe(self):
        code, _, commands = self.call_doctor(endpoint="ssh://remote.example", mode="kind")
        self.assertEqual(code, 2)
        self.assertFalse(any(command[:2] == ["docker", "info"] for command in commands))


if __name__ == "__main__":
    unittest.main()
