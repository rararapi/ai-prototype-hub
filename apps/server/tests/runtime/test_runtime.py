from copy import deepcopy
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from kubernetes import client
from kubernetes.client.exceptions import ApiException

from protohub.domain.models import SandboxStatus
from protohub.domain.ports import RuntimeFailure, RuntimeSpec
from protohub.domain.settings import Settings
from protohub.runtime.kubernetes import (
    GENERATION,
    MANAGED_BY,
    SANDBOX_ID,
    KubernetesRuntime,
    resource_name,
)
from protohub.runtime.mock import MockRuntime


def merge(target, patch):
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            merge(target[key], value)
        else:
            target[key] = deepcopy(value)


class FakeKubernetes:
    def __init__(self):
        self.resources = {"deployment": {}, "service": {}}
        self.pods = None
        self.calls = []
        self.reject_deployment = False
        self.after_service_write = None

    def __getattr__(self, name):
        verb, _, kind = name.partition("_namespaced_")

        def call(namespace, name=None, body=None, **kwargs):
            self.calls.append((verb, kind, namespace, deepcopy(body)))
            assert namespace == "protohub-samples"
            assert kwargs.get("_request_timeout") == (3, 5)
            if kind == "pod":
                if self.pods is not None:
                    return SimpleNamespace(items=self.pods)
                desired = kwargs["label_selector"].split(f"{SANDBOX_ID}=")[-1]
                return SimpleNamespace(
                    items=[
                        client.V1Pod(
                            metadata=client.V1ObjectMeta(
                                labels=resource["spec"]["template"]["metadata"]["labels"]
                            ),
                            status=client.V1PodStatus(
                                phase="Running",
                                conditions=[client.V1PodCondition(type="Ready", status="True")],
                            ),
                        )
                        for resource in self.resources["deployment"].values()
                        if resource["spec"]["replicas"] > 0
                        and resource["metadata"]["labels"][SANDBOX_ID] == desired
                    ]
                )
            if verb == "create":
                if kind == "deployment" and self.reject_deployment:
                    raise ApiException(status=403, reason="raw secret must not escape")
                name = body["metadata"]["name"]
                if name in self.resources[kind]:
                    raise ApiException(status=409)
                self.resources[kind][name] = deepcopy(body)
                metadata = self.resources[kind][name]["metadata"]
                metadata.update({"uid": str(uuid4()), "resourceVersion": "1", "generation": 1})
            elif name not in self.resources[kind]:
                raise ApiException(status=404)
            elif verb == "patch":
                current = self.resources[kind][name]
                assert body["metadata"]["resourceVersion"] == current["metadata"]["resourceVersion"]
                merge(current, body)
                current["metadata"]["resourceVersion"] = str(
                    int(current["metadata"]["resourceVersion"]) + 1
                )
            elif verb == "delete":
                current = self.resources[kind][name]
                assert body["preconditions"]["uid"] == current["metadata"]["uid"]
                del self.resources[kind][name]
                return None
            current = deepcopy(self.resources[kind][name])
            if kind == "deployment":
                current["status"] = {
                    "observedGeneration": current["metadata"]["generation"],
                    "readyReplicas": 1,
                    "availableReplicas": 1,
                    "updatedReplicas": 1,
                    "replicas": 1,
                }
            elif verb in {"create", "patch"} and self.after_service_write is not None:
                self.after_service_write()
            return client.ApiClient()._ApiClient__deserialize(
                current, "V1Deployment" if kind == "deployment" else "V1Service"
            )

        return call


@pytest.fixture
def setup_runtime():
    kube = FakeKubernetes()
    http = httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json={"app": "hello-web"})
        )
    )
    runtime = KubernetesRuntime(Settings(runtime_mode="real-kind"), kube, kube, http)
    return runtime, kube


def test_mock_is_explicit_url_free_and_generation_fenced():
    runtime = MockRuntime()
    spec = RuntimeSpec(uuid4(), 1)
    runtime.ensure_started(spec)
    assert runtime.observe(spec).status == SandboxStatus.RUNNING
    assert runtime.observe(spec).preview_url is None
    runtime.ensure_stopped(RuntimeSpec(spec.sandbox_id, 2))
    with pytest.raises(RuntimeFailure, match="newer"):
        runtime.ensure_started(spec)


def test_real_observed_lifecycle_and_independent_apps(setup_runtime):
    runtime, kube = setup_runtime
    first, second = RuntimeSpec(uuid4(), 1), RuntimeSpec(uuid4(), 1)
    runtime.ensure_started(first)
    runtime.ensure_started(first)
    runtime.ensure_started(second)
    assert len(kube.resources["deployment"]) == len(kube.resources["service"]) == 2
    observation = runtime.observe(first)
    assert observation.status == SandboxStatus.RUNNING
    assert observation.preview_url.endswith(f"/apps/{first.sandbox_id}/")
    runtime.ensure_stopped(RuntimeSpec(first.sandbox_id, 2))
    assert runtime.observe(RuntimeSpec(first.sandbox_id, 2)).status == SandboxStatus.STOPPED
    assert runtime.observe(second).status == SandboxStatus.RUNNING
    runtime.ensure_deleted(RuntimeSpec(first.sandbox_id, 3))
    assert runtime.observe(RuntimeSpec(first.sandbox_id, 3)).status == SandboxStatus.DELETED
    assert runtime.observe(second).status == SandboxStatus.RUNNING


def test_sample_security_and_fixed_image(setup_runtime):
    runtime, kube = setup_runtime
    spec = RuntimeSpec(uuid4(), 1)
    runtime.ensure_started(spec)
    body = kube.resources["deployment"][resource_name(spec)]["spec"]["template"]["spec"]
    assert body["automountServiceAccountToken"] is False
    assert body["securityContext"]["runAsNonRoot"] is True
    container = body["containers"][0]
    assert container["image"] == runtime.settings.sample_image
    assert container["securityContext"] == {
        "allowPrivilegeEscalation": False,
        "readOnlyRootFilesystem": True,
        "capabilities": {"drop": ["ALL"]},
    }
    assert "limits" in container["resources"]
    assert "hostPath" not in str(body) and "privileged" not in str(body)


def test_newer_generation_and_foreign_owner_never_mutated(setup_runtime):
    runtime, kube = setup_runtime
    old = RuntimeSpec(uuid4(), 1)
    new = RuntimeSpec(old.sandbox_id, 2)
    runtime.ensure_started(new)
    before = deepcopy(kube.resources)
    for function in (runtime.ensure_started, runtime.ensure_stopped, runtime.ensure_deleted):
        with pytest.raises(RuntimeFailure) as rejected:
            function(old)
        assert rejected.value.error.code == "stale_generation"
        assert kube.resources == before
    kube.resources["service"][resource_name(new)]["metadata"]["labels"][MANAGED_BY] = "someone-else"
    with pytest.raises(RuntimeFailure) as rejected:
        runtime.ensure_deleted(new)
    assert rejected.value.error.code == "resource_conflict"


def test_running_requires_http_sentinel_not_just_kubernetes(setup_runtime):
    runtime, kube = setup_runtime
    spec = RuntimeSpec(uuid4(), 1)
    runtime.ensure_started(spec)
    for response in (
        httpx.Response(302, headers={"location": "http://example.invalid"}),
        httpx.Response(200, json={"app": "other"}),
        httpx.Response(500),
    ):
        runtime.http = httpx.Client(
            transport=httpx.MockTransport(lambda request, response=response: response)
        )
        assert runtime.observe(spec).status == SandboxStatus.STARTING
    kube.pods = [object()]
    runtime.ensure_stopped(RuntimeSpec(spec.sandbox_id, 2))
    assert runtime.observe(RuntimeSpec(spec.sandbox_id, 2)).status == SandboxStatus.STOPPING


def test_new_deployment_without_controller_status_is_starting(setup_runtime):
    runtime, kube = setup_runtime
    spec = RuntimeSpec(uuid4(), 1)
    runtime.ensure_started(spec)
    read = kube.read_namespaced_deployment

    def no_status(**kwargs):
        result = read(**kwargs)
        result.status = None
        return result

    kube.read_namespaced_deployment = no_status
    assert runtime.observe(spec).status == SandboxStatus.STARTING


def test_partial_failure_safe_error_and_owner_only_cleanup(setup_runtime):
    runtime, kube = setup_runtime
    spec, unaffected = RuntimeSpec(uuid4(), 1), RuntimeSpec(uuid4(), 1)
    runtime.ensure_started(unaffected)
    kube.reject_deployment = True
    with pytest.raises(RuntimeFailure) as failure:
        runtime.ensure_started(spec)
    assert failure.value.error.code == "runtime_rejected"
    assert "secret" not in str(failure.value)
    assert resource_name(spec) in kube.resources["service"]
    runtime.ensure_deleted(spec)
    assert resource_name(spec) not in kube.resources["service"]
    assert resource_name(unaffected) in kube.resources["deployment"]


def test_stop_generation_fences_delayed_start(setup_runtime):
    runtime, kube = setup_runtime
    spec = RuntimeSpec(uuid4(), 1)
    runtime.ensure_started(spec)
    runtime.ensure_stopped(RuntimeSpec(spec.sandbox_id, 2))
    assert kube.resources["service"][resource_name(spec)]["metadata"]["labels"][GENERATION] == "2"
    with pytest.raises(RuntimeFailure):
        runtime.ensure_started(spec)
    assert kube.resources["deployment"][resource_name(spec)]["spec"]["replicas"] == 0
    assert kube.resources["service"][resource_name(spec)]["metadata"]["labels"][SANDBOX_ID] == str(
        spec.sandbox_id
    )


def test_old_healthy_rollout_cannot_mark_new_generation_running(setup_runtime):
    runtime, kube = setup_runtime
    spec = RuntimeSpec(uuid4(), 2)
    runtime.ensure_started(spec)
    service = kube.resources["service"][resource_name(spec)]
    assert service["spec"]["selector"][GENERATION] == "2"
    original = kube.read_namespaced_deployment

    def old_ready_rollout(**kwargs):
        deployment = original(**kwargs)
        deployment.metadata.generation = 2
        deployment.status.observed_generation = 2
        deployment.status.updated_replicas = 0
        return deployment

    kube.read_namespaced_deployment = old_ready_rollout
    assert runtime.observe(spec).status == SandboxStatus.STARTING
    kube.read_namespaced_deployment = original
    kube.pods = [
        client.V1Pod(
            metadata=client.V1ObjectMeta(labels={GENERATION: "1"}),
            status=client.V1PodStatus(
                phase="Running", conditions=[client.V1PodCondition(type="Ready", status="True")]
            ),
        )
    ]
    assert runtime.observe(spec).status == SandboxStatus.STARTING
    kube.pods[0].metadata.labels[GENERATION] = "2"
    kube.pods[0].status.conditions[0].status = "False"
    assert runtime.observe(spec).status == SandboxStatus.STARTING
    kube.pods[0].status.conditions[0].status = "True"
    assert runtime.observe(spec).status == SandboxStatus.RUNNING


def test_lease_loss_after_service_write_prevents_deployment_side_effect(setup_runtime):
    runtime, kube = setup_runtime
    valid = [True]
    spec = RuntimeSpec(uuid4(), 1, may_mutate=lambda: valid[0])
    kube.after_service_write = lambda: valid.__setitem__(0, False)
    with pytest.raises(RuntimeFailure) as lost:
        runtime.ensure_started(spec)
    assert lost.value.error.code == "lease_lost"
    assert resource_name(spec) in kube.resources["service"]
    assert resource_name(spec) not in kube.resources["deployment"]
    assert not any(verb == "create" and kind == "deployment" for verb, kind, _, _ in kube.calls)
