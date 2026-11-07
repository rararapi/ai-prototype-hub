"""Render or install private Pod discovery and ingress for the two Cloud Run frontends."""

import argparse
import ipaddress
import subprocess

import yaml
from deploy import OWNER_KEYS, SYSTEM, Cluster, DeploymentError, check_owner
from gateway import require_verified_release
from render import DNS_LABEL, validate_origins

BRIDGES = (("web", 8080), ("preview", 8081))
PRIVATE = tuple(ipaddress.IPv4Network(c) for c in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"))


def bridge_objects(edge_cidr, owner, console_origin, preview_origin):
    origins = validate_origins(console_origin, preview_origin)
    if not all(origin.endswith(".run.app") for origin in origins):
        raise ValueError("Use the verified Cloud Run HTTPS service origins.")
    if not DNS_LABEL.fullmatch(owner):
        raise ValueError("Use the existing installation owner.")
    subnet = ipaddress.IPv4Network(edge_cidr, strict=True)
    if subnet.prefixlen != 26 or not any(subnet.subnet_of(n) for n in PRIVATE):
        raise ValueError("Use the exact dedicated private /26 Cloud Run subnet.")
    labels = {
        "app.kubernetes.io/managed-by": "protohub",
        "protohub.io/profile": "managed",
        "protohub.io/owner": owner,
    }
    services, policies = [], []
    for app, port in BRIDGES:
        selector = {"app": f"protohub-{app}", "app.kubernetes.io/managed-by": "protohub"}
        services.append(
            {
                "apiVersion": "v1",
                "kind": "Service",
                "metadata": {
                    "name": f"protohub-run-{app}",
                    "namespace": SYSTEM,
                    "labels": labels.copy(),
                },
                "spec": {
                    "type": "ClusterIP",
                    "clusterIP": "None",
                    "selector": selector,
                    "ports": [{"protocol": "TCP", "port": port, "targetPort": port}],
                },
            }
        )
        policies.append(
            {
                "apiVersion": "networking.k8s.io/v1",
                "kind": "NetworkPolicy",
                "metadata": {
                    "name": f"protohub-run-to-{app}",
                    "namespace": SYSTEM,
                    "labels": labels.copy(),
                },
                "spec": {
                    "podSelector": {"matchLabels": selector},
                    "policyTypes": ["Ingress"],
                    "ingress": [
                        {
                            "from": [{"ipBlock": {"cidr": str(subnet)}}],
                            "ports": [{"protocol": "TCP", "port": port}],
                        }
                    ],
                },
            }
        )
    return services + policies


def install(cluster, resources, console_origin, preview_origin):
    labels = {k: resources[0]["metadata"]["labels"][k] for k in OWNER_KEYS}
    prior = []
    for obj in resources:
        kind, meta = obj["kind"], obj["metadata"]
        old = cluster.existing(kind, meta["name"], SYSTEM)
        check_owner(old, labels, kind, meta["name"])
        if (
            kind == "Service"
            and old
            and (
                old["spec"].get("clusterIP") != "None"
                or old["spec"].get("type", "ClusterIP") != "ClusterIP"
                or old["spec"].get("externalIPs")
            )
        ):
            raise DeploymentError("Refusing to adopt an exposed or non-headless Service.")
        prior.append(old)
    require_verified_release(cluster, labels, console_origin, preview_origin)
    for obj, previous in zip(resources, prior, strict=True):
        cluster.install(obj, previous)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("edge-cidr", "owner", "console-origin", "preview-origin"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument(
        "--apply-context", help="Explicit kubeconfig context to install the bridge."
    )
    args = parser.parse_args()
    try:
        items = bridge_objects(args.edge_cidr, args.owner, args.console_origin, args.preview_origin)
        if args.apply_context is None:
            print(yaml.safe_dump_all(items, sort_keys=False), end="")
        else:
            install(Cluster(args.apply_context), items, args.console_origin, args.preview_origin)
    except (DeploymentError, OSError, ValueError, subprocess.TimeoutExpired) as exc:
        parser.exit(1, f"Bridge stopped: {exc}\n")


if __name__ == "__main__":
    main()
