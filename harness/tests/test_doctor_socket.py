"""Real local HTTP transport tests; never contact Docker or another service."""

import importlib.util
import io
import json
import os
import socket
import subprocess
import tempfile
import threading
import time
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

SPEC = importlib.util.spec_from_file_location(
    "protohub_socket_doctor", Path(__file__).resolve().parents[1] / "doctor.py"
)
doctor = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(doctor)


class FakeUnixHTTP:
    def __init__(self, body=None, status=200, headers=None, delay=0, drip=0, raw=None):
        self.body = body if body is not None else b'{"OSType":"linux","CgroupVersion":"2"}'
        self.status, self.headers = status, headers
        self.delay, self.drip, self.raw = delay, drip, raw
        self.requests = []
        self.stop = threading.Event()

    def __enter__(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="protohub-doctor-")
        self.path = str(Path(self.temporary.name) / "info.sock")
        self.listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.listener.bind(self.path)
        self.listener.listen(4)
        self.listener.settimeout(0.05)
        self.thread = threading.Thread(target=self.serve, daemon=True)
        self.thread.start()
        return self

    def serve(self):
        while not self.stop.is_set():
            try:
                connection, _ = self.listener.accept()
            except TimeoutError:
                continue
            except OSError:
                return
            with connection:
                connection.settimeout(1)
                try:
                    request = b""
                    while b"\r\n\r\n" not in request and len(request) < 16_384:
                        value = connection.recv(4096)
                        if not value:
                            break
                        request += value
                    self.requests.append(request)
                    if self.stop.wait(self.delay):
                        return
                    headers = self.headers
                    if headers is None:
                        headers = [("Content-Length", str(len(self.body)))]
                    response = self.raw
                    if response is None:
                        response = (
                            f"HTTP/1.1 {self.status} Test\r\n"
                            + "".join(f"{key}: {value}\r\n" for key, value in headers)
                            + "Connection: close\r\n\r\n"
                        ).encode() + self.body
                    if self.drip:
                        head, separator, body = response.partition(b"\r\n\r\n")
                        connection.sendall(head + separator)
                        for value in body:
                            if self.stop.wait(self.drip):
                                return
                            connection.sendall(bytes([value]))
                    else:
                        connection.sendall(response)
                except OSError:
                    # Deadline/size/error tests deliberately close without draining.
                    pass

    def __exit__(self, *_):
        self.stop.set()
        self.listener.close()
        self.thread.join(timeout=2)
        if self.thread.is_alive():
            raise AssertionError("Fake Unix HTTP server did not stop")
        self.temporary.cleanup()


@unittest.skipUnless(os.name == "posix" and hasattr(socket, "AF_UNIX"), "WSL/Linux transport")
class DoctorSocketTests(unittest.TestCase):
    def invoke(self, endpoint, mode="kind", operation="start", environment=None, system="Linux"):
        commands = []
        observed_config = []

        def command(argv, **kwargs):
            commands.append(argv)
            observed_config.append(os.environ.get("DOCKER_CONFIG"))
            if argv[:2] == ["docker", "info"]:
                raise AssertionError("No Docker CLI info fallback is allowed")
            if argv[:3] == ["docker", "context", "show"]:
                output = "saved-test-context"
            elif argv[:3] == ["docker", "context", "inspect"]:
                output = json.dumps(endpoint)
            else:
                output = "version"
            return subprocess.CompletedProcess(argv, 0, output, "")

        output = io.StringIO()
        with (
            mock.patch.dict(os.environ, environment or {}, clear=True),
            mock.patch.object(doctor.platform, "system", return_value=system),
            mock.patch.object(doctor.platform, "release", return_value="fixture"),
            mock.patch.object(doctor.shutil, "which", side_effect=lambda name: "/test/" + name),
            mock.patch.object(doctor.subprocess, "run", side_effect=command),
            redirect_stdout(output),
        ):
            code = doctor.main(["--mode", mode, "--operation", operation])
        return code, output.getvalue(), commands, observed_config

    def test_kind_reads_one_info_response_without_credentials_or_cli_server_calls(self):
        body = json.dumps(
            {"OSType": "linux", "CgroupVersion": "2", "HttpProxy": "credential-sentinel"}
        ).encode()
        with FakeUnixHTTP(body=body) as server:
            with mock.patch.object(
                doctor.http.client.socket,
                "create_connection",
                side_effect=AssertionError("TCP contact is forbidden"),
            ) as tcp:
                code, output, commands, _ = self.invoke("unix://" + server.path)
            tcp.assert_not_called()
            self.assertEqual(code, 0)
            self.assertEqual(len(server.requests), 1)
            request = server.requests[0].decode().lower()
            self.assertTrue(request.startswith("get /info http/1.1\r\n"))
            self.assertNotIn("authorization", request)
            self.assertNotIn("credential", request)
            self.assertNotIn("credential-sentinel", output)
            self.assertNotIn(server.path, output)
            self.assertIn("PASS docker-linux-server", output)
            self.assertIn("PASS docker-cgroup-v2", output)
            self.assertIn(["docker", "compose", "version"], commands)
            self.assertIn(["docker", "buildx", "version"], commands)
            self.assertIn(["kind", "version"], commands)
            self.assertIn(["kubectl", "version", "--client=true"], commands)

    def test_context_priority_and_docker_config_are_preserved(self):
        with FakeUnixHTTP() as server:
            environment = {
                "DOCKER_CONTEXT": "selected-test-context",
                "DOCKER_HOST": "ssh://credential-sentinel@remote.invalid",
                "DOCKER_CONFIG": "/test/config-sentinel",
                "HTTP_PROXY": "http://credential-sentinel@proxy.invalid",
            }
            code, output, commands, configs = self.invoke(
                "unix://" + server.path, environment=environment
            )
            self.assertEqual(code, 0)
            self.assertEqual(len(server.requests), 1)
            inspect = next(
                argv for argv in commands if argv[:3] == ["docker", "context", "inspect"]
            )
            self.assertEqual(inspect[-1], "selected-test-context")
            self.assertTrue(all(value == "/test/config-sentinel" for value in configs))
            self.assertFalse(any(argv[:3] == ["docker", "context", "use"] for argv in commands))
            self.assertNotIn("sentinel", output)

    def test_direct_host_uses_that_exact_socket_instead_of_saved_context(self):
        with FakeUnixHTTP() as server:
            code, _, commands, _ = self.invoke(
                "ssh://remote.invalid", environment={"DOCKER_HOST": "unix://" + server.path}
            )
            self.assertEqual(code, 0)
            self.assertEqual(len(server.requests), 1)
            self.assertFalse(any(argv[:2] == ["docker", "context"] for argv in commands))

    def test_remote_and_ambiguous_endpoints_never_open_any_server_socket(self):
        for endpoint in (
            "ssh://credential-sentinel@remote.invalid",
            "tcp://localhost:2375",
            "http://localhost:2375",
            "unix://remote.invalid/run/docker.sock",
            "unix:///run/docker.sock?token=credential-sentinel",
            "unix:///run/docker.sock#fragment",
            "unix:///run/%00docker.sock",
            "unix:///",
        ):
            with (
                self.subTest(endpoint=endpoint),
                mock.patch.object(doctor, "UnixInfoSocket") as socket_type,
            ):
                code, output, _, _ = self.invoke(endpoint)
                self.assertEqual(code, 2)
                socket_type.assert_not_called()
                self.assertNotIn("credential-sentinel", output)

    def test_cgroup_one_remains_allowed_for_compose_and_kind_cleanup(self):
        with FakeUnixHTTP(body=b'{"OSType":"linux","CgroupVersion":"1"}') as server:
            for mode, operation, expected in (
                ("compose", "start", 0),
                ("kind", "cleanup", 0),
                ("kind", "start", 2),
            ):
                with self.subTest(mode=mode, operation=operation):
                    self.assertEqual(
                        self.invoke("unix://" + server.path, mode, operation)[0], expected
                    )
            self.assertEqual(len(server.requests), 3)

    def test_info_is_not_cached_across_doctor_calls(self):
        with FakeUnixHTTP() as server:
            self.assertEqual(self.invoke("unix://" + server.path)[0], 0)
            server.body = b'{"OSType":"windows","CgroupVersion":"2"}'
            self.assertEqual(self.invoke("unix://" + server.path)[0], 2)
            self.assertEqual(len(server.requests), 2)

    def test_platform_guard_prevents_even_local_server_contact(self):
        with FakeUnixHTTP() as server:
            code, _, commands, _ = self.invoke("unix://" + server.path, system="Windows")
            self.assertEqual(code, 2)
            self.assertEqual(commands, [])
            self.assertEqual(server.requests, [])

    def test_non_200_and_redirect_are_blocked_without_printing_or_following_response(self):
        for status in (301, 403, 500):
            with (
                self.subTest(status=status),
                FakeUnixHTTP(
                    status=status,
                    body=b"credential-sentinel",
                    headers=[("Location", "http://credential-sentinel@remote.invalid")],
                ) as server,
            ):
                code, output, _, _ = self.invoke("unix://" + server.path)
                self.assertEqual(code, 2)
                self.assertNotIn("credential-sentinel", output)
                self.assertEqual(len(server.requests), 1)

    def test_malformed_json_or_missing_os_type_block_even_cleanup(self):
        for body in (
            b"not-json-credential-sentinel",
            b"[]",
            b"{}",
            b'{"CgroupVersion":"2"}',
            b'{"OSType":null,"CgroupVersion":"2"}',
            b'{"OSType":2,"CgroupVersion":"2"}',
            b'{"OSType":[],"CgroupVersion":"2"}',
            b'{"OSType":"","CgroupVersion":"2"}',
            b"\xff",
            b"[" * 1500 + b"]" * 1500,
        ):
            with self.subTest(body=body[:48]), FakeUnixHTTP(body=body) as server:
                code, output, _, _ = self.invoke("unix://" + server.path, operation="cleanup")
                self.assertEqual(code, 2)
                self.assertNotIn("credential-sentinel", output)

    def test_missing_or_invalid_cgroup_only_blocks_kind_start(self):
        for value in ("missing", None, 2, [], "", "unknown"):
            data = {"OSType": "linux"}
            if value != "missing":
                data["CgroupVersion"] = value
            with self.subTest(value=value), FakeUnixHTTP(body=json.dumps(data).encode()) as server:
                endpoint = "unix://" + server.path
                self.assertEqual(self.invoke(endpoint, mode="compose")[0], 0)
                self.assertEqual(self.invoke(endpoint, operation="cleanup")[0], 0)
                self.assertEqual(self.invoke(endpoint)[0], 2)
                self.assertEqual(len(server.requests), 3)

    def test_oversized_body_is_rejected_with_or_without_length(self):
        for headers in (None, []):
            with (
                self.subTest(headers=headers),
                FakeUnixHTTP(body=b" " * (doctor.MAX_INFO_BYTES + 1), headers=headers) as server,
            ):
                self.assertEqual(self.invoke("unix://" + server.path)[0], 2)

    def test_chunked_body_cannot_bypass_size_limit(self):
        data = b" " * (doctor.MAX_INFO_BYTES + 1)
        body = f"{len(data):x}\r\n".encode() + data + b"\r\n0\r\n\r\n"
        with FakeUnixHTTP(body=body, headers=[("Transfer-Encoding", "chunked")]) as server:
            self.assertEqual(self.invoke("unix://" + server.path)[0], 2)

    def test_body_at_the_exact_size_limit_is_allowed(self):
        data = b'{"OSType":"linux","CgroupVersion":"2"}'
        body = data + b" " * (doctor.MAX_INFO_BYTES - len(data))
        with FakeUnixHTTP(body=body) as server:
            self.assertEqual(self.invoke("unix://" + server.path)[0], 0)
            self.assertEqual(len(server.requests), 1)

    def test_malformed_http_and_length_are_blocked(self):
        responses = (
            b"not-http-credential-sentinel\r\n\r\n",
            b"HTTP/1.1 200 OK\r\nContent-Length: -1\r\n\r\n{}",
            b"HTTP/1.1 200 OK\r\nContent-Length: nope\r\n\r\n{}",
            b"HTTP/1.1 200 OK\r\nContent-Length: 100\r\n\r\n{}",
        )
        for raw in responses:
            with self.subTest(raw=raw[:32]), FakeUnixHTTP(raw=raw) as server:
                code, output, _, _ = self.invoke("unix://" + server.path)
                self.assertEqual(code, 2)
                self.assertNotIn("credential-sentinel", output)

    def test_unavailable_socket_blocks_without_fallback_or_path_disclosure(self):
        with tempfile.TemporaryDirectory(prefix="protohub-doctor-") as temporary:
            path = str(Path(temporary) / "absent.sock")
            code, output, _, _ = self.invoke("unix://" + path)
            self.assertEqual(code, 2)
            self.assertNotIn(path, output)

    def test_unresponsive_server_has_a_real_socket_timeout(self):
        with FakeUnixHTTP(delay=1) as server:
            started = time.monotonic()
            with self.assertRaises(TimeoutError):
                doctor.read_docker_info(server.path, timeout_seconds=0.05)
            self.assertLess(time.monotonic() - started, 0.5)

    def test_socket_timeout_is_reported_as_blocked_without_a_fallback(self):
        read_info = doctor.read_docker_info
        with (
            FakeUnixHTTP(delay=1) as server,
            mock.patch.object(
                doctor,
                "read_docker_info",
                side_effect=lambda path: read_info(path, timeout_seconds=0.05),
            ),
        ):
            code, output, _, _ = self.invoke("unix://" + server.path)
            self.assertEqual(code, 2)
            self.assertIn("BLOCKED docker-linux-server", output)
            self.assertNotIn(server.path, output)
            self.assertEqual(len(server.requests), 1)

    def test_slow_drip_cannot_reset_the_total_io_deadline(self):
        with FakeUnixHTTP(drip=0.02) as server:
            started = time.monotonic()
            with self.assertRaises(TimeoutError):
                doctor.read_docker_info(server.path, timeout_seconds=0.08)
            self.assertLess(time.monotonic() - started, 0.5)


if __name__ == "__main__":
    unittest.main()
