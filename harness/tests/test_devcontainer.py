"""Dev Container isolation invariants and the real host-check interpreter selector."""

import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path, PurePosixPath
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "devcontainer_checks", ROOT / "scripts/checks/check.py"
)
checks = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(checks)


def mount_options(value):
    if isinstance(value, dict):
        return {
            "source": value.get("source"),
            "target": value.get("target"),
            "type": value.get("type"),
        }
    if not isinstance(value, str):
        raise AssertionError("Mounts must use Dev Container string/object definitions")
    result = {}
    for entry in value.split(","):
        if entry == "volume-nocopy" and entry not in result:
            result[entry] = True
            continue
        key, separator, content = entry.partition("=")
        if not separator or key in result:
            raise AssertionError("Mount options must have unambiguous key=value entries")
        result[key] = content
    return result


def resolve_mount(value, config, dev_id):
    variables = {
        "${devcontainerId}": dev_id,
        "${localWorkspaceFolder}": "/home/example/src/protohub",
        "${localWorkspaceFolderBasename}": "protohub",
        "${containerWorkspaceFolder}": config["workspaceFolder"],
    }
    options = mount_options(value)
    for key, content in options.items():
        if isinstance(content, str):
            for name, replacement in variables.items():
                content = content.replace(name, replacement)
            if "${" in content:
                raise AssertionError(f"Unsupported unresolved mount variable: {key}")
            options[key] = content
    return options


class DevContainerBoundaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path = ROOT / ".devcontainer/devcontainer.json"
        cls.config = json.loads(path.read_text(encoding="utf-8"))

    def test_only_workspace_is_bound_from_host(self):
        config = self.config
        mounts = [config["workspaceMount"], *config.get("mounts", [])]
        resolved = [resolve_mount(mount, config, "instance-a") for mount in mounts]
        binds = [mount for mount in resolved if mount["type"] == "bind"]
        self.assertEqual(len(binds), 1, "Only the requested workspace may be host-bound")
        self.assertEqual(binds[0]["source"], "/home/example/src/protohub")
        self.assertEqual(binds[0]["target"], config["workspaceFolder"])
        self.assertTrue(all(mount["type"] in {"bind", "volume"} for mount in resolved))
        # Socket and credential mounts would be additional binds and fail above.
        for mount in resolved:
            self.assertNotIn("docker.sock", mount.get("source") or "")
            self.assertNotIn("kubeconfig", mount.get("source") or "")

    def test_dependency_volumes_mask_host_dependencies_and_are_instance_unique(self):
        config = self.config
        workspace = PurePosixPath(config["workspaceFolder"])
        expected = {
            "/opt/protohub-venv",
            str(workspace / "apps/web/node_modules"),
            str(workspace / "tests/e2e/node_modules"),
        }
        first = [resolve_mount(mount, config, "instance-a") for mount in config["mounts"]]
        second = [resolve_mount(mount, config, "instance-b") for mount in config["mounts"]]
        by_target = {mount["target"]: mount for mount in first}
        self.assertEqual(len(by_target), len(first), "Dependency mounts must not shadow each other")
        self.assertTrue(expected.issubset(by_target))
        for target in expected:
            self.assertEqual(by_target[target]["type"], "volume")
            self.assertIs(
                by_target[target].get("volume-nocopy"),
                True,
                "Fresh dependency volumes must not copy host/image dependency contents",
            )
        first_sources = {mount["source"] for mount in first}
        second_sources = {mount["source"] for mount in second}
        self.assertEqual(len(first_sources), len(first))
        self.assertTrue(
            first_sources.isdisjoint(second_sources),
            "Different Dev Containers must not share mutable dependency volumes",
        )
        self.assertEqual(config["containerEnv"]["UV_PROJECT_ENVIRONMENT"], "/opt/protohub-venv")
        self.assertNotIn(
            str(workspace / "apps/server/.venv"),
            by_target,
            "Container Python must not use the host project's virtualenv",
        )

    def test_default_container_has_no_host_privileges_or_public_app_ports(self):
        config = self.config
        self.assertFalse(config.get("privileged", False))
        self.assertFalse(config.get("capAdd", []))
        self.assertFalse(config.get("features", {}), "Default features must not add daemon access")
        self.assertFalse(config.get("dockerComposeFile"), "Toolchain container must not start apps")
        self.assertFalse(config.get("runServices", []))
        self.assertFalse(config.get("forwardPorts", []))
        self.assertFalse(config.get("appPort"))
        initialize = config.get("initializeCommand")
        if initialize:
            self.assertIsInstance(initialize, list, "Host initialization must use explicit argv")
            self.assertEqual(
                initialize[:2],
                ["mkdir", "-p"],
                "Only nondestructive workspace mountpoint preparation is allowed",
            )
            self.assertEqual(
                set(initialize[2:]),
                {
                    "${localWorkspaceFolder}/apps/web/node_modules",
                    "${localWorkspaceFolder}/tests/e2e/node_modules",
                },
            )
        for environment in (config.get("containerEnv", {}), config.get("remoteEnv", {})):
            self.assertFalse(
                {"DOCKER_HOST", "DOCKER_CONTEXT", "KUBECONFIG", "AWS_PROFILE"} & set(environment),
                "No host management credentials are inherited",
            )
        forbidden = {
            "--privileged",
            "--network",
            "--net",
            "--pid",
            "--ipc",
            "--cap-add",
            "--device",
            "--mount",
            "--volume",
            "-v",
            "--publish",
            "-p",
            "-P",
            "--publish-all",
            "--env-file",
            "--add-host",
        }
        for argument in config.get("runArgs", []):
            self.assertNotIn(argument.split("=", 1)[0], forbidden)
            self.assertNotIn("unconfined", argument)
        for option in config.get("securityOpt", []):
            self.assertNotIn("unconfined", option)

    def test_developer_identity_and_startup_preserve_privilege_drop(self):
        config = self.config
        self.assertEqual(config["remoteUser"], "developer")
        self.assertIs(config["updateRemoteUserUID"], True)
        self.assertIs(
            config["overrideCommand"],
            False,
            "Overriding CMD can bypass the entrypoint's validated privilege drop",
        )
        build = config["build"]
        context = (ROOT / ".devcontainer" / build.get("context", ".")).resolve()
        dockerfile = (ROOT / ".devcontainer" / build["dockerfile"]).resolve()
        self.assertTrue(context.is_relative_to(ROOT), "Build context must be this checkout")
        self.assertTrue(dockerfile.is_relative_to(ROOT / ".devcontainer"))
        self.assertTrue(dockerfile.is_file())


class CheckInterpreterTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="protohub-devcontainer-env-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.server = self.root / "server"
        self.server.mkdir()
        self.patch_server = patch.object(checks, "SERVER", self.server)
        self.patch_server.start()
        self.addCleanup(self.patch_server.stop)
        self.patch_env = patch.dict(os.environ, {}, clear=True)
        self.patch_env.start()
        self.addCleanup(self.patch_env.stop)

    def interpreter(self, environment):
        suffix = "Scripts/python.exe" if os.name == "nt" else "bin/python"
        path = environment / suffix
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("synthetic interpreter path fixture", encoding="utf-8")
        path.chmod(0o755)
        return path

    def test_unset_override_uses_project_virtualenv(self):
        expected = self.interpreter(self.server / ".venv")
        self.assertEqual(Path(checks.python()).resolve(), expected.resolve())

    def test_absolute_uv_environment_uses_dependency_volume_instead_of_host_virtualenv(self):
        self.interpreter(self.server / ".venv")
        expected = self.interpreter(self.root / "external-volume")
        os.environ["UV_PROJECT_ENVIRONMENT"] = str(expected.parent.parent)
        self.assertEqual(Path(checks.python()).resolve(), expected.resolve())

    def test_relative_uv_environment_is_project_relative(self):
        expected = self.interpreter(self.server / "container-env")
        os.environ["UV_PROJECT_ENVIRONMENT"] = "container-env"
        self.assertEqual(Path(checks.python()).resolve(), expected.resolve())

    def test_missing_explicit_environment_refuses_a_silent_project_fallback(self):
        self.interpreter(self.server / ".venv")
        os.environ["UV_PROJECT_ENVIRONMENT"] = str(self.root / "missing-volume")
        with self.assertRaises(checks.MissingPrerequisite):
            checks.python()

    def test_interpreter_directory_is_not_a_usable_virtualenv(self):
        suffix = "Scripts/python.exe" if os.name == "nt" else "bin/python"
        (self.server / ".venv" / suffix).mkdir(parents=True)
        with self.assertRaises(checks.MissingPrerequisite):
            checks.python()


if __name__ == "__main__":
    unittest.main()
