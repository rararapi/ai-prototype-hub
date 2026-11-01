"""Work-record rename preserves the identities used by owned local resources."""

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[4]
SPEC = importlib.util.spec_from_file_location(
    "protohub_worklogs_local", ROOT / "scripts/local/manage.py"
)
local = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(local)


@pytest.fixture
def checkout(tmp_path, monkeypatch):
    monkeypatch.setattr(local, "ROOT", tmp_path)
    monkeypatch.setattr(local, "STATE", tmp_path / "worklogs/local")
    for name in (
        "PROTOHUB_MODE",
        "PROTOHUB_CLUSTER_NAME",
        "COMPOSE_PROJECT_NAME",
        "PROTOHUB_CONSOLE_PORT",
        "PROTOHUB_PREVIEW_PORT",
        "PROTOHUB_ENVIRONMENT",
    ):
        monkeypatch.delenv(name, raising=False)
    return tmp_path


def retained_records(root):
    directory = root / ".harness/local"
    values = {
        "owner.json": {"owner_id": "original-owner"},
        "active.json": {
            "mode": "real-kind",
            "name": "protohub-retained",
            "owner_id": "original-owner",
            "console_port": 18080,
            "preview_port": 18081,
            "environment": "production",
        },
        "kind/protohub-retained/state.json": {
            "mode": "real-kind",
            "name": "protohub-retained",
            "owner_id": "original-owner",
            "console_port": 18080,
            "preview_port": 18081,
            "environment": "production",
            "node_id": "original-node",
            "creation_receipt": "original-receipt",
        },
    }
    for path, value in values.items():
        target = directory / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(value) + "\n")
    return {path: (directory / path).read_bytes() for path in values}


def test_default_state_uses_worklogs():
    assert local.STATE == local.ROOT / "worklogs/local"


def test_legacy_owner_active_and_node_receipts_migrate_unchanged(checkout):
    before = retained_records(checkout)
    cfg = local.config()
    assert cfg == {
        "mode": "real-kind",
        "name": "protohub-retained",
        "owner_id": "original-owner",
        "console_port": 18080,
        "preview_port": 18081,
        "environment": "production",
    }
    assert not (checkout / ".harness").exists()
    assert local.owner() == "original-owner"
    assert local.config() == cfg
    saved = local.existing_record(cfg)
    assert saved["node_id"] == "original-node"
    assert saved["creation_receipt"] == "original-receipt"
    for path, original in before.items():
        assert (checkout / "worklogs/local" / path).read_bytes() == original
    assert local.record_path(cfg) == checkout / "worklogs/local/kind/protohub-retained/state.json"


def test_fresh_checkout_creates_only_new_worklogs_owner(checkout):
    cfg = local.config("mock")
    assert cfg["owner_id"] == local.owner()
    assert (checkout / "worklogs/local/owner.json").is_file()
    assert not (checkout / ".harness").exists()


def test_conflicting_roots_refuse_before_generating_or_replacing_owner(checkout, monkeypatch):
    before = retained_records(checkout)
    (checkout / "worklogs").mkdir()
    monkeypatch.setattr(local, "uuid4", lambda: pytest.fail("must retain original owner"))
    with pytest.raises(local.LocalPathError, match="Both"):
        local.config()
    assert not (checkout / "worklogs/local").exists()
    for path, original in before.items():
        assert (checkout / ".harness/local" / path).read_bytes() == original


@pytest.mark.parametrize("name", [".harness", "worklogs"])
def test_symlink_root_refused_without_writing_external_owner(checkout, tmp_path, name):
    outside = checkout.parent / (checkout.name + "-outside")
    outside.mkdir()
    (checkout / name).symlink_to(outside, target_is_directory=True)
    with pytest.raises(local.LocalPathError, match="ordinary directories"):
        local.owner()
    assert list(outside.iterdir()) == []


def test_state_override_does_not_touch_checkout_paths(checkout, tmp_path, monkeypatch):
    retained_records(checkout)
    isolated = tmp_path / "fixture-state"
    monkeypatch.setattr(local, "STATE", isolated)
    owner = local.owner()
    assert json.loads((isolated / "owner.json").read_text())["owner_id"] == owner
    assert (checkout / ".harness/local/owner.json").is_file()
    assert not (checkout / "worklogs").exists()


def test_cli_conflict_reports_blocked_before_resource_commands(checkout, monkeypatch, capsys):
    retained_records(checkout)
    (checkout / "worklogs").mkdir()
    monkeypatch.setattr(sys, "argv", ["manage.py", "down"])
    monkeypatch.setattr(local, "run", lambda *args, **kwargs: pytest.fail("no resource commands"))
    assert local.main() == 78
    assert "Both .harness/ and worklogs/ exist" in capsys.readouterr().err


def test_import_does_not_attempt_work_record_migration(monkeypatch):
    monkeypatch.setattr(
        sys.modules["local_paths"],
        "worklogs_dir",
        lambda root: pytest.fail("imports must not migrate work records"),
    )
    spec = importlib.util.spec_from_file_location(
        "protohub_worklogs_import_only", ROOT / "scripts/local/manage.py"
    )
    imported = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(imported)
    assert imported.STATE == imported.ROOT / "worklogs/local"
