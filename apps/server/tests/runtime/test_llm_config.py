"""Shared key configuration and delivery never put secrets into app contracts."""

import importlib.util
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
import yaml
from pydantic import SecretStr

from protohub.domain.models import CreateSandbox
from protohub.domain.settings import Settings

ROOT = Path(__file__).resolve().parents[4]
SPEC = importlib.util.spec_from_file_location(
    "protohub_llm_local", ROOT / "scripts/local/manage.py"
)
local = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(local)
KEY = "synthetic-common-credential"


def test_all_apps_resolve_one_server_secret_and_cannot_override(monkeypatch):
    monkeypatch.setenv("PROTOHUB_LLM_API_KEY", KEY)
    settings = Settings()
    assert isinstance(settings.llm_api_key, SecretStr)
    assert settings.resolve_llm_api_key(uuid4()).get_secret_value() == KEY
    assert settings.resolve_llm_api_key(uuid4()) is settings.llm_api_key
    assert KEY not in repr(settings)
    assert KEY not in settings.model_dump_json()
    with pytest.raises(ValueError):
        CreateSandbox(name="App", template_id="hello-web", llm_api_key=KEY)


def test_key_is_optional_and_production_disables_dev_login(monkeypatch):
    monkeypatch.delenv("PROTOHUB_LLM_API_KEY", raising=False)
    assert Settings().resolve_llm_api_key() is None
    assert Settings(environment="development").dev_login_enabled
    assert not Settings(environment="production").dev_login_enabled


def test_secret_delivery_uses_only_stdin_and_suppresses_diagnostics(monkeypatch):
    monkeypatch.setenv("PROTOHUB_LLM_API_KEY", KEY)
    calls = []

    def execute(argv, **kwargs):
        calls.append((argv, kwargs))
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(local.subprocess, "run", execute)
    local.configure_llm_secret({"name": "protohub-test", "owner_id": "test-owner"})
    argv, options = calls[0]
    assert KEY not in repr(argv)
    assert "--server-side" in argv and "kind-protohub-test" in argv
    assert options["stdout"] == options["stderr"] == subprocess.DEVNULL
    manifest = json.loads(options["input"])
    assert manifest["stringData"] == {"api-key": KEY}
    assert manifest["metadata"]["namespace"] == "protohub-system"
    assert manifest["metadata"]["labels"][local.OWNER_LABEL] == "test-owner"


@pytest.mark.parametrize("failure", [1, "timeout"])
def test_secret_failure_never_returns_input_in_diagnostics(monkeypatch, failure):
    monkeypatch.setenv("PROTOHUB_LLM_API_KEY", KEY)

    def execute(argv, **kwargs):
        if failure == "timeout":
            raise subprocess.TimeoutExpired(argv, 30, stderr=KEY)
        return SimpleNamespace(returncode=1, stderr=KEY)

    monkeypatch.setattr(local.subprocess, "run", execute)
    with pytest.raises(local.Blocked) as error:
        local.configure_llm_secret({"name": "protohub-test", "owner_id": "test-owner"})
    assert KEY not in str(error.value)


def test_unset_key_retains_secret_and_explicit_empty_clears(monkeypatch):
    monkeypatch.delenv("PROTOHUB_LLM_API_KEY", raising=False)
    calls = []
    monkeypatch.setattr(
        local.subprocess,
        "run",
        lambda argv, **kw: calls.append(kw) or SimpleNamespace(returncode=0),
    )
    cfg = {"name": "protohub-test", "owner_id": "test-owner"}
    local.configure_llm_secret(cfg)
    assert calls == []
    monkeypatch.setenv("PROTOHUB_LLM_API_KEY", "")
    local.configure_llm_secret(cfg)
    assert json.loads(calls[0]["input"])["stringData"]["api-key"] == ""


def test_common_secret_goes_only_to_api_not_workers_or_samples():
    compose = yaml.safe_load((ROOT / "compose.yaml").read_text())
    for name, service in compose["services"].items():
        assert ("PROTOHUB_LLM_API_KEY" in service.get("environment", {})) == (name == "api")
    stack = list(yaml.safe_load_all((ROOT / "infra/kubernetes/stack.yaml.in").read_text()))
    for resource in stack:
        if resource.get("kind") != "Deployment":
            continue
        pod = resource["spec"]["template"]["spec"]
        for container in [*pod.get("containers", []), *pod.get("initContainers", [])]:
            refs = [
                item for item in container.get("env", []) if item["name"] == "PROTOHUB_LLM_API_KEY"
            ]
            assert bool(refs) == (container["name"] == "api")
            if refs:
                assert refs[0]["valueFrom"]["secretKeyRef"]["name"] == "protohub-llm"


def test_launcher_propagates_environment_and_rejects_invalid_value(monkeypatch, tmp_path):
    monkeypatch.setattr(local, "STATE", tmp_path)
    monkeypatch.setenv("PROTOHUB_ENVIRONMENT", "production")
    cfg = local.config("real-kind")
    assert cfg["environment"] == "production"
    rendered = local.render(cfg, "infra/kubernetes/stack.yaml.in", "stack.yaml", "synthetic-build")
    resources = list(yaml.safe_load_all(rendered.read_text()))
    config_map = next(item for item in resources if item["kind"] == "ConfigMap")
    assert config_map["data"]["PROTOHUB_ENVIRONMENT"] == "production"
    monkeypatch.setenv("PROTOHUB_ENVIRONMENT", "production\nunsafe: value")
    with pytest.raises(local.Blocked):
        local.config("real-kind")


def test_launcher_retains_saved_production_on_restart_without_environment(monkeypatch, tmp_path):
    monkeypatch.setattr(local, "STATE", tmp_path)
    monkeypatch.setenv("PROTOHUB_ENVIRONMENT", "production")
    cfg = local.config("real-kind")
    local.save(local.record_path(cfg), cfg)
    monkeypatch.delenv("PROTOHUB_ENVIRONMENT")
    assert local.config("real-kind")["environment"] == "production"
    local.save(local.STATE / "active.json", cfg)
    assert local.config()["environment"] == "production"
    monkeypatch.setenv("PROTOHUB_ENVIRONMENT", "development")
    assert local.config()["environment"] == "development"


def test_existing_kind_environment_override_is_saved_after_successful_up(monkeypatch, tmp_path):
    monkeypatch.setattr(local, "STATE", tmp_path)
    monkeypatch.setenv("PROTOHUB_ENVIRONMENT", "local")
    cfg = local.config("real-kind")
    local.save(
        local.record_path(cfg), {**cfg, "node_id": "retained-node", "creation_receipt": "same"}
    )
    monkeypatch.setenv("PROTOHUB_ENVIRONMENT", "production")
    production = local.config("real-kind")
    monkeypatch.setattr(local, "preflight", lambda mode: None)
    monkeypatch.setattr(local, "verify_kind", lambda cfg: True)
    monkeypatch.setattr(local, "run", lambda *args, **kwargs: "a" * 40)
    monkeypatch.setattr(local, "kube", lambda *args, **kwargs: "")
    monkeypatch.setattr(local, "configure_llm_secret", lambda cfg: None)
    local.up(production)
    saved = local.existing_record(production)
    assert saved["node_id"] == "retained-node" and saved["creation_receipt"] == "same"
    assert saved["environment"] == "production"
    monkeypatch.delenv("PROTOHUB_ENVIRONMENT")
    assert local.config("real-kind")["environment"] == "production"


def test_failed_kind_update_does_not_reenable_dev_login_on_unset_retry(monkeypatch, tmp_path):
    monkeypatch.setattr(local, "STATE", tmp_path)
    monkeypatch.setenv("PROTOHUB_ENVIRONMENT", "local")
    cfg = local.config("real-kind")
    local.save(local.record_path(cfg), {**cfg, "node_id": "retained-node"})
    monkeypatch.setenv("PROTOHUB_ENVIRONMENT", "production")
    production = local.config("real-kind")
    monkeypatch.setattr(local, "preflight", lambda mode: None)
    monkeypatch.setattr(local, "verify_kind", lambda cfg: True)

    def fail(*args, **kwargs):
        raise subprocess.CalledProcessError(1, ["git", "rev-parse", "HEAD"])

    monkeypatch.setattr(local, "run", fail)
    with pytest.raises(subprocess.CalledProcessError):
        local.up(production)
    monkeypatch.delenv("PROTOHUB_ENVIRONMENT")
    assert local.config("real-kind")["environment"] == "production"
    assert local.existing_record(production)["node_id"] == "retained-node"
