import io
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import Mock, patch

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "infra/managed"))
import run_bridge as bridge
from deploy import SYSTEM, DeploymentError

OPTS = (
    "10.25.8.64/26",
    "test-team",
    "https://console-123.asia-northeast1.run.app",
    "https://preview-123.asia-northeast1.run.app",
)


class BridgeTests(unittest.TestCase):
    def test_fixed_headless_services_and_narrow_ingress(self):
        objects = bridge.bridge_objects(*OPTS)
        self.assertEqual(
            [o["kind"] for o in objects], ["Service", "Service", "NetworkPolicy", "NetworkPolicy"]
        )
        for i, (app, port) in enumerate((("web", 8080), ("preview", 8081))):
            service, policy = objects[i], objects[2 + i]
            self.assertEqual(service["metadata"]["name"], f"protohub-run-{app}")
            self.assertEqual(policy["metadata"]["name"], f"protohub-run-to-{app}")
            for obj in (service, policy):
                self.assertEqual(obj["metadata"]["namespace"], SYSTEM)
                self.assertEqual(obj["metadata"]["labels"]["protohub.io/owner"], OPTS[1])
            self.assertEqual(service["spec"]["type"], "ClusterIP")
            self.assertEqual(service["spec"]["clusterIP"], "None")
            self.assertEqual(
                service["spec"]["ports"], [{"port": port, "targetPort": port, "protocol": "TCP"}]
            )
            self.assertEqual(
                policy["spec"],
                {
                    "podSelector": {"matchLabels": service["spec"]["selector"]},
                    "policyTypes": ["Ingress"],
                    "ingress": [
                        {
                            "from": [{"ipBlock": {"cidr": OPTS[0]}}],
                            "ports": [{"protocol": "TCP", "port": port}],
                        }
                    ],
                },
            )

    def test_invalid_cidr_owner_and_origins(self):
        for i, bad in [
            (0, "0.0.0.0/26"),
            (0, "10.0.0.0/24"),
            (0, "10.0.0.1/26"),
            (0, "fd00::/64"),
            (1, "not an owner"),
            (2, "https://console.example.org"),
            (3, "https://x.run.app.other.test"),
            (3, OPTS[2]),
            (3, "http://localhost:8081"),
        ]:
            args = list(OPTS)
            args[i] = bad
            with self.subTest(args=args), self.assertRaises(ValueError):
                bridge.bridge_objects(*args)

    def test_inventory_and_live_auth_precede_all_writes(self):
        objects = bridge.bridge_objects(*OPTS)
        labels = objects[0]["metadata"]["labels"]
        cluster = Mock()
        cluster.existing.return_value = None
        with patch.object(
            bridge, "require_verified_release", side_effect=DeploymentError("old auth")
        ):
            with self.assertRaisesRegex(DeploymentError, "old auth"):
                bridge.install(cluster, objects, *OPTS[2:])
        cluster.install.assert_not_called()
        with patch.object(bridge, "require_verified_release") as check:
            bridge.install(cluster, objects, *OPTS[2:])
            check.assert_called_once_with(cluster, labels, *OPTS[2:])
            self.assertEqual([c.args[0] for c in cluster.install.call_args_list], objects)

    def test_foreign_object_stops_before_creating_policy(self):
        objects = bridge.bridge_objects(*OPTS)
        cluster = Mock()
        cluster.existing.side_effect = lambda kind, name, ns: (
            {"metadata": {"labels": {}}} if name == "protohub-run-to-preview" else None
        )
        with (
            self.assertRaisesRegex(DeploymentError, "foreign"),
            patch.object(bridge, "require_verified_release"),
        ):
            bridge.install(cluster, objects, *OPTS[2:])
        cluster.install.assert_not_called()

    def test_default_cli_is_offline(self):
        argv = [
            "run_bridge.py",
            "--edge-cidr",
            OPTS[0],
            "--owner",
            OPTS[1],
            "--console-origin",
            OPTS[2],
            "--preview-origin",
            OPTS[3],
        ]
        out = io.StringIO()
        with (
            patch.object(sys, "argv", argv),
            patch.object(bridge, "Cluster", side_effect=AssertionError("unexpected mutation")),
            redirect_stdout(out),
        ):
            bridge.main()
        self.assertEqual(list(yaml.safe_load_all(out.getvalue())), bridge.bridge_objects(*OPTS))
