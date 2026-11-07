"""Render the GKE/AKS development deployment offline from the local Kubernetes templates."""

import argparse
import re
import sys
from pathlib import Path
from string import Template

import yaml

HERE = Path(__file__).resolve().parent
BASE = HERE.parent / "kubernetes"
DB_SECRET = "protohub-db-credentials"
GOOGLE_SECRET = "protohub-google-oauth"
DNS_LABEL = re.compile(r"[a-z0-9](?:[-a-z0-9]{0,61}[a-z0-9])?")
# Require an explicit registry hostname, repository path and immutable sha256 digest.
IMAGE = re.compile(
    r"[a-z0-9]+(?:[-.][a-z0-9]+)+(?:|:[1-9][0-9]{0,4})/"
    r"(?:[a-z0-9]+(?:[._-]+[a-z0-9]+)*/)*[a-z0-9]+(?:[._-]+[a-z0-9]+)*"
    r"@sha256:[0-9a-f]{64}"
)


def validated_image(image):
    if not isinstance(image, str) or len(image) > 320 or not IMAGE.fullmatch(image):
        raise ValueError("Use registry-host/repository/image@sha256:<64 lowercase hex digits>.")
    return image


def secret_env(name, key, secret=DB_SECRET):
    return {"name": name, "valueFrom": {"secretKeyRef": {"name": secret, "key": key}}}


def load(path, **variables):
    content = Template(path.read_text(encoding="utf-8")).substitute(variables)
    return list(yaml.safe_load_all(content))


def configure_deployment(obj, images):
    deployment = obj["metadata"]["name"]
    pod = obj["spec"]["template"]["spec"]
    for container in [*pod.get("initContainers", []), *pod["containers"]]:
        if deployment == "db":
            container["image"] = images["postgres"]
            container["env"] = [
                secret_env("POSTGRES_PASSWORD", "password")
                if item["name"] == "POSTGRES_PASSWORD"
                else item
                for item in container["env"]
            ]
        elif deployment == "web":
            container["image"] = images["web"]
        elif deployment in {"api", "worker", "preview"}:
            # The Alembic init container uses the same credentials as the API.
            container["image"] = images["server"]
            env = [
                item for item in container.get("env", []) if item["name"] != "PROTOHUB_LLM_API_KEY"
            ]
            env.append(secret_env("PROTOHUB_DATABASE_URL", "database-url"))
            if container["name"] in {"api", "preview"}:
                env.append({"name": "PROTOHUB_GOOGLE_LOGIN", "value": "true"})
            if container["name"] == "api":
                env.extend(
                    [
                        secret_env("PROTOHUB_GOOGLE_CLIENT_ID", "client-id", GOOGLE_SECRET),
                        secret_env("PROTOHUB_GOOGLE_CLIENT_SECRET", "client-secret", GOOGLE_SECRET),
                    ]
                )
            container["env"] = env
        else:
            raise ValueError(f"Unmapped deployment in the base templates: {deployment}")


LOCAL_ORIGINS = ("http://localhost:8080", "http://localhost:8081")


def validate_origins(console_origin, preview_origin):
    """Validate two distinct HTTPS DNS origins for the console and preview."""
    for origin in (console_origin, preview_origin):
        host = origin.removeprefix("https://") if isinstance(origin, str) else ""
        parts = host.split(".")
        if (
            not isinstance(origin, str)
            or not origin.startswith("https://")
            or len(host) > 253
            or len(parts) < 2
            or not all(DNS_LABEL.fullmatch(part) for part in parts)
            or not re.fullmatch(r"[a-z][a-z0-9-]*", parts[-1])
            or parts[-1] == "localhost"
        ):
            raise ValueError("Use two canonical https:// DNS origins on port 443, without paths.")
    if console_origin == preview_origin:
        raise ValueError("Console and preview must use distinct DNS hosts.")
    return console_origin, preview_origin


def render(
    server_image,
    web_image,
    sample_image,
    postgres_image,
    storage_class,
    owner,
    console_origin=None,
    preview_origin=None,
    ai_project=None,
    ai_location="global",
    ai_model="gemini-3.5-flash-lite",
):
    origins = (
        LOCAL_ORIGINS
        if console_origin is None and preview_origin is None
        else validate_origins(console_origin, preview_origin)
    )
    ai_enabled = ai_project is not None
    if ai_enabled:
        if (
            not isinstance(ai_project, str)
            or not re.fullmatch(r"[a-z][a-z0-9-]{4,61}[a-z0-9]", ai_project)
            or not isinstance(ai_location, str)
            or not re.fullmatch(r"(global|[a-z]+-[a-z]+[0-9])", ai_location)
            or not isinstance(ai_model, str)
            or not re.fullmatch(r"gemini-[a-z0-9.-]{1,110}", ai_model)
        ):
            raise ValueError("Use an explicit Vertex project, location and Gemini model.")
    elif ai_location != "global" or ai_model != "gemini-3.5-flash-lite":
        raise ValueError("AI options require --ai-project.")
    images = {
        "server": validated_image(server_image),
        "web": validated_image(web_image),
        "postgres": validated_image(postgres_image),
    }
    sample_image = validated_image(sample_image)
    if not isinstance(owner, str) or not DNS_LABEL.fullmatch(owner):
        raise ValueError("Use a stable lowercase DNS label (1–63 characters) for owner.")
    if (
        not isinstance(storage_class, str)
        or len(storage_class) > 253
        or not all(DNS_LABEL.fullmatch(label) for label in storage_class.split("."))
    ):
        raise ValueError("Use the name of an approved Kubernetes StorageClass.")

    namespaces = load(BASE / "namespaces.yaml.in", OWNER_ID=owner)
    for ns in namespaces:
        ns["metadata"]["labels"].update(
            {
                "pod-security.kubernetes.io/enforce": "restricted",
                "pod-security.kubernetes.io/enforce-version": "latest",
            }
        )
    policies = load(HERE / "network.yaml")
    rbac = load(BASE / "rbac.yaml")
    stack = load(
        BASE / "stack.yaml.in",
        ENVIRONMENT="production",
        CONSOLE_PORT="8080",
        PREVIEW_PORT="8081",
        BUILD_TAG="managed",
    )
    for obj in stack:
        kind = obj["kind"]
        if kind == "ConfigMap":
            del obj["data"]["PROTOHUB_DATABASE_URL"]
            obj["data"]["PROTOHUB_SAMPLE_IMAGE"] = sample_image
            obj["data"]["PROTOHUB_CONSOLE_ORIGIN"], obj["data"]["PROTOHUB_PREVIEW_ORIGIN"] = origins
        elif kind == "PersistentVolumeClaim":
            obj["spec"]["storageClassName"] = storage_class
        elif kind == "Deployment":
            configure_deployment(obj, images)
            if ai_enabled and obj["metadata"]["name"] == "api":
                pod = obj["spec"]["template"]["spec"]
                pod["serviceAccountName"] = "protohub-api"
                # Workload Identity supplies Google credentials; no Kubernetes token is mounted.
                pod["automountServiceAccountToken"] = False
                api = next(c for c in pod["containers"] if c["name"] == "api")
                api["env"].extend(
                    {"name": key, "value": value}
                    for key, value in {
                        "PROTOHUB_AI_ENABLED": "true",
                        "PROTOHUB_AI_VERTEX_PROJECT": ai_project,
                        "PROTOHUB_AI_VERTEX_LOCATION": ai_location,
                        "PROTOHUB_AI_MODEL": ai_model,
                    }.items()
                )
            if obj["metadata"]["name"] in {"api", "worker", "preview"}:
                annotations = obj["spec"]["template"]["metadata"].setdefault("annotations", {})
                (
                    annotations["protohub.io/console-origin"],
                    annotations["protohub.io/preview-origin"],
                ) = origins
            if obj["metadata"]["name"] == "worker":
                # envFrom is read only at startup. A sample-only release must roll the worker.
                pod_meta = obj["spec"]["template"]["metadata"]
                pod_meta.setdefault("annotations", {})["protohub.io/sample-image"] = sample_image
        elif kind == "Service":
            obj["spec"]["type"] = "ClusterIP"
            for port in obj["spec"]["ports"]:
                port.pop("nodePort", None)
        else:
            raise ValueError(f"Unmapped kind in the base stack: {kind}")
    ai_accounts = (
        [
            {
                "apiVersion": "v1",
                "kind": "ServiceAccount",
                "metadata": {"name": "protohub-api", "namespace": "protohub-system"},
                "automountServiceAccountToken": False,
            }
        ]
        if ai_enabled
        else []
    )
    objects = namespaces + policies + rbac + ai_accounts + stack
    for obj in objects:
        obj["metadata"].setdefault("labels", {}).update(
            {
                "app.kubernetes.io/managed-by": "protohub",
                "protohub.io/profile": "managed",
                "protohub.io/owner": owner,
            }
        )
    return objects


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in (
        "server-image",
        "web-image",
        "sample-image",
        "postgres-image",
        "storage-class",
        "owner",
    ):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--ai-project", help="Explicit Vertex quota project; enables real Gemini.")
    parser.add_argument("--ai-location", default="global")
    parser.add_argument("--ai-model", default="gemini-3.5-flash-lite")
    parser.add_argument("--console-origin", help="Approved HTTPS origin of the console.")
    parser.add_argument("--preview-origin", help="Approved HTTPS origin on a separate host.")
    try:
        objects = render(**vars(parser.parse_args()))
    except (OSError, KeyError, ValueError, yaml.YAMLError) as exc:
        parser.exit(1, f"Render failed: {exc}\n")
    yaml.safe_dump_all(objects, sys.stdout, sort_keys=False)


if __name__ == "__main__":
    main()
