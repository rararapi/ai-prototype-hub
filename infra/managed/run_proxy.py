"""Render a Cloud Run frontend offline, or use verify to inspect a deployed pair read-only."""

import argparse
import http.client
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
PORTS = {"web": 8080, "preview": 8081}
SERVICE_NAME = re.compile(r"[a-z](?:[a-z0-9-]{0,47}[a-z0-9])?")
NETWORK_NAME = re.compile(r"[a-z](?:[a-z0-9-]{0,61}[a-z0-9])?")
ACCOUNT = re.compile(
    r"[a-z][a-z0-9-]{4,28}[a-z0-9]@[a-z][a-z0-9-]{4,28}[a-z0-9]\.iam\.gserviceaccount\.com"
)


# The public OCI index and its Linux/amd64 entry are independently pinned. Update both
# on an image change; Cloud Run reports the selected child through its registry mirror.
LINUX_AMD64 = {
    "sha256:0e52bd054126cdc040b1276c0af347aeb02a41b9cfe305d6094767ac30e97949": "sha256:84ed8c0dd296c188bfc24ed506f46589e9285fb0b11cf3a04d91d524d3067e11",
}


def runtime_image():
    dockerfile = (ROOT / "infra/docker/web.Dockerfile").read_text(encoding="utf-8")
    match = re.search(
        r"^FROM nginx:[^\s@]+@(sha256:[a-f0-9]{64})(?: AS runtime)?$", dockerfile, re.M
    )
    if not match:
        raise ValueError("The web Dockerfile must pin its nginx runtime by SHA-256 digest.")
    return "docker.io/library/nginx@" + match[1]


def nginx_config(role, parked):
    if role not in PORTS:
        raise ValueError("Unknown proxy role.")
    routes = """
        location = /edge-healthz { return 200 'ok'; }
        location / { return 503; }
"""
    if not parked:
        host = f"protohub-run-{role}.protohub-system.svc.protohub.gke.internal:{PORTS[role]}"
        if role == "web":
            app_route = """
        proxy_hide_header X-Frame-Options;
        add_header X-Frame-Options DENY always;
        location / { proxy_pass http://$backend$request_uri; }
"""
        else:
            app_route = """
        location /apps/ {
            if ($request_uri !~ "^/apps/") { return 404; }
            proxy_pass http://$backend$request_uri;
        }
        location / { return 404; }
"""
        # A variable forces Nginx to resolve the headless Service again as Pod IPs change.
        # $request_uri preserves escaping and the original query. The authority is fixed.
        routes = f"""
        include /tmp/protohub-dns.conf;
        set $backend {host};
        proxy_http_version 1.1;
        proxy_pass_request_headers off;
        proxy_set_header Host localhost;
        proxy_set_header Connection "";
        proxy_set_header Authorization $http_authorization;
        proxy_set_header Origin $http_origin;
        proxy_set_header Accept $http_accept;
        proxy_set_header Content-Type $http_content_type;
        proxy_set_header Access-Control-Request-Method $http_access_control_request_method;
        proxy_set_header Access-Control-Request-Headers $http_access_control_request_headers;
        proxy_hide_header Set-Cookie;
        proxy_ignore_headers X-Accel-Redirect;
        proxy_redirect off;
        proxy_connect_timeout 5s;
        proxy_read_timeout 35s;
"""
        if role == "web":
            routes += """
        proxy_set_header X-ProtoHub-Client $http_x_protohub_client;
        proxy_set_header X-Requested-With $http_x_requested_with;
"""
        routes += (
            """
        location = /edge-healthz { proxy_pass http://$backend/healthz; }
"""
            + app_route
        )
    return (
        """worker_processes 1;
pid /tmp/protohub-nginx.pid;
error_log stderr warn;
events { worker_connections 256; }
http {
    access_log off;
    client_body_temp_path /tmp/protohub-client;
    proxy_temp_path /tmp/protohub-proxy;
    fastcgi_temp_path /tmp/protohub-fastcgi;
    uwsgi_temp_path /tmp/protohub-uwsgi;
    scgi_temp_path /tmp/protohub-scgi;
    server {
        listen 8080 default_server;
        server_name _;
        client_max_body_size 64k;
"""
        + routes
        + "    }\n}\n"
    )


def command(config, parked):
    setup = ""
    if not parked:
        # Nameservers come from the platform's VPC resolver configuration, never the visitor.
        setup = """dns=$(awk '$1 == "nameserver" && $2 ~ /^[0-9.]+$/ {print $2; exit}' /etc/resolv.conf)
printf 'resolver %s valid=15s ipv6=off; resolver_timeout 3s;\\n' "${dns:-169.254.169.254}" >/tmp/protohub-dns.conf
"""
    return (
        setup
        + "cat >/tmp/protohub-nginx.conf <<'NGINX'\n"
        + config
        + ("NGINX\nexec nginx -c /tmp/protohub-nginx.conf -g 'daemon off;'\n")
    )


def render(
    role, service, region, service_account, network, subnet, parked=True, owner="protohub-managed"
):
    if not NETWORK_NAME.fullmatch(owner):
        raise ValueError("Use a stable lowercase owner label.")
    if not SERVICE_NAME.fullmatch(service):
        raise ValueError("Use a lowercase Cloud Run service name (1–49 characters).")
    if not re.fullmatch(r"[a-z]+-[a-z]+[0-9]+", region):
        raise ValueError("Use a Google Cloud region name.")
    if not ACCOUNT.fullmatch(service_account):
        raise ValueError("Use a dedicated user-managed service-account email.")
    if not NETWORK_NAME.fullmatch(network) or not NETWORK_NAME.fullmatch(subnet):
        raise ValueError("Use network and subnet names in the service project.")
    container = {
        "image": runtime_image(),
        "command": ["/bin/sh"],
        "args": ["-ec", command(nginx_config(role, parked), parked)],
        "ports": [{"containerPort": 8080}],
        "resources": {"limits": {"cpu": "1", "memory": "512Mi"}},
        "startupProbe": {
            "httpGet": {"path": "/edge-healthz", "port": 8080},
            "periodSeconds": 5,
            "timeoutSeconds": 4,
            "failureThreshold": 30,
        },
    }
    interfaces = json.dumps([{"network": network, "subnetwork": subnet}], separators=(",", ":"))
    return {
        "apiVersion": "serving.knative.dev/v1",
        "kind": "Service",
        "metadata": {
            "name": service,
            "labels": {
                "cloud.googleapis.com/location": region,
                "protohub-role": role,
                "protohub-profile": PROFILE,
                "protohub-owner": owner,
            },
            "annotations": {
                "run.googleapis.com/ingress": "all",
                "run.googleapis.com/invoker-iam-disabled": "false",
                "run.googleapis.com/minScale": "0",
                "run.googleapis.com/maxScale": "1",
            },
        },
        "spec": {
            "template": {
                "metadata": {
                    "annotations": {
                        "run.googleapis.com/network-interfaces": interfaces,
                        "run.googleapis.com/vpc-access-egress": "private-ranges-only",
                        "run.googleapis.com/cpu-throttling": "true",
                        "run.googleapis.com/execution-environment": "gen2",
                        "autoscaling.knative.dev/minScale": "0",
                        "autoscaling.knative.dev/maxScale": "1",
                    }
                },
                "spec": {
                    "serviceAccountName": service_account,
                    "containerConcurrency": 32,
                    "timeoutSeconds": 45,
                    "containers": [container],
                },
            },
            "traffic": [{"latestRevision": True, "percent": 100}],
        },
    }


STAGES = ("legacy-parked", "parked", "live-private", "live-public")
PROJECT = re.compile(r"[a-z][a-z0-9-]{4,28}[a-z0-9]")
REGION = re.compile(r"[a-z]+-[a-z]+[0-9]+")
PROFILE = "gke-headless"
DEFAULT_OWNER = "protohub-managed"


def require(value, message):
    if not value:
        raise ValueError(message)


def cloud(*args):
    """Never pass tokens to the shell or echo gcloud errors, tokens or service configuration."""
    binary = shutil.which("gcloud")
    require(binary, "Google Cloud CLI is not on PATH.")
    result = subprocess.run(
        [binary, *args, "--quiet"], capture_output=True, text=True, check=False, timeout=45
    )
    require(
        result.returncode == 0,
        "A read-only gcloud call failed. Check the active account and its permissions.",
    )
    return result.stdout.strip()


def reported_url(service, project_number, region, metadata, status, requested):
    primary = status.get("url")
    deterministic = f"https://{service}-{project_number}.{region}.run.app"
    # Only accept the provider's primary URL or its known project/region-specific alias.
    aliases = json.loads(metadata.get("annotations", {}).get("run.googleapis.com/urls", "[]"))
    require(
        isinstance(aliases, list) and isinstance(primary, str),
        "Cloud Run did not report service URLs.",
    )
    reported = [primary, *aliases]
    selected = requested or (deterministic if deterministic in reported else primary)
    prefix = re.escape(service + "-")
    valid_host = re.fullmatch(
        r"https://" + prefix + r"[a-z0-9]+(?:-[a-z0-9]+)*(?:\.[a-z0-9-]+){0,2}\.run\.app",
        selected or "",
    )
    require(
        selected in reported
        and selected in (primary, deterministic)
        and valid_host
        and "---" not in selected,
        "Requested URL is not a verified, untagged run.app service origin.",
    )
    return selected


def same_network_resource(value, name, path, project, number):
    # gcloud may expand the same-project short names into Compute resource references.
    return value == name or any(
        value
        in (
            f"projects/{p}/{path}/{name}",
            f"https://www.googleapis.com/compute/v1/projects/{p}/{path}/{name}",
        )
        for p in (project, number)
    )


def inspect_template(template, *, role, parked, identity, network, subnet, project, number, region):
    spec = template.get("spec", {})
    annotations = template.get("metadata", {}).get("annotations", {})
    require(
        spec.get("serviceAccountName") == identity and not spec.get("volumes"),
        "The proxy service identity or volumes do not match the release profile.",
    )
    require(
        annotations.get("run.googleapis.com/vpc-access-egress") == "private-ranges-only"
        and not annotations.get("run.googleapis.com/vpc-access-connector"),
        "The proxy must use Direct VPC private-ranges-only egress.",
    )
    interfaces = json.loads(annotations.get("run.googleapis.com/network-interfaces", "[]"))
    require(
        isinstance(interfaces, list)
        and len(interfaces) == 1
        and isinstance(interfaces[0], dict)
        and same_network_resource(
            interfaces[0].get("network"), network, "global/networks", project, number
        )
        and same_network_resource(
            interfaces[0].get("subnetwork"),
            subnet,
            f"regions/{region}/subnetworks",
            project,
            number,
        )
        and not interfaces[0].get("tags"),
        "Wrong Direct VPC network or subnet.",
    )
    require(
        annotations.get("autoscaling.knative.dev/minScale", "0") == "0"
        and annotations.get("autoscaling.knative.dev/maxScale") == "1"
        and annotations.get("run.googleapis.com/cpu-throttling", "true") == "true"
        and annotations.get("run.googleapis.com/execution-environment") == "gen2",
        "Unexpected revision scaling, CPU billing, or execution environment.",
    )
    require(
        spec.get("timeoutSeconds") == 45 and spec.get("containerConcurrency") == 32,
        "Unexpected request timeout or container concurrency.",
    )
    containers = spec.get("containers", [])
    require(
        len(containers) == 1
        and not containers[0].get("env")
        and not containers[0].get("volumeMounts"),
        "Unknown container, credentials, or mount in service.",
    )
    container = containers[0]
    limits = container.get("resources", {}).get("limits", {})
    require(
        str(limits.get("cpu")) in ("1", "1000m")
        and str(limits.get("memory")) in ("512Mi", "0.5Gi", "536870912")
        and set(limits) == {"cpu", "memory"},
        "Unexpected proxy CPU/memory or other resource limits.",
    )
    image = runtime_image()
    if template.get("kind") == "Revision":
        child = LINUX_AMD64.get(image.split("@", 1)[1])
        require(child, "The Linux/amd64 manifest for this trusted index requires verification.")
        trusted = {
            host + "@" + child
            for host in ("mirror.gcr.io/library/nginx", "docker.io/library/nginx")
        }
        require(
            container.get("image") in trusted
            and template.get("status", {}).get("imageDigest") in trusted,
            "Unexpected Linux/amd64 image deployed on Cloud Run.",
        )
    else:
        require(
            container.get("image") == image, "Unexpected image in the Cloud Run service template."
        )
    require(
        container.get("command") == ["/bin/sh"]
        and container.get("args") == ["-ec", command(nginx_config(role, parked), parked)],
        "The deployed image or Nginx command differs from the requested stage.",
    )


def inspect_revision(data, observed, name, number, region, **expected):
    metadata = data.get("metadata", {})
    labels = metadata.get("labels", {})
    require(
        data.get("apiVersion") == "serving.knative.dev/v1"
        and data.get("kind") == "Revision"
        and str(metadata.get("namespace")) == number
        and metadata.get("name") == observed["revision"]
        and metadata.get("uid")
        and labels.get("serving.knative.dev/service") == name
        and labels.get("serving.knative.dev/serviceUid") == observed["uid"]
        and labels.get("cloud.googleapis.com/location") == region
        and metadata.get("generation") is not None
        and str(data.get("status", {}).get("observedGeneration")) == str(metadata["generation"])
        and any(
            c.get("type") == "Ready" and c.get("status") == "True"
            for c in data.get("status", {}).get("conditions", [])
        ),
        "The latest serving revision is not ready or does not belong to this service.",
    )
    inspect_template(data, number=number, region=region, **expected)
    return metadata["uid"]


def inspect_service(
    data, policy, name, project_number, region, role, owner, stage, profile, requested=None
):
    metadata = data.get("metadata", {})
    labels = metadata.get("labels", {})
    annotations = metadata.get("annotations", {})
    require(
        data.get("kind") == "Service"
        and data.get("apiVersion") == "serving.knative.dev/v1"
        and metadata.get("name") == name
        and str(metadata.get("namespace")) == project_number
        and labels.get("cloud.googleapis.com/location") == region
        and labels.get("protohub-role") == role,
        "Service name, project, region, or role does not match the requested resource.",
    )
    require(metadata.get("uid"), "Cloud Run service identity is missing.")
    legacy = stage == "legacy-parked"
    parked = stage in ("parked", "legacy-parked")
    if legacy:
        require(
            "protohub-owner" not in labels and "protohub-profile" not in labels,
            "Legacy inspection requires both ownership labels to be absent.",
        )
    else:
        require(
            labels.get("protohub-owner") == owner and labels.get("protohub-profile") == PROFILE,
            "Ownership/profile mismatch; do not replace or publish this service.",
        )
    public = stage == "live-public"
    require(
        annotations.get("run.googleapis.com/invoker-iam-disabled", "false")
        == ("true" if public else "false"),
        "Invoker IAM check does not match the requested stage.",
    )
    require(
        annotations.get("run.googleapis.com/ingress") == "all",
        "Unexpected Cloud Run ingress setting.",
    )
    require(
        not any(
            m in ("allUsers", "allAuthenticatedUsers")
            for b in policy.get("bindings", [])
            for m in b.get("members", [])
        ),
        "Broad service-level IAM membership is not part of this profile.",
    )
    spec = data.get("spec", {})
    require(
        annotations.get("run.googleapis.com/minScale", "0") == "0"
        and annotations.get("run.googleapis.com/maxScale") == "1"
        and annotations.get("run.googleapis.com/scalingMode", "automatic") == "automatic"
        and not annotations.get("run.googleapis.com/manualInstanceCount"),
        "Unexpected service-wide scaling configuration.",
    )
    inspect_template(
        spec.get("template", {}),
        role=role,
        parked=parked,
        number=project_number,
        region=region,
        **profile,
    )
    status = data.get("status", {})
    revision = status.get("latestReadyRevisionName")
    require(
        metadata.get("generation") is not None
        and str(status.get("observedGeneration")) == str(metadata["generation"])
        and revision
        and revision == status.get("latestCreatedRevisionName")
        and any(
            c.get("type") == "Ready" and c.get("status") == "True"
            for c in status.get("conditions", [])
        ),
        "Cloud Run has not observed a ready latest revision.",
    )
    desired = spec.get("traffic", [])
    actual = status.get("traffic", [])
    require(
        len(desired) == 1
        and desired[0].get("percent") == 100
        and desired[0].get("latestRevision") is True
        and not desired[0].get("tag")
        and not desired[0].get("revisionName")
        and len(actual) == 1
        and actual[0].get("percent") == 100
        and actual[0].get("revisionName") == revision
        and not actual[0].get("tag"),
        "Expected all traffic on the untagged ready latest revision.",
    )
    return {
        "url": reported_url(name, project_number, region, metadata, status, requested),
        "uid": metadata["uid"],
        "revision": revision,
        "generation": metadata["generation"],
    }


def observe_pair(project, number, region, names, owner, stage, urls, profile):
    observed = {}
    for role, name in names.items():
        selector = [name, "--project", project, "--region", region, "--format", "json"]
        service = json.loads(cloud("run", "services", "describe", *selector))
        policy = json.loads(cloud("run", "services", "get-iam-policy", *selector))
        observed[role] = inspect_service(
            service, policy, name, number, region, role, owner, stage, profile, urls[role]
        )
        latest = json.loads(
            cloud("run", "revisions", "describe", observed[role]["revision"], *selector[1:])
        )
        observed[role]["revision_uid"] = inspect_revision(
            latest,
            observed[role],
            name,
            number,
            region,
            role=role,
            parked=stage in ("parked", "legacy-parked"),
            **profile,
        )

    return observed


def https_probe(origin, path, token, console_origin):
    # Called only after BOTH URLs were verified against provider metadata. This client never
    # follows redirects or uses environment proxies. The invoker token is not an app session.
    connection = http.client.HTTPSConnection(origin.removeprefix("https://"), timeout=15)
    headers = {"Origin": console_origin}
    if token:
        headers["X-Serverless-Authorization"] = "Bearer " + token
    try:
        connection.request("GET", path, headers=headers)
        response = connection.getresponse()
        body = response.read(65537)
        require(len(body) <= 65536, "Unexpectedly large verification response.")
        try:
            parsed = json.loads(body)
        except (UnicodeError, ValueError):
            parsed = None
        return response.status, parsed
    finally:
        connection.close()


def verify_access(services, stage):
    console = services["web"]["url"]
    preview = services["preview"]["url"]
    private = stage != "live-public"
    token = None
    if private:
        for origin in (console, preview):
            require(
                https_probe(origin, "/edge-healthz", None, console)[0] in (401, 403),
                "Anonymous invocations must be rejected on both private services.",
            )
        token = cloud("auth", "print-identity-token")
        require(
            re.fullmatch(r"[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+", token),
            "The active gcloud account did not supply an invoker identity token.",
        )
    for origin in (console, preview):
        require(
            https_probe(origin, "/edge-healthz", token, console)[0] == 200,
            "The selected frontend is unreachable or its backend health probe failed.",
        )
    if stage in ("legacy-parked", "parked"):
        for origin in (console, preview):
            require(
                https_probe(origin, "/", token, console)[0] == 503,
                "A parked frontend must return 503 for application traffic.",
            )
        return
    status, info = https_probe(console, "/api/v1/system", token, console)
    require(
        status == 200
        and isinstance(info, dict)
        and info.get("auth_mode") == "google"
        and info.get("runtime_mode") == "real-kind"
        and info.get("preview_origin") == preview
        and re.fullmatch(
            r"[a-zA-Z0-9_-]+\.apps\.googleusercontent\.com", info.get("google_client_id") or ""
        ),
        "Console/preview origins, runtime, or Google login configuration do not match.",
    )
    for path in ("/api/v1/templates", "/api/v1/sandboxes"):
        status, body = https_probe(console, path, token, console)
        require(
            status == 401
            and isinstance(body, dict)
            and isinstance(body.get("error"), dict)
            and body["error"].get("code") == "login_required",
            "Protected API did not require an app session.",
        )
    status, body = https_probe(
        preview, "/apps/00000000-0000-4000-8000-000000000000/healthz", token, console
    )
    require(
        status == 401 and body == {"error": "preview_auth_required"},
        "Preview did not require an app session.",
    )


def verify(
    project,
    region,
    web_service,
    preview_service,
    stage,
    service_account,
    network,
    subnet,
    owner=DEFAULT_OWNER,
    web_url=None,
    preview_url=None,
):
    require(
        PROJECT.fullmatch(project)
        and REGION.fullmatch(region)
        and NETWORK_NAME.fullmatch(owner)
        and SERVICE_NAME.fullmatch(web_service)
        and SERVICE_NAME.fullmatch(preview_service)
        and web_service != preview_service
        and stage in STAGES
        and ACCOUNT.fullmatch(service_account)
        and NETWORK_NAME.fullmatch(network)
        and NETWORK_NAME.fullmatch(subnet),
        "Invalid project/region/services/owner/stage.",
    )
    project_info = json.loads(
        cloud("projects", "describe", project, "--format", "json(projectId,projectNumber)")
    )
    number = str(project_info.get("projectNumber"))
    require(
        project_info.get("projectId") == project and number.isascii() and number.isdigit(),
        "Unable to verify the requested Google Cloud project.",
    )
    names = {"web": web_service, "preview": preview_service}
    urls = {"web": web_url, "preview": preview_url}
    profile = {
        "identity": service_account,
        "network": network,
        "subnet": subnet,
        "project": project,
    }
    services = observe_pair(project, number, region, names, owner, stage, urls, profile)
    verify_access(services, stage)
    require(
        services == observe_pair(project, number, region, names, owner, stage, urls, profile),
        "Service or revision changed during verification.",
    )
    return {"stage": stage, "project": project, "region": region, "services": services}


def verify_cli(argv):
    parser = argparse.ArgumentParser(
        description="Read-only verification of an existing Cloud Run service pair."
    )
    for name in (
        "project",
        "region",
        "web-service",
        "preview-service",
        "service-account",
        "network",
        "subnet",
    ):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--stage", required=True, choices=STAGES)
    parser.add_argument("--owner", default=DEFAULT_OWNER)
    parser.add_argument("--web-url")
    parser.add_argument("--preview-url")
    args = parser.parse_args(argv)
    try:
        print(json.dumps(verify(**vars(args)), indent=2))
    except (ValueError, OSError, http.client.HTTPException, subprocess.TimeoutExpired) as error:
        parser.exit(1, f"Verification failed: {error}\n")


def main():
    if sys.argv[1:2] == ["verify"]:
        return verify_cli(sys.argv[2:])
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--role", choices=PORTS, required=True)
    for name in ("service", "region", "service-account", "network", "subnet"):
        parser.add_argument("--" + name, required=True)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--parked",
        dest="parked",
        action="store_true",
        help="Reserve a URL with a closed frontend (default).",
    )
    mode.add_argument(
        "--live",
        dest="parked",
        action="store_false",
        help="Render forwarding to the selected GKE backend.",
    )
    parser.set_defaults(parked=True)
    parser.add_argument("--owner", default=DEFAULT_OWNER)
    args = parser.parse_args()
    try:
        manifest = render(**vars(args))
    except ValueError as error:
        parser.error(str(error))
    print(yaml.safe_dump(manifest, sort_keys=False), end="")


if __name__ == "__main__":
    sys.exit(main())
