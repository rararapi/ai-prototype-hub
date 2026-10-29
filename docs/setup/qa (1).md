#!/usr/bin/env python3
"""Read-only environment checks for WSL2/Linux. Never installs or restarts tools."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
from urllib.parse import urlsplit


def read_docker_setting(argv: list[str]) -> str:
    """Read CLI metadata only, never print context names or endpoint values."""
    result = subprocess.run(argv, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=12, check=False, shell=False)
    if result.returncode != 0:
        raise ValueError("Docker metadata could not be read")
    return result.stdout.strip()


def local_docker_endpoint() -> bool:
    """Verify the effective target before any request to the Docker server.

    No CLI override is supplied: DOCKER_CONTEXT wins over DOCKER_HOST, which
    wins over the saved context. Context inspect respects DOCKER_CONFIG and
    does not contact the daemon or mutate the selected context.
    """
    if shutil.which("docker") is None:
        print("BLOCKED docker-endpoint: Docker CLI is unavailable")
        return False
    try:
        context = os.environ.get("DOCKER_CONTEXT", "")
        endpoint = os.environ.get("DOCKER_HOST", "")
        if context or not endpoint:
            context = context or read_docker_setting(["docker", "context", "show"])
            if not context or any(ord(char) < 32 for char in context):
                raise ValueError("Docker context is invalid")
            endpoint = json.loads(read_docker_setting(["docker", "context", "inspect", "--format", "{{json .Endpoints.docker.Host}}", "--", context]))
        if not isinstance(endpoint, str) or any(char.isspace() or ord(char) < 32 for char in endpoint):
            raise ValueError("Docker endpoint is invalid")
        target = urlsplit(endpoint)
        if not endpoint.startswith("unix:///") or target.scheme != "unix" or target.netloc or not target.path.startswith("/") or target.path == "/" or target.query or target.fragment:
            print("BLOCKED docker-endpoint: only a local Unix socket is allowed; no server was contacted")
            return False
    except (OSError, subprocess.SubprocessError, ValueError):
        print("BLOCKED docker-endpoint: effective endpoint could not be verified; no server was contacted")
        return False
    print("PASS docker-endpoint: effective target is a local Unix socket")
    return True


def probe(name: str, argv: list[str], required_output: str | None = None) -> bool:
    if shutil.which(argv[0]) is None:
        print(f"BLOCKED {name}: required executable is unavailable")
        return False
    try:
        result = subprocess.run(argv, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=12, check=False, shell=False)
    except (OSError, subprocess.SubprocessError):
        print(f"BLOCKED {name}: read-only check could not finish")
        return False
    if result.returncode != 0:
        print(f"BLOCKED {name}: read-only check failed; verify the installed tool or selected daemon")
        return False
    if required_output is not None and result.stdout.strip() != required_output:
        print(f"BLOCKED {name}: a Linux Docker server is required")
        return False
    # Intentionally do not echo arbitrary tool output, environment, or contexts.
    print(f"PASS {name}")
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("compose", "kind"), default="compose")
    args = parser.parse_args(argv)
    if platform.system() != "Linux":
        print("BLOCKED platform: run inside WSL2 or Linux CI, not native Windows/macOS")
        return 2
    is_wsl = "microsoft" in platform.release().lower() or bool(os.environ.get("WSL_INTEROP"))
    print("PASS platform: " + ("WSL/Linux environment" if is_wsl else "Linux environment (CI is supported)"))
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
    endpoint_is_local = local_docker_endpoint()
    success = endpoint_is_local and success
    if endpoint_is_local:
        success = probe("docker-linux-server", ["docker", "info", "--format", "{{.OSType}}"], required_output="linux") and success
    if args.mode == "kind":
        success = probe("kind", ["kind", "version"]) and success
        success = probe("kubectl", ["kubectl", "version", "--client=true"]) and success
    if not success:
        print("BLOCKED doctor: fix prerequisites manually; no installation, sudo, restart, or context change was performed")
        return 2
    print("PASS doctor: read-only prerequisites satisfied")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
