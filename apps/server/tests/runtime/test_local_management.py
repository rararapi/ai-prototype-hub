import importlib.util
import json
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import yaml

SOURCE = Path(__file__).resolve().parents[4] / "scripts/local/manage.py"
SPEC = importlib.util.spec_from_file_location("protohub_local", SOURCE)
local = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(local)


@pytest.fixture
def cfg(tmp_path, monkeypatch):
    monkeypatch.setattr(local, "STATE", tmp_path)
    for key in (
        "PROTOHUB_CLUSTER_NAME",
        "COMPOSE_PROJECT_NAME",
        "PROTOHUB_MODE",
        "PROTOHUB_CONSOLE_PORT",
        "PROTOHUB_PREVIEW_PORT",
        "PROTOHUB_RESET_CONFIRM",
    ):
        monkeypatch.delenv(key, raising=False)
    return {
        "name": "protohub-test",
        "mode": "real-kind",
        "owner_id": "test-owner",
        "console_port": 18080,
        "preview_port": 18081,
    }


def test_daily_commands_restore_previous_name_and_ports(cfg):
    local.save(local.STATE / "active.json", cfg)
    restored = local.config()
    assert restored["name"] == cfg["name"]
    assert restored["console_port"] == 18080 and restored["preview_port"] == 18081


def test_remote_or_unsafe_resource_names_rejected(cfg, monkeypatch):
    monkeypatch.setenv("PROTOHUB_CLUSTER_NAME", "../other-cluster")
    with pytest.raises(local.Blocked):
        local.config("real-kind")
    monkeypatch.setenv("PROTOHUB_CLUSTER_NAME", "protohub-safe")
    monkeypatch.setenv("PROTOHUB_CONSOLE_PORT", "80")
    with pytest.raises(local.Blocked):
        local.config("real-kind")


def test_compose_foreign_container_blocks_every_mutation(cfg, monkeypatch):
    cfg["mode"] = "mock"
    commands = []

    def execute(argv, capture=False):
        commands.append(argv)
        if argv[:3] == ["docker", "ps", "-aq"]:
            return "foreign-container"
        if argv[:3] == ["docker", "container", "inspect"]:
            return json.dumps([{"Config": {"Labels": {"protohub.io/owner": "other"}}}])
        raise AssertionError("must stop on first ownership mismatch")

    monkeypatch.setattr(local, "run", execute)
    with pytest.raises(local.Blocked, match="another owner"):
        local.verify_compose(cfg)
    assert all("down" not in argv and "rm" not in argv for argv in commands)


def test_unowned_existing_kind_never_adopted(cfg, monkeypatch):
    commands = []

    def execute(argv, capture=False):
        commands.append(argv)
        return cfg["name"]

    monkeypatch.setattr(local, "run", execute)
    with pytest.raises(local.Blocked, match="no matching ownership"):
        local.verify_kind(cfg)
    assert commands == [["kind", "get", "clusters"]]


def test_kind_replaced_node_cannot_be_deleted_by_old_record(cfg, monkeypatch):
    local.save(local.record_path(cfg), {**cfg, "node_id": "original"})

    def execute(argv, capture=False):
        if argv[0] == "kind":
            return cfg["name"]
        return json.dumps(
            [{"Id": "replacement", "Config": {"Labels": {"io.x-k8s.kind.cluster": cfg["name"]}}}]
        )

    monkeypatch.setattr(local, "run", execute)
    with pytest.raises(local.Blocked, match="identity differs"):
        local.verify_kind(cfg)


def test_reset_requires_exact_name_before_destructive_calls(cfg, monkeypatch):
    monkeypatch.setattr(local, "preflight", lambda _: None)
    monkeypatch.setattr(
        local, "run", lambda *_: pytest.fail("must not execute destructive command")
    )
    with pytest.raises(local.Blocked, match="exact name"):
        local.reset(cfg)


def test_daily_kind_down_scales_only_owned_workloads_and_retains_pvc(cfg, monkeypatch):
    monkeypatch.setattr(local, "preflight", lambda _: None)
    monkeypatch.setattr(local, "verify_kind", lambda _: True)
    commands = []
    monkeypatch.setattr(local, "kube", lambda _cfg, *args: commands.append(args))
    local.down(cfg)
    assert len(commands) == 3
    assert all("scale" in argv and "--replicas=0" in argv for argv in commands)
    assert all("delete" not in argv and "persistentvolumeclaim" not in argv for argv in commands)
    assert "app.kubernetes.io/managed-by=protohub" in commands[-1]


def test_rendered_kind_has_loopback_only_mappings_and_fixed_node_digest(cfg):
    output = local.render(cfg, "infra/kind/cluster.yaml.in", "cluster.yaml")
    cluster = yaml.safe_load(output.read_text())
    assert cluster["networking"]["apiServerAddress"] == "127.0.0.1"
    node = cluster["nodes"][0]
    assert "@sha256:" in node["image"]
    assert all(item["listenAddress"] == "127.0.0.1" for item in node["extraPortMappings"])
    assert {item["hostPort"] for item in node["extraPortMappings"]} == {18080, 18081}


def test_create_timeout_preserves_fresh_identity_for_owned_reset(cfg, monkeypatch):
    commands = []

    def execute(argv, capture=False):
        commands.append(argv)
        if argv[:3] == ["docker", "ps", "-aq"]:
            return ""
        if argv[:3] == ["kind", "create", "cluster"]:
            raise subprocess.CalledProcessError(1, argv)
        if argv[:2] == ["docker", "inspect"]:
            return json.dumps(
                [
                    {
                        "Id": "created-by-attempt",
                        "Created": datetime.now(UTC).isoformat(),
                        "Config": {
                            "Labels": {
                                "io.x-k8s.kind.cluster": cfg["name"],
                                "io.x-k8s.kind.role": "control-plane",
                            }
                        },
                    }
                ]
            )
        if argv == ["kind", "get", "clusters"]:
            return cfg["name"]
        if argv[:3] == ["kind", "delete", "cluster"]:
            return ""
        raise AssertionError(argv)

    monkeypatch.setattr(local, "run", execute)
    with pytest.raises(subprocess.CalledProcessError):
        local.create_kind(cfg, Path("cluster.yaml"))
    record = local.existing_record(cfg)
    assert record["node_id"] == "created-by-attempt"
    assert record["creation_receipt"] and record["bootstrap_state"] == "incomplete"
    monkeypatch.setattr(local, "preflight", lambda _: None)
    monkeypatch.setenv("PROTOHUB_RESET_CONFIRM", cfg["name"])

    def unavailable_api(*args, **kwargs):
        raise subprocess.CalledProcessError(1, ["kubectl"])

    monkeypatch.setattr(local, "kube", unavailable_api)
    local.reset(cfg)
    assert ["kind", "delete", "cluster", "--name", cfg["name"]] in commands


def test_bootstrap_cannot_capture_an_older_node(cfg, monkeypatch):
    local.save(
        local.record_path(cfg),
        {
            **cfg,
            "creation_receipt": "attempt",
            "creation_started_at": datetime.now(UTC).isoformat(),
        },
    )
    old = {
        "Id": "preexisting",
        "Created": (datetime.now(UTC) - timedelta(days=1)).isoformat(),
        "Config": {
            "Labels": {"io.x-k8s.kind.cluster": cfg["name"], "io.x-k8s.kind.role": "control-plane"}
        },
    }
    monkeypatch.setattr(local, "run", lambda *args: json.dumps([old]))
    with pytest.raises(local.Blocked, match="not a fresh"):
        local.capture_created_node(cfg, "attempt")
    assert "node_id" not in local.existing_record(cfg)


def test_test_fixture_up_does_not_change_developer_active_stack(cfg, monkeypatch):
    previous = {**cfg, "name": "protohub-developer"}
    local.save(local.STATE / "active.json", previous)
    before = (local.STATE / "active.json").read_bytes()
    cfg["mode"] = "mock"
    monkeypatch.setenv("PROTOHUB_NO_ACTIVATE", "1")
    monkeypatch.setattr(local, "preflight", lambda _: None)
    monkeypatch.setattr(local, "verify_compose", lambda _: False)
    monkeypatch.setattr(local, "free_ports", lambda _: None)
    monkeypatch.setattr(local, "compose", lambda *_: "")
    local.up(cfg)
    assert (local.STATE / "active.json").read_bytes() == before
    assert local.existing_record(cfg)["name"] == cfg["name"]
