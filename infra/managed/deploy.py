"""Install a rendered ProtoHub development stack into an explicit Kubernetes context."""

import argparse
import base64
import binascii
import getpass
import json
import re
import secrets
import subprocess
import sys
import warnings
from pathlib import Path

import yaml
from render import DB_SECRET, GOOGLE_SECRET, LOCAL_ORIGINS, render


class DeploymentError(Exception):
    pass


def read_manifest(path):
    """Only accept the current renderer output, including its ordered policies."""
    try:
        objects = list(yaml.safe_load_all(path.read_text(encoding="utf-8")))
        by_name = {(obj["kind"], obj["metadata"]["name"]): obj for obj in objects}

        def image(name):
            pod = by_name["Deployment", name]["spec"]["template"]["spec"]
            return pod["containers"][0]["image"]

        cfg = by_name["ConfigMap", "protohub-config"]["data"]
        origins = cfg["PROTOHUB_CONSOLE_ORIGIN"], cfg["PROTOHUB_PREVIEW_ORIGIN"]
        api_env = {
            e["name"]: e.get("value")
            for e in by_name["Deployment", "api"]["spec"]["template"]["spec"]["containers"][0].get(
                "env", []
            )
        }
        ai = {}
        if api_env.get("PROTOHUB_AI_ENABLED") == "true":
            ai = {
                "ai_project": api_env["PROTOHUB_AI_VERTEX_PROJECT"],
                "ai_location": api_env["PROTOHUB_AI_VERTEX_LOCATION"],
                "ai_model": api_env["PROTOHUB_AI_MODEL"],
            }
        expected = render(
            image("api"),
            image("web"),
            cfg["PROTOHUB_SAMPLE_IMAGE"],
            image("db"),
            by_name["PersistentVolumeClaim", "protohub-db"]["spec"]["storageClassName"],
            by_name["Namespace", "protohub-system"]["metadata"]["labels"]["protohub.io/owner"],
            *(origins if origins != LOCAL_ORIGINS else ()),
            **ai,
        )
    except (KeyError, TypeError, IndexError, OSError, ValueError, yaml.YAMLError) as exc:
        raise DeploymentError("Invalid manifest. Generate it again with render.py.") from exc
    if objects != expected:
        raise DeploymentError("Manifest differs from the current renderer. Regenerate it.")
    return objects


OWNER_KEYS = ("protohub.io/owner", "protohub.io/profile", "app.kubernetes.io/managed-by")
SYSTEM = "protohub-system"
DATABASE_OBJECTS = {
    ("Namespace", None, SYSTEM),
    ("Namespace", None, "protohub-samples"),
    ("NetworkPolicy", SYSTEM, "system-ingress"),
    ("NetworkPolicy", "protohub-samples", "samples-default-deny"),
    ("PersistentVolumeClaim", SYSTEM, "protohub-db"),
    ("Deployment", SYSTEM, "db"),
    ("Service", SYSTEM, "db"),
}
CLIENT_ID = re.compile(r"[a-zA-Z0-9_-]+\.apps\.googleusercontent\.com")
CLIENT_SECRET = re.compile(r"[a-zA-Z0-9_-]{1,512}")


def validate_google_credentials(client_id, client_secret):
    if not isinstance(client_id, str) or len(client_id) > 512 or not CLIENT_ID.fullmatch(client_id):
        raise DeploymentError("Invalid Google OAuth web client ID.")
    if not isinstance(client_secret, str) or not CLIENT_SECRET.fullmatch(client_secret):
        raise DeploymentError("Invalid Google OAuth client secret.")
    return {"client-id": client_id, "client-secret": client_secret}


def prompt_google_credentials():
    try:
        with warnings.catch_warnings():
            # getpass normally falls back to echoing stdin if there is no secure terminal.
            warnings.simplefilter("error", getpass.GetPassWarning)
            client_id = getpass.getpass("Google OAuth web client ID: ")
            client_secret = getpass.getpass("Google OAuth web client secret: ")
    except (getpass.GetPassWarning, EOFError, OSError):
        raise DeploymentError("Run --configure-google in an interactive terminal.") from None
    return validate_google_credentials(client_id, client_secret)


def validate_existing_google_secret(secret):
    meta = secret.get("metadata", {})
    if (
        secret.get("immutable") is not True
        or secret.get("type") != "Opaque"
        or "kubectl.kubernetes.io/last-applied-configuration" in (meta.get("annotations") or {})
        or set(secret.get("data") or {}) != {"client-id", "client-secret"}
    ):
        raise DeploymentError("Existing Google OAuth Secret must be immutable and well-formed.")
    try:
        credentials = [
            base64.b64decode(secret["data"][key], validate=True).decode("ascii")
            for key in ("client-id", "client-secret")
        ]
    except (binascii.Error, ValueError, TypeError):
        raise DeploymentError("Invalid data in existing Google OAuth Secret.") from None
    validate_google_credentials(*credentials)
    return {
        "metadata": {
            "labels": meta.get("labels", {}),
            "deletionTimestamp": meta.get("deletionTimestamp"),
        }
    }


class Cluster:
    def __init__(self, context):
        if not context or context.startswith("-") or any(c.isspace() for c in context):
            raise DeploymentError("Supply an explicit kubeconfig context.")
        self.command = ["kubectl", "--context", context, "--request-timeout=30s"]

    def run(self, args, obj=None):
        result = subprocess.run(
            self.command + args,
            input=json.dumps(obj) if obj is not None else None,
            text=True,
            capture_output=True,
            timeout=60,
            check=False,
        )
        if result.returncode:
            # Admission errors can echo rejected manifest data, including Secret values.
            raise DeploymentError(f"kubectl {args[0]} failed (exit {result.returncode}).")
        return result.stdout.strip()

    def existing(self, kind, name, namespace=None):
        args = ["get", f"{kind}/{name}", "--ignore-not-found"]
        if namespace:
            args.extend(["--namespace", namespace])
        if kind == "Secret" and name == GOOGLE_SECRET:
            # Validate the two encoded fields in memory. No values leave this method.
            info = self.run(args + ["-o", "json"])
            return validate_existing_google_secret(json.loads(info)) if info else None
        if kind == "Secret":
            # Only metadata and key presence cross the subprocess boundary.
            fmt = (
                'go-template={{index .metadata.labels "protohub.io/owner"}}|'
                '{{index .metadata.labels "protohub.io/profile"}}|'
                '{{index .metadata.labels "app.kubernetes.io/managed-by"}}|'
                "{{if .data.password}}yes{{else}}no{{end}}|"
                '{{if index .data "database-url"}}yes{{else}}no{{end}}|'
                "{{.immutable}}|{{if .metadata.deletionTimestamp}}deleting{{else}}active{{end}}"
            )
            info = self.run(args + ["-o", fmt])
            if not info:
                return None
            fields = info.split("|")
            if len(fields) != 7 or fields[3:] != ["yes", "yes", "true", "active"]:
                raise DeploymentError("Existing database Secret is incomplete or being deleted.")
            return {"metadata": {"labels": dict(zip(OWNER_KEYS, fields[:3], strict=True))}}
        info = self.run(args + ["-o", "json"])
        return json.loads(info) if info else None

    def has_public_routes(self):
        resources = set(
            self.run(
                [
                    "api-resources",
                    "--api-group=gateway.networking.k8s.io",
                    "-o",
                    "name",
                ]
            ).splitlines()
        )
        gateway_kind = "gateways.gateway.networking.k8s.io"
        route_kind = "httproutes.gateway.networking.k8s.io"
        if not resources.intersection({gateway_kind, route_kind}):
            return False
        if not {gateway_kind, route_kind} <= resources:
            raise DeploymentError(
                "Gateway API discovery incomplete. Inspect it before redeploying."
            )
        gateway = self.existing(gateway_kind, "protohub-browser", SYSTEM)
        if not gateway or gateway["spec"]["gatewayClassName"] in {"gke-l7-rilb", "gke-l7-rilb-mc"}:
            return False
        # Do not depend on Accepted or deletion status: actual routing can lag the status.
        routes = json.loads(self.run(["get", route_kind, "--namespace", SYSTEM, "-o", "json"]))
        return any(
            parent.get("name") == "protohub-browser"
            and parent.get("namespace", SYSTEM) == SYSTEM
            and parent.get("kind", "Gateway") == "Gateway"
            and parent.get("group", "gateway.networking.k8s.io") == "gateway.networking.k8s.io"
            for route in routes["items"]
            for parent in route.get("spec", {}).get("parentRefs", [])
        )

    def install(self, obj, previous):
        meta = obj["metadata"]
        if previous:
            # Obtain the server-defaulted three-way merge without writing. Use PUT for the
            # actual change so the API checks the observed uid and resourceVersion atomically.
            merged = json.loads(
                self.run(
                    [
                        "apply",
                        "--dry-run=server",
                        "--field-manager=protohub-managed",
                        "-f",
                        "-",
                        "-o",
                        "json",
                    ],
                    obj,
                )
            )
            before = previous["metadata"]
            if any(merged["metadata"].get(k) != before[k] for k in ("uid", "resourceVersion")):
                raise DeploymentError("Resource changed since preflight. Inspect it and retry.")
            if merged != previous:
                self.run(["replace", "--field-manager=protohub-managed", "-f", "-"], merged)
        else:
            action = ["create", "--field-manager=protohub-managed"]
            if obj["kind"] != "Secret":
                action.append("--save-config")
            self.run(action + ["-f", "-"], obj)
        print(f"{obj['kind']}/{meta['name']}", flush=True)


def check_owner(existing, labels, kind, name):
    if existing:
        meta = existing["metadata"]
        if meta.get("deletionTimestamp") or any(
            meta.get("labels", {}).get(key) != value for key, value in labels.items()
        ):
            raise DeploymentError(f"Refusing to adopt a foreign or terminating {kind}/{name}.")


def install_secret(cluster, name, labels, data):
    secret = {
        "apiVersion": "v1",
        "kind": "Secret",
        "type": "Opaque",
        "immutable": True,
        "metadata": {"name": name, "namespace": SYSTEM, "labels": labels},
        "stringData": data,
    }
    cluster.install(secret, None)


def create_secret(cluster, labels):
    password = secrets.token_urlsafe(32)
    install_secret(
        cluster,
        DB_SECRET,
        labels,
        {
            "password": password,
            "database-url": f"postgresql+psycopg://protohub:{password}@db/protohub",
        },
    )


LAST_APPLIED = "kubectl.kubernetes.io/last-applied-configuration"


def contains_fields(live, desired):
    # Ignore Kubernetes-defaulted fields, while comparing requested values and list members.
    if isinstance(desired, dict):
        return isinstance(live, dict) and all(
            k in live and contains_fields(live[k], v) for k, v in desired.items()
        )
    if isinstance(desired, list):
        return (
            isinstance(live, list)
            and len(live) == len(desired)
            and all(contains_fields(a, b) for a, b in zip(live, desired, strict=True))
        )
    return live == desired


def changes_browser_release(objects, previous):
    for obj in objects:
        kind, meta = obj["kind"], obj["metadata"]
        if not (
            (kind == "Deployment" and meta["name"] in {"api", "web", "preview"})
            or (kind == "ConfigMap" and meta["name"] == "protohub-config")
        ):
            continue
        live = previous[kind, meta.get("namespace"), meta["name"]]
        if not live:
            return True
        try:
            last = json.loads(live["metadata"]["annotations"][LAST_APPLIED])
            if kind == "Deployment":
                desired = obj["spec"]["template"]
                if last["spec"]["template"] != desired or not contains_fields(
                    live["spec"]["template"], desired
                ):
                    return True
            else:
                desired = {k: v for k, v in obj["data"].items() if k != "PROTOHUB_SAMPLE_IMAGE"}
                for source in (last, live):
                    if {
                        k: v for k, v in source["data"].items() if k != "PROTOHUB_SAMPLE_IMAGE"
                    } != desired:
                        return True
        except (AttributeError, KeyError, TypeError, ValueError):
            return True
    return False


def load_google_client_file(path, console_origin):
    try:
        if not path.is_file():
            raise ValueError
        with path.open("rb") as source:
            data = source.read(65537)
        if len(data) > 65536:
            raise ValueError
        doc = json.loads(data)
        if not isinstance(doc, dict) or "installed" in doc or not isinstance(doc.get("web"), dict):
            raise ValueError
        web = doc["web"]
        if not all(
            isinstance(web.get(key), list) and console_origin in web[key]
            for key in ("javascript_origins", "redirect_uris")
        ):
            raise ValueError
    except (OSError, TypeError, ValueError, RecursionError):
        raise DeploymentError(
            "Provide a Google Web client JSON with the exact console origin in both registered URI lists."
        ) from None
    return validate_google_credentials(web.get("client_id"), web.get("client_secret"))


def deploy(
    cluster, objects, configure_google=False, google_client_file=None, *, prepare_database=False
):
    if prepare_database and (configure_google or google_client_file is not None):
        raise DeploymentError("Database preparation cannot be combined with Google credentials.")
    by_name = {(obj["kind"], obj["metadata"]["name"]): obj for obj in objects}
    ns_labels = by_name["Namespace", SYSTEM]["metadata"]["labels"]
    labels = {key: ns_labels[key] for key in OWNER_KEYS}
    storage = by_name["PersistentVolumeClaim", "protohub-db"]["spec"]["storageClassName"]
    if not cluster.existing("StorageClass", storage):
        raise DeploymentError(f"StorageClass {storage} does not exist.")

    # Complete ownership checks before writing, including on a partial retry.
    # Only create absent objects. Updates carry the observed resourceVersion.
    previous = {}
    for obj in objects:
        kind, meta = obj["kind"], obj["metadata"]
        namespace = meta.get("namespace")
        if namespace and not previous["Namespace", None, namespace]:
            # A fresh namespace cannot already contain any of the named resources.
            current = None
        else:
            current = cluster.existing(kind, meta["name"], namespace)
        check_owner(current, labels, kind, meta["name"])
        previous[kind, meta.get("namespace"), meta["name"]] = current

    existing_secret = None
    google_secret = None
    if previous["Namespace", None, SYSTEM]:
        existing_secret = cluster.existing("Secret", DB_SECRET, SYSTEM)
        if not prepare_database:
            google_secret = cluster.existing("Secret", GOOGLE_SECRET, SYSTEM)
    check_owner(google_secret, labels, "Secret", GOOGLE_SECRET)
    check_owner(existing_secret, labels, "Secret", DB_SECRET)
    prior_pvc = previous["PersistentVolumeClaim", SYSTEM, "protohub-db"]
    if prior_pvc:
        if not existing_secret:
            raise DeploymentError("Restore the original database Secret for the existing PVC.")
        if prior_pvc["spec"].get("storageClassName") != storage:
            raise DeploymentError("Existing database PVC has a different StorageClass.")

    if prepare_database:
        if any(live for key, live in previous.items() if key not in DATABASE_OBJECTS):
            raise DeploymentError(
                "Database preparation is only for a fresh or database-only stack."
            )
        db = previous["Deployment", SYSTEM, "db"]
        if db and not prior_pvc:
            raise DeploymentError("Restore the existing database PVC before preparing this stack.")
        if db and not contains_fields(
            db["spec"]["template"], by_name["Deployment", "db"]["spec"]["template"]
        ):
            raise DeploymentError(
                "Existing database workload differs; use the full release procedure."
            )

    if (
        previous["Namespace", None, SYSTEM]
        and (prepare_database or not google_secret or changes_browser_release(objects, previous))
        and (
            any(
                cluster.existing("NetworkPolicy", n, SYSTEM)
                for n in ("protohub-run-to-web", "protohub-run-to-preview")
            )
            or (
                prepare_database
                and any(
                    cluster.existing("Service", n, SYSTEM)
                    for n in ("protohub-run-web", "protohub-run-preview")
                )
            )
            or cluster.has_public_routes()
        )
    ):
        raise DeploymentError(
            "Remove the owned public ProtoHub HTTPRoutes and Cloud Run bridge policies before changing this release. "
            "Restore them after the rollout and live authentication checks."
        )
    credentials = None
    if prepare_database:
        objects = [
            o
            for o in objects
            if (o["kind"], o["metadata"].get("namespace"), o["metadata"]["name"])
            in DATABASE_OBJECTS
        ]
    elif not google_secret:
        if google_client_file is not None:
            origin = by_name["ConfigMap", "protohub-config"]["data"]["PROTOHUB_CONSOLE_ORIGIN"]
            credentials = load_google_client_file(google_client_file, origin)
        elif configure_google:
            credentials = prompt_google_credentials()
        else:
            raise DeploymentError(
                "Google OAuth Secret is missing. Re-run with --configure-google or --google-client-file PATH."
            )

    for obj in objects:
        kind, meta = obj["kind"], obj["metadata"]
        if kind == "PersistentVolumeClaim" and not existing_secret:
            create_secret(cluster, labels)
        try:
            cluster.install(obj, previous[kind, meta.get("namespace"), meta["name"]])
            if kind == "Namespace" and meta["name"] == SYSTEM and credentials is not None:
                install_secret(cluster, GOOGLE_SECRET, labels, credentials)
        except DeploymentError as exc:
            raise DeploymentError(f"{kind}/{meta['name']}: {exc}") from exc


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--context", required=True)
    parser.add_argument("--manifest", required=True, type=Path)
    credential_source = parser.add_mutually_exclusive_group()
    credential_source.add_argument(
        "--prepare-database",
        action="store_true",
        help="Prepare only the private PostgreSQL database in a fresh stack; OAuth is not required.",
    )
    credential_source.add_argument(
        "--configure-google",
        action="store_true",
        help="Prompt privately for Google OAuth credentials if the managed Secret is absent.",
    )
    credential_source.add_argument(
        "--google-client-file",
        type=Path,
        help="Private local Web OAuth client JSON. Read only on initial configuration.",
    )
    args = parser.parse_args()
    try:
        deploy(
            Cluster(args.context),
            read_manifest(args.manifest),
            args.configure_google,
            args.google_client_file,
            prepare_database=args.prepare_database,
        )
    except (DeploymentError, OSError, subprocess.TimeoutExpired) as exc:
        print(f"Deployment stopped: {exc}", file=sys.stderr)
        return 1
    if args.prepare_database:
        print("Database resources installed. Check PVC binding and PostgreSQL readiness.")
    else:
        print("Manifests applied. Check rollouts and run the sample before reporting readiness.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
