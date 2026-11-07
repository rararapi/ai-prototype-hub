import subprocess
import sys
import unittest
from contextlib import nullcontext
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "infra/managed"))
import gateway

ORIGINS = ("https://console.example.test", "https://preview.example.test")
ARGS = (*ORIGINS, "10.90.0.0/23", "browser-tls", "dev-team")


class GatewayTests(unittest.TestCase):
    def test_loopback_port_reads_a_real_process_pipe_and_closes_it(self):
        real_popen = subprocess.Popen
        children = []

        def start_child(*args, **kwargs):
            child = real_popen(
                [
                    sys.executable,
                    "-u",
                    "-c",
                    "import time; print('Forwarding from 127.0.0.1:12345 -> 8080', flush=True); time.sleep(30)",
                ],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
            )
            children.append(child)
            return child

        cluster = Mock(command=["kubectl", "--context", "explicit"])
        with patch.object(gateway.subprocess, "Popen", side_effect=start_child):
            with gateway.loopback_port(cluster, "web", 8080) as port:
                self.assertEqual(port, 12345)
                self.assertIsNone(children[0].poll())
        self.assertIsNotNone(children[0].poll())
        self.assertTrue(children[0].stdout.closed)

    def test_loopback_port_rejects_a_process_that_exits_before_forwarding(self):
        real_popen = subprocess.Popen
        child = real_popen(
            [sys.executable, "-c", "pass"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
        cluster = Mock(command=["kubectl", "--context", "explicit"])
        with patch.object(gateway.subprocess, "Popen", return_value=child):
            with self.assertRaises(gateway.DeploymentError):
                with gateway.loopback_port(cluster, "web", 8080):
                    self.fail("An exited forwarder must not authorize publication")
        self.assertIsNotNone(child.poll())
        self.assertTrue(child.stdout.closed)

    def test_internal_https_names_and_scoped_routes(self):
        items = gateway.resources(*ARGS)
        (gw,) = [x for x in items if x["kind"] == "Gateway"]
        self.assertEqual(gw["spec"]["gatewayClassName"], "gke-l7-rilb")
        self.assertEqual(len(gw["spec"]["listeners"]), 2)
        routes = [x for x in items if x["kind"] == "HTTPRoute"]
        checks = [x for x in items if x["kind"] == "HealthCheckPolicy"]
        self.assertEqual(len(checks), 2)
        for hc in checks:
            self.assertEqual(
                hc["spec"]["default"]["config"]["httpHealthCheck"]["host"], "localhost"
            )
        for listener, route, host in zip(gw["spec"]["listeners"], routes, ORIGINS, strict=True):
            self.assertEqual(listener["hostname"], host[8:])
            self.assertEqual((listener["protocol"], listener["port"]), ("HTTPS", 443))
            self.assertEqual(listener["tls"]["certificateRefs"][0]["name"], "browser-tls")
            self.assertEqual(route["spec"]["hostnames"], [host[8:]])
            rule = route["spec"]["rules"][0]
            self.assertIn(rule["backendRefs"][0]["name"], ("web", "preview"))
            self.assertEqual(
                rule["filters"][0], {"type": "URLRewrite", "urlRewrite": {"hostname": "localhost"}}
            )
            if listener["name"] == "web":
                self.assertEqual(
                    rule["filters"][1]["responseHeaderModifier"]["set"],
                    [{"name": "X-Frame-Options", "value": "DENY"}],
                )

        for item in items:
            if item["kind"] == "NetworkPolicy":
                rules = item["spec"]["ingress"]
                self.assertEqual(len(rules), 1)
                self.assertEqual(
                    {p["ipBlock"]["cidr"] for p in rules[0]["from"]},
                    {"10.90.0.0/23", *gateway.GOOGLE_PROBES},
                )
                self.assertIn(rules[0]["ports"][0]["port"], (8080, 8081))

    def test_public_gateway_is_opt_in_and_only_routes_encrypted_requests_to_auth_boundaries(self):
        private = gateway.resources(*ARGS)
        public = gateway.resources(*ARGS, access="internet")
        (old,) = (obj for obj in private if obj["kind"] == "Gateway")
        (new,) = (obj for obj in public if obj["kind"] == "Gateway")
        self.assertEqual(new["spec"]["gatewayClassName"], "gke-l7-regional-external-managed")
        self.assertEqual(old["spec"]["listeners"], new["spec"]["listeners"])
        self.assertEqual(
            [obj for obj in private if obj["kind"] != "Gateway"],
            [obj for obj in public if obj["kind"] != "Gateway"],
        )
        with self.assertRaises(ValueError):
            gateway.resources(*ARGS, access="http")

    def test_probe_denies_old_or_open_images_before_exposure(self):
        info = {"auth_mode": "google", "preview_origin": ORIGINS[1]}
        good = [
            (200, info),
            (401, {"error": {"code": "login_required"}}),
            (401, {"error": "preview_auth_required"}),
        ]
        for i, wrong in (
            (0, (200, {"auth_mode": "local-dev"})),
            (1, (200, {})),
            (2, (404, {})),
            (2, (200, {})),
        ):
            answers = list(good)
            answers[i] = wrong
            with (
                self.subTest(i=i, wrong=wrong),
                patch.object(gateway, "loopback_port", side_effect=lambda *_: nullcontext(1234)),
                patch.object(gateway, "get_json", side_effect=answers),
                self.assertRaises(gateway.DeploymentError),
            ):
                gateway.verify_live_auth(Mock(), ORIGINS[1])
        with (
            patch.object(gateway, "loopback_port", side_effect=lambda *_: nullcontext(1234)),
            patch.object(gateway, "get_json", side_effect=good),
        ):
            gateway.verify_live_auth(Mock(), ORIGINS[1])

    def test_refuses_unsafe_inputs(self):
        for replace, index in [
            ("http://console.example.test", 0),
            (ORIGINS[0], 1),
            ("https://*.example.test", 0),
            ("https://host.example.test/path", 0),
            ("https://127.0.0.1", 1),
            ("https://a@b.example", 0),
            ("0.0.0.0/0", 2),
            ("10.0.0.0/8", 2),
            ("198.51.100.0/24", 2),
            ("../tls", 3),
            ("", 4),
        ]:
            with self.subTest(replace=replace), self.assertRaises(ValueError):
                args = list(ARGS)
                args[index] = replace
                gateway.resources(*args)

    def test_profile_mismatch_foreign_resource_and_missing_tls_stop_before_writes(self):
        items = gateway.resources(*ARGS)
        labels = items[0]["metadata"]["labels"]
        config = {
            "PROTOHUB_GOOGLE_LOGIN": "true",
            "PROTOHUB_ENVIRONMENT": "production",
            "PROTOHUB_CONSOLE_ORIGIN": ORIGINS[0],
            "PROTOHUB_PREVIEW_ORIGIN": ORIGINS[1],
        }
        for case in ("wrong-origin", "no-tls", "foreign", "old-replica", "email-login", "ok"):
            with self.subTest(case=case):
                cluster = Mock()

                def existing(kind, name, namespace=None, case=case):
                    if kind == "ConfigMap":
                        return {
                            "metadata": {"labels": labels},
                            "data": config if case != "wrong-origin" else {},
                        }
                    if kind == "Deployment":
                        env = (
                            [{"name": "PROTOHUB_GOOGLE_LOGIN", "value": "true"}]
                            if case != "email-login"
                            else []
                        )
                        return {
                            "metadata": {"labels": labels, "generation": 2},
                            "spec": {
                                "replicas": 1,
                                "template": {"spec": {"containers": [{"name": name, "env": env}]}},
                            },
                            "status": {
                                "observedGeneration": 2,
                                "replicas": 2 if case == "old-replica" else 1,
                                "readyReplicas": 1,
                                "updatedReplicas": 1,
                                "availableReplicas": 1,
                            },
                        }
                    if kind in {"Service", "Namespace"}:
                        return {"metadata": {"labels": labels}, "spec": {"type": "ClusterIP"}}
                    if case == "foreign" and kind == gateway.RESOURCE_TYPES["Gateway"]:
                        return {"metadata": {"labels": {}}}
                    return None

                cluster.existing.side_effect = existing
                cluster.run.return_value = "kubernetes.io/tls|yes|yes" if case != "no-tls" else ""
                if case == "ok":
                    with patch.object(gateway, "verify_live_auth") as auth:
                        gateway.install(cluster, items, *ORIGINS, "browser-tls")
                        auth.assert_called_once_with(cluster, ORIGINS[1])
                    self.assertEqual(cluster.install.call_count, len(items))
                else:
                    with self.assertRaises(gateway.DeploymentError):
                        gateway.install(cluster, items, *ORIGINS, "browser-tls")
                    cluster.install.assert_not_called()
