"""Only fixed trusted samples in one namespace, using in-cluster credentials."""

from typing import Any

import httpx
from kubernetes import client, config
from kubernetes.client.exceptions import ApiException

from protohub.domain.models import SandboxStatus
from protohub.domain.ports import Observation, RuntimeFailure, RuntimeSpec
from protohub.domain.settings import Settings

MANAGED_BY = "app.kubernetes.io/managed-by"
SANDBOX_ID = "protohub.io/sandbox-id"
GENERATION = "protohub.io/generation"


def resource_name(spec: RuntimeSpec) -> str:
    return "sandbox-" + spec.sandbox_id.hex


def labels(spec: RuntimeSpec) -> dict[str, str]:
    return {
        MANAGED_BY: "protohub",
        SANDBOX_ID: str(spec.sandbox_id),
        GENERATION: str(spec.generation),
    }


def sample_url(settings: Settings, spec: RuntimeSpec, path: str = "/healthz") -> str:
    return f"http://{resource_name(spec)}.{settings.sample_namespace}.svc.cluster.local:8080{path}"


class KubernetesRuntime:
    def __init__(
        self, settings: Settings, apps: Any, core: Any, http: httpx.Client | None = None
    ) -> None:
        self.settings, self.apps, self.core = settings, apps, core
        self.http = http or httpx.Client(timeout=3, follow_redirects=False, trust_env=False)

    @classmethod
    def in_cluster(cls, settings: Settings) -> "KubernetesRuntime":
        # Deliberately no load_kube_config fallback and no host kubeconfig.
        config.load_incluster_config()
        return cls(settings, client.AppsV1Api(), client.CoreV1Api())

    def _call(self, function: Any, missing_ok: bool = False, **kwargs: Any) -> Any:
        try:
            return function(**kwargs, _request_timeout=(3, 5))
        except ApiException as exc:
            if exc.status == 404 and missing_ok:
                return None
            retryable = exc.status in {0, 409, 429, 500, 502, 503, 504}
            raise RuntimeFailure(
                "runtime_unavailable" if retryable else "runtime_rejected",
                "Sample runtime request could not complete",
                retryable,
            ) from None
        except Exception:
            raise RuntimeFailure(
                "runtime_unavailable", "Sample runtime is unavailable", True
            ) from None

    def _owned(self, obj: Any, spec: RuntimeSpec) -> None:
        if obj is None:
            return
        found = obj.metadata.labels or {}
        if found.get(MANAGED_BY) != "protohub" or found.get(SANDBOX_ID) != str(spec.sandbox_id):
            raise RuntimeFailure(
                "resource_conflict", "A resource with this name is not owned by ProtoHub"
            )
        try:
            generation = int(found.get(GENERATION, "-1"))
        except ValueError:
            generation = -1
        if generation < 0 or generation > spec.generation:
            raise RuntimeFailure("stale_generation", "A newer operation owns this sample")

    def _get(self, kind: str, spec: RuntimeSpec) -> Any:
        api = self.apps if kind == "deployment" else self.core
        result = self._call(
            getattr(api, f"read_namespaced_{kind}"),
            missing_ok=True,
            name=resource_name(spec),
            namespace=self.settings.sample_namespace,
        )
        self._owned(result, spec)
        return result

    def _authorize(self, spec: RuntimeSpec) -> None:
        if spec.may_mutate is not None:
            try:
                allowed = spec.may_mutate()
            except Exception:
                allowed = False
            if not allowed:
                raise RuntimeFailure("lease_lost", "This operation no longer owns the sample")

    def _upsert(self, kind: str, spec: RuntimeSpec, body: dict[str, Any]) -> None:
        existing = self._get(kind, spec)
        api = self.apps if kind == "deployment" else self.core
        self._authorize(spec)
        if existing is None:
            self._call(
                getattr(api, f"create_namespaced_{kind}"),
                namespace=self.settings.sample_namespace,
                body=body,
            )
        else:
            # Optimistic resourceVersion prevents a concurrent newer owner being overwritten.
            body["metadata"]["resourceVersion"] = existing.metadata.resource_version
            self._call(
                getattr(api, f"patch_namespaced_{kind}"),
                name=resource_name(spec),
                namespace=self.settings.sample_namespace,
                body=body,
            )

    def ensure_started(self, spec: RuntimeSpec) -> None:
        if spec.template_id != "hello-web":
            raise RuntimeFailure(
                "invalid_template", "Only the trusted hello-web template is supported"
            )
        selector = {MANAGED_BY: "protohub", SANDBOX_ID: str(spec.sandbox_id)}
        self._upsert(
            "service",
            spec,
            {
                "apiVersion": "v1",
                "kind": "Service",
                "metadata": {"name": resource_name(spec), "labels": labels(spec)},
                "spec": {
                    "selector": {**selector, GENERATION: str(spec.generation)},
                    "ports": [{"port": 8080, "targetPort": 8080}],
                },
            },
        )
        self._upsert(
            "deployment",
            spec,
            {
                "apiVersion": "apps/v1",
                "kind": "Deployment",
                "metadata": {"name": resource_name(spec), "labels": labels(spec)},
                "spec": {
                    "replicas": 1,
                    "selector": {"matchLabels": selector},
                    "template": {
                        "metadata": {"labels": labels(spec)},
                        "spec": {
                            "automountServiceAccountToken": False,
                            "securityContext": {
                                "runAsNonRoot": True,
                                "runAsUser": 10001,
                                "runAsGroup": 10001,
                                "seccompProfile": {"type": "RuntimeDefault"},
                            },
                            "containers": [
                                {
                                    "name": "hello-web",
                                    "image": self.settings.sample_image,
                                    "imagePullPolicy": "IfNotPresent",
                                    "ports": [{"containerPort": 8080}],
                                    "securityContext": {
                                        "allowPrivilegeEscalation": False,
                                        "readOnlyRootFilesystem": True,
                                        "capabilities": {"drop": ["ALL"]},
                                    },
                                    "resources": {
                                        "requests": {"cpu": "25m", "memory": "32Mi"},
                                        "limits": {"cpu": "200m", "memory": "96Mi"},
                                    },
                                    "readinessProbe": {
                                        "httpGet": {"path": "/healthz", "port": 8080},
                                        "periodSeconds": 2,
                                        "timeoutSeconds": 1,
                                    },
                                    "volumeMounts": [{"name": "tmp", "mountPath": "/tmp"}],
                                }
                            ],
                            "volumes": [{"name": "tmp", "emptyDir": {"sizeLimit": "8Mi"}}],
                        },
                    },
                },
            },
        )

    def _pods(self, spec: RuntimeSpec) -> list[Any]:
        result = self._call(
            self.core.list_namespaced_pod,
            namespace=self.settings.sample_namespace,
            label_selector=f"{MANAGED_BY}=protohub,{SANDBOX_ID}={spec.sandbox_id}",
        )
        return result.items if result is not None else []

    def observe(self, spec: RuntimeSpec) -> Observation:
        deployment, service = self._get("deployment", spec), self._get("service", spec)
        pods = self._pods(spec)
        if deployment is None:
            if pods:
                return Observation(SandboxStatus.STOPPING)
            return Observation(SandboxStatus.DELETED if service is None else SandboxStatus.STOPPED)
        if (deployment.spec.replicas or 0) == 0:
            return Observation(SandboxStatus.STOPPING if pods else SandboxStatus.STOPPED)
        state = deployment.status
        if (
            service is None
            or state is None
            or (state.observed_generation or 0) < deployment.metadata.generation
            or (state.updated_replicas or 0) < deployment.spec.replicas
            or (state.replicas or 0) != deployment.spec.replicas
            or (state.available_replicas or 0) < 1
            or (state.ready_replicas or 0) < 1
            or not any(
                (pod.metadata.labels or {}).get(GENERATION) == str(spec.generation)
                and pod.metadata.deletion_timestamp is None
                and pod.status is not None
                and pod.status.phase == "Running"
                and any(
                    c.type == "Ready" and c.status == "True" for c in (pod.status.conditions or [])
                )
                for pod in pods
            )
        ):
            return Observation(SandboxStatus.STARTING)
        try:
            response = self.http.get(sample_url(self.settings, spec))
            if response.status_code != 200 or response.json().get("app") != "hello-web":
                return Observation(SandboxStatus.STARTING)
        except (httpx.HTTPError, ValueError, AttributeError):
            return Observation(SandboxStatus.STARTING)
        return Observation(
            SandboxStatus.RUNNING,
            f"{self.settings.preview_origin.rstrip('/')}/apps/{spec.sandbox_id}/",
        )

    def ensure_stopped(self, spec: RuntimeSpec) -> None:
        for kind in ("deployment", "service"):
            obj = self._get(kind, spec)
            if obj is None:
                continue
            body: dict[str, Any] = {
                "metadata": {
                    "labels": labels(spec),
                    "resourceVersion": obj.metadata.resource_version,
                }
            }
            if kind == "deployment":
                body["spec"] = {"replicas": 0}
            api = self.apps if kind == "deployment" else self.core
            self._authorize(spec)
            self._call(
                getattr(api, f"patch_namespaced_{kind}"),
                name=resource_name(spec),
                namespace=self.settings.sample_namespace,
                body=body,
            )

    def ensure_deleted(self, spec: RuntimeSpec) -> None:
        for kind in ("deployment", "service"):
            obj = self._get(kind, spec)
            if obj is None:
                continue
            api = self.apps if kind == "deployment" else self.core
            self._authorize(spec)
            self._call(
                getattr(api, f"delete_namespaced_{kind}"),
                missing_ok=True,
                name=resource_name(spec),
                namespace=self.settings.sample_namespace,
                body={
                    "propagationPolicy": "Foreground",
                    "preconditions": {
                        "uid": obj.metadata.uid,
                        "resourceVersion": obj.metadata.resource_version,
                    },
                },
            )
