#!/usr/bin/env python3
"""Read-only environment checks for WSL2/Linux. Never installs or restarts tools."""

from __future__ import annotations

import argparse
import http.client
import json
import os
import platform
import re
import shutil
import socket
import subprocess
import time
from pathlib import Path
from urllib.parse import urlsplit

DOCKER_INFO_TIMEOUT = 12.0
MAX_INFO_BYTES = 1024 * 1024


def read_docker_setting(argv: list[str]) -> str:
    """Read CLI metadata only, never print context names or endpoint values."""
    result = subprocess.run(
        argv,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=12,
        check=False,
        shell=False,
    )
    if result.returncode != 0:
        raise ValueError("Docker metadata could not be read")
    return result.stdout.strip()


def local_docker_socket_path() -> str | None:
    """Verify the effective target before any request to the Docker server.

    No CLI override is supplied: DOCKER_CONTEXT wins over DOCKER_HOST, which
    wins over the saved context. Context inspect respects DOCKER_CONFIG and
    does not contact the daemon or mutate the selected context.
    Escaped socket names are rejected rather than guessing URL decoding rules.
    """
    if shutil.which("docker") is None:
        print("BLOCKED docker-endpoint: Docker CLI is unavailable")
        return None
    try:
        context = os.environ.get("DOCKER_CONTEXT", "")
        endpoint = os.environ.get("DOCKER_HOST", "")
        if context or not endpoint:
            context = context or read_docker_setting(["docker", "context", "show"])
            if not context or any(ord(char) < 32 for char in context):
                raise ValueError("Docker context is invalid")
            endpoint = json.loads(
                read_docker_setting(
                    [
                        "docker",
                        "context",
                        "inspect",
                        "--format",
                        "{{json .Endpoints.docker.Host}}",
                        "--",
                        context,
                    ]
                )
            )
        if not isinstance(endpoint, str) or any(
            char.isspace() or ord(char) < 32 for char in endpoint
        ):
            raise ValueError("Docker endpoint is invalid")
        target = urlsplit(endpoint)
        if (
            not endpoint.startswith("unix:///")
            or target.scheme != "unix"
            or target.netloc
            or not target.path.startswith("/")
            or target.path == "/"
            or target.query
            or target.fragment
            or "%" in target.path
        ):
            print(
                "BLOCKED docker-endpoint: only a local Unix socket is allowed; no server was contacted"
            )
            return None
    except (OSError, subprocess.SubprocessError, ValueError):
        print(
            "BLOCKED docker-endpoint: effective endpoint could not be verified; no server was contacted"
        )
        return None
    print("PASS docker-endpoint: effective target is a local Unix socket")
    return target.path


def local_docker_endpoint() -> bool:
    """Compatibility check without retaining a context or socket across calls."""
    return local_docker_socket_path() is not None


class UnixInfoSocket(socket.socket):
    """Apply one deadline to connect/send and every HTTP parser socket read."""

    def __init__(self, timeout_seconds: float) -> None:
        super().__init__(socket.AF_UNIX, socket.SOCK_STREAM)
        self.deadline = time.monotonic() + timeout_seconds

    def remaining(self) -> float:
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("Docker metadata deadline exceeded")
        return remaining

    def connect(self, address: str) -> None:
        self.settimeout(self.remaining())
        return super().connect(address)

    def sendall(self, data: bytes, flags: int = 0) -> None:
        self.settimeout(self.remaining())
        return super().sendall(data, flags)

    def recv_into(self, buffer, nbytes: int = 0, flags: int = 0) -> int:
        self.settimeout(self.remaining())
        return super().recv_into(buffer, nbytes, flags)


def read_docker_info(
    socket_path: str, *, timeout_seconds: float = DOCKER_INFO_TIMEOUT
) -> dict[str, str]:
    """One read-only Engine GET /info; return only the available capability fields.

    The verified Unix socket is the sole transport. HTTPConnection cannot open a
    TCP connection, use environment proxies, send credentials, or follow redirects.
    Engine API: https://docs.docker.com/reference/api/engine/
    """
    if not 0 < timeout_seconds <= DOCKER_INFO_TIMEOUT:
        raise ValueError("Invalid Docker metadata timeout")
    with UnixInfoSocket(timeout_seconds) as transport:
        transport.connect(socket_path)
        connection = http.client.HTTPConnection("localhost", timeout=timeout_seconds)
        connection.auto_open = False
        connection.sock = transport
        try:
            connection.request("GET", "/info", headers={"Connection": "close"})
            with connection.getresponse() as response:
                if response.status != 200:
                    raise ValueError("Docker metadata response was unsuccessful")
                length = response.getheader("Content-Length")
                if length is not None and (
                    re.fullmatch(r"[0-9]+", length) is None or int(length) > MAX_INFO_BYTES
                ):
                    raise ValueError("Invalid Docker metadata response size")
                payload = response.read(MAX_INFO_BYTES + 1)
                transport.remaining()
                if len(payload) > MAX_INFO_BYTES:
                    raise ValueError("Docker metadata response exceeded the size limit")
        finally:
            connection.close()
    data = json.loads(payload)
    if not isinstance(data, dict) or not isinstance(data.get("OSType"), str) or not data["OSType"]:
        raise ValueError("Docker metadata omitted required capabilities")
    result = {"OSType": data["OSType"]}
    if isinstance(data.get("CgroupVersion"), str) and data["CgroupVersion"] in {"1", "2"}:
        result["CgroupVersion"] = data["CgroupVersion"]
    return result


def probe(name: str, argv: list[str], required_output: str | None = None) -> bool:
    if shutil.which(argv[0]) is None:
        print(f"BLOCKED {name}: required executable is unavailable")
        return False
    try:
        result = subprocess.run(
            argv,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=12,
            check=False,
            shell=False,
        )
    except (OSError, subprocess.SubprocessError):
        print(f"BLOCKED {name}: read-only check could not finish")
        return False
    if result.returncode != 0:
        print(
            f"BLOCKED {name}: read-only check failed; verify the installed tool or selected daemon"
        )
        return False
    if required_output is not None and result.stdout.strip() != required_output:
        print(f"BLOCKED {name}: required Docker server capability is unavailable")
        return False
    # Intentionally do not echo arbitrary tool output, environment, or contexts.
    print(f"PASS {name}")
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("compose", "kind"), default="compose")
    parser.add_argument("--operation", choices=("start", "cleanup"), default="start")
    args = parser.parse_args(argv)
    if platform.system() != "Linux":
        print("BLOCKED platform: run inside WSL2 or Linux CI, not native Windows/macOS")
        return 2
    is_wsl = "microsoft" in platform.release().lower() or bool(os.environ.get("WSL_INTEROP"))
    print(
        "PASS platform: "
        + ("WSL/Linux environment" if is_wsl else "Linux environment (CI is supported)")
    )
    root = Path(__file__).resolve().parent.parent
    if re.match(r"^/mnt/[a-zA-Z](?:/|$)", str(root)):
        print("WARN filesystem: use the WSL Linux filesystem for source files and bind mounts")
    checks = [
        ("git", ["git", "--version"]),
        ("python3", ["python3", "--version"]),
        ("make", ["make", "--version"]),
        ("docker-cli", ["docker", "--version"]),
        ("compose-v2", ["docker", "compose", "version"]),
        ("buildx", ["docker", "buildx", "version"]),
    ]
    success = True
    for name, command in checks:
        success = probe(name, command) and success
    socket_path = local_docker_socket_path()
    success = socket_path is not None and success
    server_info = None
    if socket_path is not None:
        try:
            server_info = read_docker_info(socket_path)
        except (OSError, http.client.HTTPException, ValueError, RecursionError):
            print("BLOCKED docker-linux-server: bounded local server metadata check failed")
            success = False
        else:
            if server_info["OSType"] == "linux":
                print("PASS docker-linux-server")
            else:
                print("BLOCKED docker-linux-server: a Linux Docker server is required")
                success = False
    if args.mode == "kind":
        success = probe("kind", ["kind", "version"]) and success
        success = probe("kubectl", ["kubectl", "version", "--client=true"]) and success
        if socket_path is not None and args.operation == "start":
            cgroup_ready = (
                server_info is not None
                and server_info["OSType"] == "linux"
                and server_info.get("CgroupVersion") == "2"
            )
            if cgroup_ready:
                print("PASS docker-cgroup-v2")
            else:
                print("BLOCKED docker-cgroup-v2: required Docker server capability is unavailable")
                print(
                    "BLOCKED real-kind: selected Kubernetes 1.37 requires cgroup v2; review Docker/WSL configuration with explicit approval. No override or OS change was made."
                )
            success = cgroup_ready and success
    if not success:
        print(
            "BLOCKED doctor: fix prerequisites manually; no installation, sudo, restart, or context change was performed"
        )
        return 2
    print("PASS doctor: read-only prerequisites satisfied")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
