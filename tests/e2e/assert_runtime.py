"""Real HTTP, Kubernetes observation, TTL, restart and permission evidence."""

import argparse
import json
import os
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import ProxyHandler, Request, build_opener

parser = argparse.ArgumentParser()
parser.add_argument("--gate", choices=["e2e", "security"], required=True)
parser.add_argument("--report", type=Path, required=True)
args = parser.parse_args()
console = os.environ["PROTOHUB_CONSOLE_URL"]
preview = os.environ["PROTOHUB_PREVIEW_URL"]
context = "kind-" + os.environ["PROTOHUB_CLUSTER_NAME"]
opener = build_opener(ProxyHandler({}))
checks, registered = [], []


def http(path, method="GET", payload=None, headers=None, base=console):
    request_headers = {
        "Content-Type": "application/json",
        "X-ProtoHub-Client": "console",
        **(headers or {}),
    }
    data = json.dumps(payload if payload is not None else {}).encode() if method != "GET" else None
    request = Request(base + path, data=data, method=method, headers=request_headers)
    try:
        with opener.open(request, timeout=10) as response:
            return response.status, response.read()
    except HTTPError as exc:
        return exc.code, exc.read()


def api(path, method="GET", payload=None):
    status, body = http("/api/v1" + path, method, payload)
    assert status in {200, 201, 202}, (path, status, body[:200])
    return json.loads(body)


def kube(*argv, namespace="protohub-system", expect=0):
    result = subprocess.run(
        ["kubectl", "--context", context, "-n", namespace, *argv],
        capture_output=True,
        text=True,
        timeout=320,
        check=False,
    )
    if expect is not None:
        assert result.returncode == expect, (
            argv[:2],
            result.returncode,
            result.stderr[:200],
        )
    return result.stdout.strip()


def wait(predicate, timeout=120):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            value = predicate()
            if value:
                return value
        except (OSError, ValueError, AssertionError):
            pass
        time.sleep(0.5)
    raise AssertionError("Timed out waiting for observed condition")


def status(sandbox_id, desired):
    return wait(lambda: api(f"/sandboxes/{sandbox_id}")["status"] == desired)


def create(name, ttl=900):
    value = api(
        "/sandboxes",
        "POST",
        {"name": name, "template_id": "hello-web", "ttl_seconds": ttl},
    )
    registered.append(value["id"])
    return value["id"]


def resources(sandbox_id):
    return json.loads(
        kube(
            "get",
            "deployments,services,pods",
            "-l",
            f"protohub.io/sandbox-id={sandbox_id}",
            "-o",
            "json",
            namespace="protohub-samples",
        )
    )["items"]


def no_pods(sandbox_id):
    return not any(item["kind"] == "Pod" for item in resources(sandbox_id))


def passed(name):
    checks.append({"name": name, "status": "PASS"})
    print("PASS real " + name, flush=True)


try:
    assert api("/system")["runtime_mode"] == "real-kind"
    wait(
        lambda: (
            not json.loads(
                kube("get", "deployments,services,pods", "-o", "json", namespace="protohub-samples")
            )["items"]
        )
    )
    one, two = create("Real fixture one", 60), create("Real fixture two")
    with ThreadPoolExecutor(max_workers=4) as pool:
        operations = list(pool.map(lambda _: api(f"/sandboxes/{one}/start", "POST"), range(4)))
    assert len({op["id"] for op in operations}) == 1
    api(f"/sandboxes/{two}/start", "POST")
    status(one, "running")
    status(two, "running")
    assert sum(item["kind"] == "Deployment" for item in resources(one)) == 1
    for sandbox_id in (one, two):
        value = api(f"/sandboxes/{sandbox_id}")
        assert value["preview_url"] == f"{preview}/apps/{sandbox_id}/"
        assert http(f"/apps/{sandbox_id}/healthz", base=preview)[0] == 200
    passed("duplicate start, real readiness and independent URLs")

    if args.gate == "security":
        for namespace, verb, resource, expected in (
            ("protohub-samples", "create", "deployments.apps", "yes"),
            ("protohub-samples", "get", "secrets", "no"),
            ("protohub-samples", "create", "roles.rbac.authorization.k8s.io", "no"),
            ("protohub-samples", "create", "pods/exec", "no"),
            ("protohub-system", "create", "deployments.apps", "no"),
        ):
            answer = kube(
                "auth",
                "can-i",
                verb,
                resource,
                "--as=system:serviceaccount:protohub-system:protohub-worker",
                namespace=namespace,
                expect=None,
            )
            assert answer == expected, (namespace, verb, resource, answer)
        passed("live RBAC allow and deny")
        for sandbox_id in (one, two):
            pods = [item for item in resources(sandbox_id) if item["kind"] == "Pod"]
            assert pods
            for pod in pods:
                spec = pod["spec"]
                assert spec["automountServiceAccountToken"] is False
                assert not spec.get("hostNetwork")
                assert not any("hostPath" in value for value in spec.get("volumes", []))
                assert spec["securityContext"]["runAsNonRoot"] is True
                for container in spec["containers"]:
                    security = container["securityContext"]
                    assert security["allowPrivilegeEscalation"] is False
                    assert security["readOnlyRootFilesystem"] is True
                    assert "ALL" in security["capabilities"]["drop"]
                    assert container["resources"]["limits"]["memory"]
                    assert container["resources"]["limits"]["cpu"]
        for deployment in ("api", "preview"):
            spec = json.loads(kube("get", "deployment", deployment, "-o", "json"))["spec"][
                "template"
            ]["spec"]
            assert spec["automountServiceAccountToken"] is False
        passed("live Pod security configuration and credential separation")
        assert (
            http(
                "/api/v1/sandboxes",
                "POST",
                {"name": "Rejected", "template_id": "arbitrary"},
            )[0]
            == 422
        )
        assert (
            http(
                "/api/v1/sandboxes",
                "POST",
                {"name": "Rejected", "template_id": "hello-web", "image": "untrusted"},
            )[0]
            == 422
        )
        assert (
            http("/api/v1/sandboxes", "POST", {}, {"Origin": "http://untrusted.example"})[0] == 403
        )
        assert http("/api/v1/sandboxes", headers={"Host": "untrusted.example"})[0] == 403
        assert http("/api/v1/sandboxes", "POST", {}, {"X-ProtoHub-Client": ""})[0] == 403
        assert http(f"/apps/{one}/", method="POST", base=preview)[0] in {403, 405}
        assert http(f"/apps/{one}/http://127.0.0.1/", base=preview)[0] in {400, 404}
        assert http(f"/apps/{one}/", headers={"Host": "untrusted.example"}, base=preview)[0] == 403
        passed("live template, Origin, Host and preview input rejection")
    else:
        # Queue remains durable while worker process is absent; restart never drops records.
        kube("scale", "deployment/worker", "--replicas=0")
        wait(
            lambda: (
                not json.loads(kube("get", "pods", "-l", "app=protohub-worker", "-o", "json"))[
                    "items"
                ]
            )
        )
        queued = create("Worker recovery")
        api(f"/sandboxes/{queued}/start", "POST")
        assert api(f"/sandboxes/{queued}")["status"] == "starting"
        kube("scale", "deployment/worker", "--replicas=1")
        kube("rollout", "status", "deployment/worker", "--timeout=180s")
        status(queued, "running")
        kube("rollout", "restart", "deployment/api")
        kube("rollout", "status", "deployment/api", "--timeout=180s")
        assert api(f"/sandboxes/{queued}")["name"] == "Worker recovery"
        passed("queue recovery and API/worker restart persistence")

        config = json.loads(kube("get", "configmap", "protohub-config", "-o", "json"))["data"]
        recovery = create("Running lease recovery")
        try:
            kube(
                "set",
                "env",
                "deployment/worker",
                "PROTOHUB_SAMPLE_IMAGE=protohub/hello-web:missing-test-image",
                "PROTOHUB_OPERATION_TIMEOUT_SECONDS=90",
            )
            kube("rollout", "status", "deployment/worker", "--timeout=180s")
            operation = api(f"/sandboxes/{recovery}/start", "POST")
            wait(lambda: api(f"/operations/{operation['id']}")["status"] == "running")
            assert api(f"/operations/{operation['id']}")["attempt_count"] == 1
            pods = json.loads(kube("get", "pods", "-l", "app=protohub-worker", "-o", "json"))[
                "items"
            ]
            assert len(pods) == 1 and pods[0]["metadata"]["labels"]["app"] == "protohub-worker"
            kube(
                "delete",
                "pod",
                pods[0]["metadata"]["name"],
                "--grace-period=0",
                "--force",
                "--wait=false",
            )
            kube(
                "set",
                "env",
                "deployment/worker",
                "PROTOHUB_SAMPLE_IMAGE=" + config["PROTOHUB_SAMPLE_IMAGE"],
                "PROTOHUB_OPERATION_TIMEOUT_SECONDS-",
            )
            kube("rollout", "status", "deployment/worker", "--timeout=180s")
            status(recovery, "running")
            recovered = api(f"/operations/{operation['id']}")
            assert recovered["status"] == "succeeded" and recovered["attempt_count"] >= 2
        finally:
            kube(
                "set",
                "env",
                "deployment/worker",
                "PROTOHUB_SAMPLE_IMAGE-",
                "PROTOHUB_OPERATION_TIMEOUT_SECONDS-",
            )
            kube("rollout", "status", "deployment/worker", "--timeout=180s")
        passed("running job recovers after real worker death and lease expiry")

        racing = create("Start then stop")
        api(f"/sandboxes/{racing}/start", "POST")
        api(f"/sandboxes/{racing}/stop", "POST")
        status(racing, "stopped")
        wait(lambda: no_pods(racing))
        time.sleep(6)
        assert api(f"/sandboxes/{racing}")["status"] == "stopped"
        assert no_pods(racing)
        passed("start superseded by stop stays stopped")

        # Inject a real partial creation failure in this dedicated cluster only.
        role = json.loads(
            kube(
                "get",
                "role",
                "protohub-worker",
                "-o",
                "json",
                namespace="protohub-samples",
            )
        )
        original_verbs = role["rules"][0]["verbs"]
        partial = create("Partial creation failure")
        try:
            kube(
                "patch",
                "role",
                "protohub-worker",
                "--type=json",
                "-p",
                json.dumps(
                    [
                        {
                            "op": "replace",
                            "path": "/rules/0/verbs",
                            "value": [v for v in original_verbs if v != "create"],
                        }
                    ]
                ),
                namespace="protohub-samples",
            )
            api(f"/sandboxes/{partial}/start", "POST")
            status(partial, "failed")
            assert api(f"/sandboxes/{partial}")["error"]
            wait(lambda: no_pods(partial))
            assert http(f"/apps/{partial}/", base=preview)[0] in {404, 409, 503}
        finally:
            kube(
                "patch",
                "role",
                "protohub-worker",
                "--type=json",
                "-p",
                json.dumps(
                    [
                        {
                            "op": "replace",
                            "path": "/rules/0/verbs",
                            "value": original_verbs,
                        }
                    ]
                ),
                namespace="protohub-samples",
            )
        passed("real partial failure records safe error and cannot preview")

        timeout_app = create("Readiness timeout")
        try:
            kube(
                "set",
                "env",
                "deployment/worker",
                "PROTOHUB_SAMPLE_IMAGE=protohub/hello-web:missing-test-image",
                "PROTOHUB_OPERATION_TIMEOUT_SECONDS=5",
            )
            kube("rollout", "status", "deployment/worker", "--timeout=180s")
            api(f"/sandboxes/{timeout_app}/start", "POST")
            status(
                timeout_app,
                "failed",
            )
            assert api(f"/sandboxes/{timeout_app}")["preview_url"] is None
            wait(lambda: no_pods(timeout_app))
        finally:
            kube(
                "set",
                "env",
                "deployment/worker",
                "PROTOHUB_SAMPLE_IMAGE=" + config["PROTOHUB_SAMPLE_IMAGE"],
                "PROTOHUB_OPERATION_TIMEOUT_SECONDS-",
            )
            kube("rollout", "status", "deployment/worker", "--timeout=180s")
        passed("real readiness timeout cannot claim Ready")

        status(one, "stopped")
        wait(lambda: no_pods(one))
        assert api(f"/sandboxes/{one}")["name"] == "Real fixture one"
        assert http(f"/apps/{one}/", base=preview)[0] in {404, 409, 503}
        assert api(f"/sandboxes/{two}")["status"] == "running"
        assert http(f"/apps/{two}/healthz", base=preview)[0] == 200
        passed("TTL stops real Pods, retains record and leaves other application running")
finally:
    for sandbox_id in registered:
        api(f"/sandboxes/{sandbox_id}", "DELETE")
        status(sandbox_id, "deleted")
        wait(lambda sandbox_id=sandbox_id: not resources(sandbox_id))
        assert http(f"/apps/{sandbox_id}/", base=preview)[0] in {404, 409, 503}
    passed("delete removes owned Pod/Service/Deployment and preview route")
    (args.report / "runtime-checks.json").write_text(
        json.dumps(
            {
                "checks": checks,
                "sandbox_ids": registered,
                "context": context,
                "cleanup": "all fixture sandbox resources absent",
            },
            indent=2,
        ),
        encoding="utf-8",
    )
