"""Static deployment boundaries supplement, never replace, live RBAC/Pod checks."""

from pathlib import Path
from string import Template

import yaml

ROOT = Path(__file__).resolve().parents[2]


def test_compose_exposes_only_loopback_console():
    config = yaml.safe_load((ROOT / "compose.yaml").read_text())
    services = config["services"]
    for name in ("api", "worker", "db"):
        assert not services[name].get("ports")
    assert all(port.startswith("127.0.0.1:") for port in services["web"]["ports"])
    for name in ("api", "worker", "web"):
        assert services[name]["read_only"] is True
        assert "ALL" in services[name]["cap_drop"]
        assert len(services[name]["tmpfs"]) == 1
        assert services[name]["tmpfs"][0].startswith("/tmp:")
        assert "noexec,nosuid" in services[name]["tmpfs"][0]
        assert not any("docker.sock" in str(value) for value in services[name].get("volumes", []))


def test_kind_api_and_nodeport_bind_loopback():
    text = (ROOT / "infra/kind/cluster.yaml.in").read_text()
    config = yaml.safe_load(Template(text).substitute(CONSOLE_PORT="8080", PREVIEW_PORT="8081"))
    assert config["networking"]["apiServerAddress"] == "127.0.0.1"
    assert all(
        mapping["listenAddress"] == "127.0.0.1"
        for mapping in config["nodes"][0]["extraPortMappings"]
    )
    assert "@sha256:" in config["nodes"][0]["image"]


def test_worker_rbac_has_no_secret_exec_or_cluster_writes():
    resources = list(yaml.safe_load_all((ROOT / "infra/kubernetes/rbac.yaml").read_text()))
    assert not any(
        resource["kind"] in {"ClusterRole", "ClusterRoleBinding"} for resource in resources
    )
    role = next(resource for resource in resources if resource["kind"] == "Role")
    assert role["metadata"]["namespace"] == "protohub-samples"
    for rule in role["rules"]:
        assert not ({"secrets", "pods/exec", "roles", "rolebindings", "*"} & set(rule["resources"]))
        assert "*" not in rule["verbs"]


def test_control_plane_credentials_and_workload_mounts():
    text = Template((ROOT / "infra/kubernetes/stack.yaml.in").read_text()).substitute(
        BUILD_TAG="test", CONSOLE_PORT="8080", PREVIEW_PORT="8081", OWNER_ID="test-owner"
    )
    deployments = {
        resource["metadata"]["name"]: resource
        for resource in yaml.safe_load_all(text)
        if resource and resource["kind"] == "Deployment"
    }
    for name, deployment in deployments.items():
        spec = deployment["spec"]["template"]["spec"]
        assert not spec.get("hostNetwork")
        assert not any("hostPath" in volume for volume in spec.get("volumes", []))
        assert spec["automountServiceAccountToken"] is (name == "worker")
        for container in spec["containers"]:
            security = container["securityContext"]
            assert security["allowPrivilegeEscalation"] is False
            assert "ALL" in security["capabilities"]["drop"]
