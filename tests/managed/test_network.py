"""Declared pod permissions. Runtime enforcement also requires the target cluster's CNI."""

import unittest
from itertools import product
from pathlib import Path

import yaml

SYSTEM = "protohub-system"
SAMPLES = "protohub-samples"
MANAGED = "app.kubernetes.io/managed-by"
SANDBOX = "protohub.io/sandbox-id"
MANIFEST = Path(__file__).resolve().parents[2] / "infra/managed/network.yaml"


def matches(selector, labels):
    if not all(labels.get(k) == v for k, v in selector.get("matchLabels", {}).items()):
        return False
    for expr in selector.get("matchExpressions", []):
        key = expr["key"]
        if expr["operator"] == "Exists":
            if key not in labels:
                return False
        elif expr["operator"] == "In":
            if labels.get(key) not in expr["values"]:
                return False
        else:
            raise AssertionError(f"Unsupported selector operator: {expr}")
    return True


def peer_matches(peer, policy_namespace, source):
    namespace, labels = source
    if "ipBlock" in peer:
        raise AssertionError("Unexpected IP-range grant")
    if peer == {}:
        return True
    if "namespaceSelector" in peer:
        if not matches(peer["namespaceSelector"], {"kubernetes.io/metadata.name": namespace}):
            return False
    elif policy_namespace != namespace:
        return False
    return matches(peer.get("podSelector", {}), labels)


def ingress_allowed(policies, source, target, port, protocol="TCP"):
    namespace, labels = target
    selected = [
        p["spec"]
        for p in policies
        if p["metadata"]["namespace"] == namespace
        and "Ingress" in p["spec"]["policyTypes"]
        and matches(p["spec"]["podSelector"], labels)
    ]
    if not selected:
        return True
    for policy in selected:
        for rule in policy.get("ingress", []):
            peers = rule.get("from", [])
            ports = rule.get("ports", [])
            if peers and not any(peer_matches(peer, namespace, source) for peer in peers):
                continue
            if any("endPort" in entry for entry in ports):
                raise AssertionError("Unexpected port range")
            if not ports or any(
                p.get("protocol", "TCP") == protocol and p.get("port", port) == port for p in ports
            ):
                return True
    return False


class ManagedNetworkTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.policies = list(yaml.safe_load_all(MANIFEST.read_text(encoding="utf-8")))

    def test_default_deny_and_sample_egress(self):
        for policy in self.policies:
            self.assertEqual(policy["kind"], "NetworkPolicy")
            self.assertEqual(policy["apiVersion"], "networking.k8s.io/v1")
        for ns in [SYSTEM, SAMPLES]:
            specs = [p["spec"] for p in self.policies if p["metadata"]["namespace"] == ns]
            deny = [s for s in specs if not s["podSelector"] and not s.get("ingress")]
            self.assertTrue(any("Ingress" in s["policyTypes"] for s in deny))
            egress = [s for s in specs if "Egress" in s["policyTypes"]]
            if ns == SAMPLES:
                self.assertTrue(any(not s["podSelector"] for s in egress))
                self.assertTrue(all(not s.get("egress") for s in egress))
            else:
                self.assertFalse(egress, "worker needs API server and cluster DNS access")

    def test_pod_traffic_matrix(self):
        pods = {
            role: (SYSTEM, {MANAGED: "protohub", "app": f"protohub-{role}"})
            for role in ["web", "api", "db", "preview", "worker"]
        }
        pods.update(
            {
                "sample": (SAMPLES, {MANAGED: "protohub", SANDBOX: "example"}),
                "unmanaged-sample": (SAMPLES, {MANAGED: "other", SANDBOX: "example"}),
                "no-sandbox-id": (SAMPLES, {MANAGED: "protohub"}),
                "unrelated": (SYSTEM, {}),
                "unmanaged-worker": (SYSTEM, {"app": "protohub-worker"}),
                "foreign-worker": ("unrelated", pods["worker"][1]),
                "foreign-web": ("unrelated", pods["web"][1]),
                "foreign-api": ("unrelated", pods["api"][1]),
            }
        )
        allowed = {
            ("web", "api", 8000),
            ("api", "db", 5432),
            ("preview", "db", 5432),
            ("worker", "db", 5432),
            ("worker", "sample", 8080),
            ("preview", "sample", 8080),
        }
        targets = [name for name, (ns, _) in pods.items() if ns in (SYSTEM, SAMPLES)]
        for source, target, port in product(pods, targets, [5432, 8000, 8080, 8081, 9999]):
            with self.subTest(source=source, target=target, port=port):
                self.assertEqual(
                    ingress_allowed(self.policies, pods[source], pods[target], port),
                    (source, target, port) in allowed,
                )
                self.assertFalse(
                    ingress_allowed(self.policies, pods[source], pods[target], port, "UDP")
                )
