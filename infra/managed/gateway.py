"""Render a GKE HTTPS Gateway for registered browser users."""

import argparse
import http.client
import ipaddress
import json
import queue
import re
import subprocess
import sys
import threading
from contextlib import contextmanager

import yaml
from deploy import SYSTEM, Cluster, DeploymentError, check_owner
from render import DNS_LABEL, validate_origins

GATEWAY = "protohub-browser"
GOOGLE_PROBES = ("35.191.0.0/16", "130.211.0.0/22")
PRIVATE_NETWORKS = tuple(
    ipaddress.IPv4Network(n) for n in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")
)
RESOURCE_TYPES = {
    "NetworkPolicy": "networkpolicies.networking.k8s.io",
    "HealthCheckPolicy": "healthcheckpolicies.networking.gke.io",
    "Gateway": "gateways.gateway.networking.k8s.io",
    "HTTPRoute": "httproutes.gateway.networking.k8s.io",
}


GATEWAY_CLASSES = {"private": "gke-l7-rilb", "internet": "gke-l7-regional-external-managed"}


def resources(console_origin, preview_origin, proxy_cidr, tls_secret, owner, access="private"):
    if access not in GATEWAY_CLASSES:
        raise ValueError("Choose private or internet access.")
    origins = validate_origins(console_origin, preview_origin)
    hosts = [origin.removeprefix("https://") for origin in origins]
    if not DNS_LABEL.fullmatch(tls_secret) or not DNS_LABEL.fullmatch(owner):
        raise ValueError("Use DNS labels for the TLS Secret and owner.")
    subnet = ipaddress.IPv4Network(proxy_cidr, strict=True)
    if not (16 <= subnet.prefixlen <= 26 and any(subnet.subnet_of(n) for n in PRIVATE_NETWORKS)):
        raise ValueError("Use the exact private regional proxy-only subnet (/16 through /26).")
    labels = {
        "protohub.io/profile": "managed",
        "app.kubernetes.io/managed-by": "protohub",
        "protohub.io/owner": owner,
    }

    def obj(api_version, kind, name, spec):
        return {
            "apiVersion": api_version,
            "kind": kind,
            "metadata": {"namespace": SYSTEM, "name": name, "labels": labels.copy()},
            "spec": spec,
        }

    policies, listeners, routes = [], [], []
    for name, host, port in zip(("web", "preview"), hosts, (8080, 8081), strict=True):
        policies.append(
            obj(
                "networking.k8s.io/v1",
                "NetworkPolicy",
                f"gateway-to-{name}",
                {
                    "podSelector": {
                        "matchLabels": {
                            "app": f"protohub-{name}",
                            "app.kubernetes.io/managed-by": "protohub",
                        }
                    },
                    "policyTypes": ["Ingress"],
                    "ingress": [
                        {
                            "from": [
                                {"ipBlock": {"cidr": cidr}}
                                for cidr in (str(subnet), *GOOGLE_PROBES)
                            ],
                            "ports": [{"port": port, "protocol": "TCP"}],
                        }
                    ],
                },
            )
        )
        policies.append(
            obj(
                "networking.gke.io/v1",
                "HealthCheckPolicy",
                f"{GATEWAY}-{name}",
                {
                    "default": {
                        "config": {
                            "type": "HTTP",
                            "httpHealthCheck": {
                                "portSpecification": "USE_FIXED_PORT",
                                "port": port,
                                "requestPath": "/healthz",
                                "host": "localhost",
                            },
                        }
                    },
                    "targetRef": {"group": "", "kind": "Service", "name": name},
                },
            )
        )
        listeners.append(
            {
                "name": name,
                "port": 443,
                "protocol": "HTTPS",
                "hostname": host,
                "allowedRoutes": {"namespaces": {"from": "Same"}},
                "tls": {
                    "mode": "Terminate",
                    "certificateRefs": [{"kind": "Secret", "name": tls_secret}],
                },
            }
        )
        routes.append(
            obj(
                "gateway.networking.k8s.io/v1",
                "HTTPRoute",
                f"{GATEWAY}-{name}",
                {
                    "parentRefs": [{"name": GATEWAY, "sectionName": name}],
                    "hostnames": [host],
                    "rules": [
                        {
                            "matches": [
                                {
                                    "path": {
                                        "type": "PathPrefix",
                                        "value": "/" if name == "web" else "/apps",
                                    }
                                }
                            ],
                            "filters": [
                                {"type": "URLRewrite", "urlRewrite": {"hostname": "localhost"}}
                            ],
                            "backendRefs": [{"name": name, "port": port}],
                        }
                    ],
                },
            )
        )
        if name == "web":
            # Protect authenticated console actions against clickjacking without restricting GIS.
            routes[-1]["spec"]["rules"][0]["filters"].append(
                {
                    "type": "ResponseHeaderModifier",
                    "responseHeaderModifier": {
                        "set": [{"name": "X-Frame-Options", "value": "DENY"}]
                    },
                }
            )
    gateway = obj(
        "gateway.networking.k8s.io/v1",
        "Gateway",
        GATEWAY,
        {"gatewayClassName": GATEWAY_CLASSES[access], "listeners": listeners},
    )
    return [*policies, gateway, *routes]


@contextmanager
def loopback_port(cluster, service, port):
    # The colon lets kubectl allocate a free local port; no user port is reclaimed.
    proc = subprocess.Popen(
        [
            *cluster.command,
            "-n",
            SYSTEM,
            "port-forward",
            "--address=127.0.0.1",
            "--pod-running-timeout=15s",
            f"service/{service}",
            f":{port}",
        ],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    lines = queue.Queue(maxsize=1)

    def read_forwarding_line():
        try:
            lines.put(proc.stdout.readline(200))
        except OSError:
            lines.put(b"")

    # Windows selectors support sockets only. A pipe reader also bounds partial-line waits.
    reader = threading.Thread(target=read_forwarding_line, daemon=True)
    reader.start()
    try:
        try:
            line = lines.get(timeout=20)
        except queue.Empty:
            raise DeploymentError(
                "Timed out connecting to the release for an authentication check."
            ) from None
        match = re.fullmatch(rb"Forwarding from 127\.0\.0\.1:(\d+) -> \d+\s*", line)
        if not match:
            raise DeploymentError(
                "Cannot reach the live service through the explicit Kubernetes context."
            )
        yield int(match.group(1))
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
        reader.join(timeout=1)
        if not reader.is_alive() and proc.stdout is not None:
            proc.stdout.close()


def get_json(port, path):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    try:
        conn.request("GET", path, headers={"Host": "localhost", "Accept": "application/json"})
        reply = conn.getresponse()
        body = reply.read(32769)
        if len(body) > 32768:
            raise DeploymentError("Unexpected response size from the authentication check.")
        data = json.loads(body)
        if not isinstance(data, dict):
            raise DeploymentError("Unexpected response from the authentication check.")
        return reply.status, data
    finally:
        conn.close()


def verify_live_auth(cluster, preview_origin):
    # Old images ignore unknown settings. Require the expected running code on both routes.
    with loopback_port(cluster, "web", 8080) as port:
        status, info = get_json(port, "/api/v1/system")
        if (
            status != 200
            or info.get("auth_mode") != "google"
            or info.get("preview_origin") != preview_origin
        ):
            raise DeploymentError("The live console did not report the approved Google profile.")
        status, reply = get_json(port, "/api/v1/sandboxes")
        error = reply.get("error")
        if status != 401 or not isinstance(error, dict) or error.get("code") != "login_required":
            raise DeploymentError("The live API did not reject an anonymous user.")
    with loopback_port(cluster, "preview", 8081) as port:
        status, reply = get_json(port, "/apps/00000000-0000-4000-8000-000000000001/")
        if status != 401 or reply.get("error") != "preview_auth_required":
            raise DeploymentError("The live preview did not require a registered session.")


def require_verified_release(cluster, labels, console_origin, preview_origin):
    required = [
        ("Namespace", SYSTEM, None),
        ("ConfigMap", "protohub-config", SYSTEM),
        ("Service", "web", SYSTEM),
        ("Service", "preview", SYSTEM),
        ("Deployment", "api", SYSTEM),
        ("Deployment", "preview", SYSTEM),
    ]
    for kind, name, ns in required:
        current = cluster.existing(kind, name, ns)
        if not current:
            raise DeploymentError(f"Deploy the application first: missing {kind}/{name}.")
        check_owner(current, labels, kind, name)
        if kind == "Service" and current["spec"].get("type", "ClusterIP") != "ClusterIP":
            raise DeploymentError("Backend services must be ClusterIP.")
        if kind == "Deployment":
            spec, status = current["spec"], current.get("status", {})
            generation = current["metadata"].get("generation")
            size = spec.get("replicas", 1)
            if (
                not size
                or generation is None
                or status.get("observedGeneration") != generation
                or any(
                    status.get(field) != size
                    for field in (
                        "replicas",
                        "updatedReplicas",
                        "readyReplicas",
                        "availableReplicas",
                    )
                )
            ):
                raise DeploymentError(f"Wait for a complete rollout of Deployment/{name}.")
            containers = spec["template"]["spec"]["containers"]
            container = next((c for c in containers if c["name"] == name), {})
            if {"name": "PROTOHUB_GOOGLE_LOGIN", "value": "true"} not in container.get("env", []):
                raise DeploymentError(f"Google login is required on Deployment/{name}.")
        if kind == "ConfigMap":
            desired = {
                "PROTOHUB_ENVIRONMENT": "production",
                "PROTOHUB_CONSOLE_ORIGIN": console_origin,
                "PROTOHUB_PREVIEW_ORIGIN": preview_origin,
            }
            if any(current["data"].get(k) != v for k, v in desired.items()):
                raise DeploymentError(
                    "Deploy matching HTTPS origins and Google login before installing the Gateway."
                )
    verify_live_auth(cluster, preview_origin)


def install(cluster, items, console_origin, preview_origin, tls_secret):
    labels = items[0]["metadata"]["labels"]
    fmt = 'go-template={{.type}}|{{if index .data "tls.crt"}}yes{{end}}|{{if index .data "tls.key"}}yes{{end}}'
    if (
        cluster.run(["get", "secret", tls_secret, "-n", SYSTEM, "-o", fmt])
        != "kubernetes.io/tls|yes|yes"
    ):
        raise DeploymentError("Provide a TLS secret covering both browser hostnames.")
    prior = []
    for item in items:
        kind, name = item["kind"], item["metadata"]["name"]
        existing = cluster.existing(RESOURCE_TYPES[kind], name, SYSTEM)
        check_owner(existing, labels, kind, name)
        if (
            kind == "Gateway"
            and existing
            and existing["spec"].get("gatewayClassName") != item["spec"]["gatewayClassName"]
        ):
            raise DeploymentError(
                "Existing Gateway has a different exposure. Review its lifecycle before switching."
            )
        prior.append(existing)
    require_verified_release(cluster, labels, console_origin, preview_origin)
    for obj, previous in zip(items, prior, strict=True):
        cluster.install(obj, previous)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ("console-origin", "preview-origin", "proxy-cidr", "tls-secret", "owner"):
        parser.add_argument("--" + key, required=True)
    parser.add_argument(
        "--access",
        choices=GATEWAY_CLASSES,
        default="private",
        help="internet creates a public HTTPS frontend when applied",
    )
    parser.add_argument(
        "--apply-context",
        help="Explicitly create/update the selected load balancer in the given context",
    )
    args = parser.parse_args()
    try:
        items = resources(
            args.console_origin,
            args.preview_origin,
            args.proxy_cidr,
            args.tls_secret,
            args.owner,
            args.access,
        )
        if args.apply_context is None:
            yaml.safe_dump_all(items, sys.stdout, sort_keys=False)
        else:
            install(
                Cluster(args.apply_context),
                items,
                args.console_origin,
                args.preview_origin,
                args.tls_secret,
            )
    except (OSError, ValueError, DeploymentError) as exc:
        parser.exit(1, f"Gateway stopped: {exc}\n")


if __name__ == "__main__":
    main()
