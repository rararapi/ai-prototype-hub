import base64
import copy
import io
import json
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "infra/managed"))
import deploy
from render import render


def release():
    refs = [
        f"registry.example.org/dev/{name}@sha256:{'a' * 64}"
        for name in ("server", "web", "hello-web", "postgres")
    ]
    return render(*refs, "approved-csi", "demo-owner")


class MemoryCluster:
    def __init__(self):
        self.resources = {("StorageClass", None, "approved-csi"): {"metadata": {}}}
        self.writes = []

    def has_public_routes(self):
        return False

    def existing(self, kind, name, namespace=None):
        return self.resources.get((kind, namespace, name))

    def install(self, obj, previous):
        meta = obj["metadata"]
        key = (obj["kind"], meta.get("namespace"), meta["name"])
        if previous != self.resources.get(key):
            raise deploy.DeploymentError("collision")
        self.resources[key] = copy.deepcopy(obj)
        self.writes.append(key)


CLIENT_ID = "123456789-owntest.apps.googleusercontent.com"
CLIENT_SECRET = "synthetic-test-only"


def fresh(cluster, desired):
    with patch.object(deploy.getpass, "getpass", side_effect=[CLIENT_ID, CLIENT_SECRET]):
        deploy.deploy(cluster, desired, configure_google=True)


class DeployTests(unittest.TestCase):
    def test_prepare_database_initial_retry_and_full_release_handoff(self):
        desired, cluster = release(), MemoryCluster()
        with (
            patch.object(cluster, "existing", wraps=cluster.existing) as lookup,
            patch.object(
                deploy, "prompt_google_credentials", side_effect=AssertionError("Google prompt")
            ),
            patch.object(
                deploy, "load_google_client_file", side_effect=AssertionError("Google file read")
            ),
        ):
            deploy.deploy(cluster, desired, prepare_database=True)
            key = ("Secret", deploy.SYSTEM, deploy.DB_SECRET)
            self.assertEqual(set(cluster.writes), deploy.DATABASE_OBJECTS | {key})
            self.assertLess(
                cluster.writes.index(key),
                cluster.writes.index(("PersistentVolumeClaim", deploy.SYSTEM, "protohub-db")),
            )
            secret = copy.deepcopy(cluster.resources[key])
            self.assertTrue(secret["immutable"])
            deploy.deploy(cluster, desired, prepare_database=True)
            self.assertNotIn(
                ("Secret", deploy.GOOGLE_SECRET, deploy.SYSTEM),
                [call.args for call in lookup.call_args_list],
            )
            self.assertEqual(cluster.writes.count(key), 1)
            self.assertEqual(cluster.resources[key], secret)
        fresh(cluster, desired)
        self.assertEqual(cluster.resources[key], secret)
        self.assertEqual(cluster.writes.count(key), 1)
        self.assertIn(("Deployment", deploy.SYSTEM, "api"), cluster.resources)
        self.assertIn(("Secret", deploy.SYSTEM, deploy.GOOGLE_SECRET), cluster.resources)

    def test_prepare_database_refuses_any_noncore_object_and_bridges_before_writes(self):
        desired = release()
        ns = next(
            d
            for d in desired
            if d["kind"] == "Namespace" and d["metadata"]["name"] == deploy.SYSTEM
        )
        for kind, name in (
            ("Deployment", "api"),
            ("Deployment", "worker"),
            ("Deployment", "web"),
            ("Deployment", "preview"),
            ("ServiceAccount", "protohub-worker"),
            ("NetworkPolicy", "protohub-run-to-preview"),
            ("Service", "protohub-run-web"),
            ("public", "route"),
        ):
            with self.subTest(kind=kind, name=name):
                cluster = MemoryCluster()
                cluster.resources["Namespace", None, deploy.SYSTEM] = ns
                if kind != "public":
                    cluster.resources[kind, deploy.SYSTEM, name] = {
                        "metadata": {"labels": ns["metadata"]["labels"]}
                    }
                with (
                    patch.object(cluster, "has_public_routes", return_value=kind == "public"),
                    self.assertRaises(deploy.DeploymentError),
                ):
                    deploy.deploy(cluster, desired, prepare_database=True)
                self.assertEqual(cluster.writes, [])

    def test_prepare_database_preserves_storage_and_recovers_partial_secret_creation(self):
        cluster, desired = MemoryCluster(), release()
        original = cluster.install

        def fail_at_pvc(obj, prev):
            if obj["kind"] == "PersistentVolumeClaim":
                raise deploy.DeploymentError("interrupted")
            original(obj, prev)

        with (
            patch.object(cluster, "install", side_effect=fail_at_pvc),
            self.assertRaisesRegex(deploy.DeploymentError, "interrupted"),
        ):
            deploy.deploy(cluster, desired, prepare_database=True)
        secret_key = ("Secret", deploy.SYSTEM, deploy.DB_SECRET)
        secret = copy.deepcopy(cluster.resources[secret_key])
        deploy.deploy(cluster, desired, prepare_database=True)
        self.assertEqual(cluster.resources[secret_key], secret)
        self.assertEqual(cluster.writes.count(secret_key), 1)
        for key, operation in [
            (secret_key, "remove"),
            (("PersistentVolumeClaim", deploy.SYSTEM, "protohub-db"), "remove"),
            (("PersistentVolumeClaim", deploy.SYSTEM, "protohub-db"), "storage"),
            (("Deployment", deploy.SYSTEM, "db"), "image"),
            (("Namespace", None, deploy.SYSTEM), "owner"),
        ]:
            with self.subTest(key=key, operation=operation):
                broken = copy.deepcopy(cluster)
                broken.writes.clear()
                if operation == "remove":
                    del broken.resources[key]
                elif operation == "storage":
                    broken.resources[key]["spec"]["storageClassName"] = "different"
                elif operation == "image":
                    broken.resources[key]["spec"]["template"]["spec"]["containers"][0]["image"] = (
                        "different"
                    )
                else:
                    broken.resources[key]["metadata"]["labels"]["protohub.io/owner"] = "other"
                with self.assertRaises(deploy.DeploymentError):
                    deploy.deploy(broken, desired, prepare_database=True)
                self.assertEqual(broken.writes, [])

    def test_prepare_database_rejects_google_flags_before_any_read(self):
        cluster = MemoryCluster()
        for opts in [{"configure_google": True}, {"google_client_file": Path("/unused")}]:
            with (
                self.subTest(opts=opts),
                patch.object(cluster, "existing", side_effect=AssertionError("cluster accessed")),
                self.assertRaisesRegex(deploy.DeploymentError, "combined"),
            ):
                deploy.deploy(cluster, release(), prepare_database=True, **opts)
        for flag in (["--configure-google"], ["--google-client-file", "/unused"]):
            args = [
                "deploy",
                "--prepare-database",
                "--context",
                "test",
                "--manifest",
                "/unused",
                *flag,
            ]
            with (
                patch.object(sys, "argv", args),
                patch.object(sys, "stderr", io.StringIO()),
                self.assertRaises(SystemExit) as error,
            ):
                deploy.main()
            self.assertEqual(error.exception.code, 2)

    def seeded_release(self):
        desired, cluster = release(), MemoryCluster()
        fresh(cluster, desired)
        for obj in desired:
            key = (obj["kind"], obj["metadata"].get("namespace"), obj["metadata"]["name"])
            cluster.resources[key]["metadata"].setdefault("annotations", {})[
                deploy.LAST_APPLIED
            ] = json.dumps(obj)
        cluster.writes.clear()
        return desired, cluster

    def test_public_routes_block_browser_changes_before_writes(self):
        for name in (
            "api",
            "web",
            "preview",
            "origins",
            "missing-annotation",
            "invalid-annotation",
            "live-drift",
            "lost-oauth",
        ):
            desired, cluster = self.seeded_release()
            if name == "origins":
                obj = next(o for o in desired if o["kind"] == "ConfigMap")
                obj["data"]["PROTOHUB_CONSOLE_ORIGIN"] = "https://new.example.org"
            elif name in ("missing-annotation", "invalid-annotation", "live-drift"):
                api = cluster.resources["Deployment", deploy.SYSTEM, "api"]
                if name == "live-drift":
                    api["spec"]["template"]["spec"]["containers"][0]["image"] = "other"
                elif name == "missing-annotation":
                    del api["metadata"]["annotations"][deploy.LAST_APPLIED]
                else:
                    api["metadata"]["annotations"][deploy.LAST_APPLIED] = "{invalid"
            elif name == "lost-oauth":
                del cluster.resources["Secret", deploy.SYSTEM, deploy.GOOGLE_SECRET]
            else:
                obj = next(
                    o
                    for o in desired
                    if o["kind"] == "Deployment" and o["metadata"]["name"] == name
                )
                obj["spec"]["template"]["spec"]["containers"][0]["image"] = "changed"
            with (
                patch.object(cluster, "has_public_routes", return_value=True),
                self.subTest(name=name),
                self.assertRaisesRegex(deploy.DeploymentError, "public ProtoHub HTTPRoute"),
            ):
                deploy.deploy(cluster, desired)
            self.assertFalse(cluster.writes)

    def test_cloud_run_policy_alone_prevents_auth_change_and_credential_replacement(self):
        for role in ("web", "preview"):
            for change in ("server", "lost-oauth"):
                desired, cluster = self.seeded_release()
                cluster.resources["NetworkPolicy", deploy.SYSTEM, f"protohub-run-to-{role}"] = {
                    "metadata": {}
                }
                if change == "server":
                    api = next(
                        o
                        for o in desired
                        if o["kind"] == "Deployment" and o["metadata"]["name"] == "api"
                    )
                    api["spec"]["template"]["spec"]["containers"][0]["image"] = "older-image"
                else:
                    del cluster.resources["Secret", deploy.SYSTEM, deploy.GOOGLE_SECRET]
                with (
                    self.subTest(role=role, change=change),
                    patch.object(
                        cluster,
                        "has_public_routes",
                        side_effect=AssertionError("unexpected Gateway dependency"),
                    ),
                    self.assertRaisesRegex(deploy.DeploymentError, "Cloud Run bridge"),
                ):
                    deploy.deploy(cluster, desired)
                self.assertFalse(cluster.writes)

    def test_downloaded_web_client_is_used_privately_once(self):
        desired, cluster = release(), MemoryCluster()
        origin = next(
            o["data"]["PROTOHUB_CONSOLE_ORIGIN"] for o in desired if o["kind"] == "ConfigMap"
        )
        web = {
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
            "javascript_origins": [origin],
            "redirect_uris": [origin],
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "client.json"
            path.write_text(json.dumps({"web": web}))
            with patch.object(
                deploy.getpass, "getpass", side_effect=AssertionError("unexpected prompt")
            ):
                deploy.deploy(cluster, desired, google_client_file=path)
                path.unlink()
                deploy.deploy(cluster, desired, google_client_file=path)
        self.assertEqual(cluster.writes.count(("Secret", deploy.SYSTEM, deploy.GOOGLE_SECRET)), 1)

    def test_invalid_downloaded_client_never_writes_or_discloses_credentials(self):
        origin = "http://localhost:8080"
        web = {
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
            "javascript_origins": [origin],
            "redirect_uris": [origin],
        }
        cases = [
            b"[{",
            b"x" * 65537,
            json.dumps({"installed": web}).encode(),
            json.dumps({"installed": web, "web": web}).encode(),
        ]
        for key in ("javascript_origins", "redirect_uris"):
            for bad in (None, origin, ["https://unknown.example.test"], [origin + "/"]):
                cases.append(json.dumps({"web": {**web, key: bad}}).encode())
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sensitive-name.json"
            for case in cases:
                path.write_bytes(case)
                cluster = MemoryCluster()
                with self.assertRaises(deploy.DeploymentError) as err:
                    deploy.deploy(cluster, release(), google_client_file=path)
                self.assertFalse(cluster.writes)
                for private in (CLIENT_ID, CLIENT_SECRET, str(path), path.name):
                    self.assertNotIn(private, str(err.exception))

    def test_unchanged_and_sample_only_updates_do_not_check_public_gateway(self):
        for sample_only in (False, True):
            desired, cluster = self.seeded_release()
            if sample_only:
                config = next(o for o in desired if o["kind"] == "ConfigMap")
                config["data"]["PROTOHUB_SAMPLE_IMAGE"] = "new-digest"
                worker = next(
                    o
                    for o in desired
                    if o["kind"] == "Deployment" and o["metadata"]["name"] == "worker"
                )
                worker["spec"]["template"]["metadata"]["annotations"][
                    "protohub.io/sample-image"
                ] = "new-digest"
            with patch.object(
                cluster, "has_public_routes", side_effect=AssertionError("unexpected check")
            ):
                deploy.deploy(cluster, desired)
            self.assertTrue(cluster.writes)

    def test_gateway_discovery_absent_private_external_and_failure(self):
        client = deploy.Cluster("test")
        names = "gateways.gateway.networking.k8s.io\nhttproutes.gateway.networking.k8s.io"
        route = {"spec": {"parentRefs": [{"name": "protohub-browser"}]}}
        with patch.object(client, "run", return_value=""):
            self.assertFalse(client.has_public_routes())
        for klass, routes, expected in (
            ("gke-l7-rilb", [route], False),
            ("gke-l7-regional-external-managed", [route], True),
            ("gke-l7-global-external-managed", [], False),
            ("unrecognized", [route], True),
            ("unrecognized", [{"spec": {"parentRefs": [{"name": "other"}]}}], False),
        ):
            gateway = json.dumps({"spec": {"gatewayClassName": klass}})
            with patch.object(
                client, "run", side_effect=[names, gateway, json.dumps({"items": routes})]
            ):
                self.assertEqual(client.has_public_routes(), expected)
        with (
            patch.object(client, "run", side_effect=deploy.DeploymentError("forbidden")),
            self.assertRaises(deploy.DeploymentError),
        ):
            client.has_public_routes()

    def test_accept_rendered_manifest_and_reject_modified_extra_reordered(self):
        desired = release()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "managed.yaml"
            path.write_text(yaml.safe_dump_all(desired))
            self.assertEqual(deploy.read_manifest(path), desired)
            modified = copy.deepcopy(desired)
            service = next(obj for obj in modified if obj["kind"] == "Service")
            service["spec"]["type"] = "LoadBalancer"
            for bad in (modified, desired + [desired[-1]], list(reversed(desired)), [None]):
                with self.subTest(), self.assertRaises(deploy.DeploymentError):
                    path.write_text(yaml.safe_dump_all(bad))
                    deploy.read_manifest(path)

    def test_fresh_install_retry_and_lost_credentials(self):
        cluster, desired = MemoryCluster(), release()
        fresh(cluster, desired)
        key = ("Secret", deploy.SYSTEM, deploy.DB_SECRET)
        pvc = ("PersistentVolumeClaim", deploy.SYSTEM, "protohub-db")
        self.assertLess(cluster.writes.index(key), cluster.writes.index(pvc))
        secret = copy.deepcopy(cluster.resources[key])
        self.assertTrue(secret["immutable"])
        self.assertIn(secret["stringData"]["password"], secret["stringData"]["database-url"])
        deploy.deploy(cluster, desired)
        self.assertEqual(cluster.writes.count(key), 1)
        self.assertEqual(secret, cluster.resources[key])
        del cluster.resources[key]
        cluster.writes.clear()
        with self.assertRaisesRegex(deploy.DeploymentError, "original database Secret"):
            deploy.deploy(cluster, desired)
        self.assertEqual(cluster.writes, [])

    def test_existing_foreign_resource_terminating_namespace_storage_fail_without_writes(self):
        desired = release()
        for key, bad in (
            (("Namespace", None, "protohub-samples"), {"metadata": {"labels": {}}}),
            (("Deployment", deploy.SYSTEM, "worker"), {"metadata": {"labels": {}}}),
            (("Secret", deploy.SYSTEM, deploy.DB_SECRET), {"metadata": {"labels": {}}}),
            (("Namespace", None, "protohub-system"), {"metadata": {"deletionTimestamp": "now"}}),
            (("StorageClass", None, "approved-csi"), None),
        ):
            cluster = MemoryCluster()
            # A live namespaced object always has a live namespace.
            if key[1]:
                ns = next(
                    d
                    for d in desired
                    if d["kind"] == "Namespace" and d["metadata"]["name"] == key[1]
                )
                cluster.resources["Namespace", None, key[1]] = ns
            cluster.resources[key] = bad
            with self.subTest(key=key), self.assertRaises(deploy.DeploymentError):
                deploy.deploy(cluster, desired)
            self.assertEqual(cluster.writes, [])

    def test_changed_pvc_storage_class_and_partial_failure(self):
        desired, cluster = release(), MemoryCluster()
        original = cluster.install

        def fail_at_pvc(obj, prev):
            if obj["kind"] == "PersistentVolumeClaim":
                raise deploy.DeploymentError("injected failure")
            original(obj, prev)

        with patch.object(cluster, "install", side_effect=fail_at_pvc):
            with self.assertRaisesRegex(deploy.DeploymentError, "injected failure"):
                fresh(cluster, desired)
        deploy.deploy(cluster, desired)
        self.assertEqual(cluster.writes.count(("Secret", deploy.SYSTEM, deploy.DB_SECRET)), 1)
        cluster.resources["PersistentVolumeClaim", deploy.SYSTEM, "protohub-db"]["spec"][
            "storageClassName"
        ] = "other"
        cluster.writes.clear()
        with self.assertRaisesRegex(deploy.DeploymentError, "different StorageClass"):
            deploy.deploy(cluster, desired)
        self.assertEqual(cluster.writes, [])

    def test_secret_preflight_checks_metadata_and_key_presence_without_printing_values(self):
        client = deploy.Cluster("private-test")
        with patch.object(
            client, "run", return_value="owner|managed|protohub|yes|yes|true|active"
        ) as run:
            secret = client.existing("Secret", deploy.DB_SECRET, deploy.SYSTEM)
            self.assertEqual(secret["metadata"]["labels"]["protohub.io/owner"], "owner")
            template = run.call_args.args[0][-1]
            self.assertIn("if .data.password", template)
            self.assertNotIn("{{.data.password}}", template)
        with patch.object(client, "run", return_value=""):
            self.assertIsNone(client.existing("Secret", deploy.DB_SECRET, deploy.SYSTEM))
        for suffix in ("no|yes|true|active", "yes|yes|false|active", "yes|yes|true|deleting"):
            with (
                self.subTest(suffix=suffix),
                patch.object(client, "run", return_value="owner|managed|protohub|" + suffix),
            ):
                with self.assertRaises(deploy.DeploymentError):
                    client.existing("Secret", deploy.DB_SECRET, deploy.SYSTEM)

    def test_explicit_google_setup_is_required_before_first_write(self):
        cluster, desired = MemoryCluster(), release()
        with self.assertRaisesRegex(deploy.DeploymentError, "--configure-google"):
            deploy.deploy(cluster, desired)
        self.assertFalse(cluster.writes)
        for client_id, secret in (
            ("bogus", CLIENT_SECRET),
            (CLIENT_ID, ""),
            (CLIENT_ID, "unsafe secret"),
            (CLIENT_ID, "invalid\nvalue"),
        ):
            with (
                self.subTest(client_id=client_id),
                patch.object(deploy.getpass, "getpass", side_effect=[client_id, secret]),
                self.assertRaisesRegex(deploy.DeploymentError, "Invalid Google OAuth"),
            ):
                deploy.deploy(cluster, desired, configure_google=True)
            self.assertFalse(cluster.writes)

    def test_owned_google_secret_created_once_and_reused_without_prompting(self):
        cluster, desired = MemoryCluster(), release()
        fresh(cluster, desired)
        key = ("Secret", deploy.SYSTEM, deploy.GOOGLE_SECRET)
        api = ("Deployment", deploy.SYSTEM, "api")
        self.assertLess(cluster.writes.index(key), cluster.writes.index(api))
        secret = copy.deepcopy(cluster.resources[key])
        self.assertTrue(secret["immutable"])
        self.assertEqual(
            secret["stringData"], {"client-id": CLIENT_ID, "client-secret": CLIENT_SECRET}
        )
        with patch.object(
            deploy.getpass, "getpass", side_effect=AssertionError("unexpected prompt")
        ):
            deploy.deploy(cluster, desired, configure_google=True)
            deploy.deploy(cluster, desired)
        self.assertEqual(cluster.resources[key], secret)
        self.assertEqual(cluster.writes.count(key), 1)

        cluster.resources[key]["metadata"]["labels"]["protohub.io/owner"] = "another-team"
        cluster.writes.clear()
        with self.assertRaisesRegex(deploy.DeploymentError, "foreign or terminating"):
            deploy.deploy(cluster, desired, configure_google=True)
        self.assertFalse(cluster.writes)

    def test_private_reuse_validation_rejects_damaged_secret(self):
        def encode(value):
            return base64.b64encode(value.encode()).decode()

        obj = {
            "metadata": {"labels": {"protohub.io/owner": "owner"}},
            "immutable": True,
            "type": "Opaque",
            "data": {"client-id": encode(CLIENT_ID), "client-secret": encode(CLIENT_SECRET)},
        }
        cluster = deploy.Cluster("private-dev")
        with patch.object(cluster, "run", return_value=json.dumps(obj)):
            safe = cluster.existing("Secret", deploy.GOOGLE_SECRET, deploy.SYSTEM)
        self.assertNotIn("data", safe)
        for change in (
            {"data": {}},
            {"data": {"client-id": "%%%", "client-secret": encode(CLIENT_SECRET)}},
            {"data": {"client-id": encode("bad"), "client-secret": encode(CLIENT_SECRET)}},
            {"data": {"client-id": encode(CLIENT_ID), "client-secret": encode(" ")}},
            {
                "metadata": {
                    "annotations": {"kubectl.kubernetes.io/last-applied-configuration": "bad"}
                }
            },
            {"immutable": False},
            {"type": "kubernetes.io/tls"},
        ):
            with (
                patch.object(cluster, "run", return_value=json.dumps(obj | change)),
                self.assertRaises(deploy.DeploymentError) as exc,
            ):
                cluster.existing("Secret", deploy.GOOGLE_SECRET, deploy.SYSTEM)
            self.assertNotIn(CLIENT_SECRET, str(exc.exception))
            self.assertNotIn(CLIENT_ID, str(exc.exception))

    def test_google_configuration_is_not_echoed_or_stored_in_apply_annotations(self):
        obj = deploy.validate_google_credentials(CLIENT_ID, CLIENT_SECRET)
        cluster = deploy.Cluster("private-dev")
        out = io.StringIO()
        with (
            patch.object(
                deploy.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, "", "")
            ) as run,
            redirect_stdout(out),
        ):
            deploy.install_secret(cluster, deploy.GOOGLE_SECRET, {}, obj)
        args, kwargs = run.call_args
        self.assertNotIn("--save-config", args[0])
        for value in obj.values():
            self.assertNotIn(value, str(args) + out.getvalue())
            self.assertIn(value, kwargs["input"])

    def test_external_origin_manifest_reconstruction_rejects_edits(self):
        from render import LOCAL_ORIGINS

        refs = [f"registry.example.org/demo/app@sha256:{'c' * 64}"] * 4
        desired = render(
            *refs, "approved-csi", "test", "https://web.example.org", "https://pv.example.org"
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "release.yaml"
            path.write_text(yaml.safe_dump_all(desired))
            self.assertEqual(deploy.read_manifest(path), desired)
            cfg = next(o["data"] for o in desired if o["kind"] == "ConfigMap")
            for value in (
                LOCAL_ORIGINS[0],
                "https://web.example.org",
                "https://different.example.org",
            ):
                cfg["PROTOHUB_PREVIEW_ORIGIN"] = value
                path.write_text(yaml.safe_dump_all(desired))
                with self.assertRaises(deploy.DeploymentError):
                    deploy.read_manifest(path)

    def test_update_uses_dry_run_and_at_most_one_versioned_replace(self):
        cluster = deploy.Cluster("private-dev")
        obj = {"kind": "Deployment", "metadata": {"name": "api"}}
        prev = {"metadata": {"resourceVersion": "20", "uid": "existing"}}
        merged = dict(obj, metadata=dict(prev["metadata"], name="api"))
        with patch.object(cluster, "run", side_effect=[json.dumps(merged), ""]) as run:
            cluster.install(obj, prev)
            self.assertIn("--dry-run=server", run.call_args_list[0].args[0])
            self.assertEqual(run.call_args.args[0][0], "replace")
            self.assertEqual(run.call_args.args[1]["metadata"]["resourceVersion"], "20")
            self.assertEqual(run.call_args.args[1]["metadata"]["uid"], "existing")
        with patch.object(cluster, "run", return_value=json.dumps(prev)) as run:
            cluster.install(obj, prev)
            self.assertEqual(run.call_count, 1)
        with patch.object(
            cluster,
            "run",
            return_value=json.dumps({"metadata": {"resourceVersion": "23", "uid": "other"}}),
        ) as run:
            with self.assertRaisesRegex(deploy.DeploymentError, "changed since preflight"):
                cluster.install(obj, prev)
            self.assertEqual(run.call_count, 1)

    def test_kubectl_uses_explicit_context_and_no_secret_in_logs_or_argv(self):
        cluster = deploy.Cluster("private-dev")
        obj = {"kind": "Deployment", "metadata": {"name": "api"}}
        out = io.StringIO()
        with (
            patch.object(
                deploy.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, "", "")
            ) as run,
            patch.object(deploy.secrets, "token_urlsafe", return_value="synthetic-private-value"),
            redirect_stdout(out),
        ):
            deploy.create_secret(cluster, {})
            args, kwargs = run.call_args
            self.assertEqual(args[0][:3], ["kubectl", "--context", "private-dev"])
            self.assertNotIn("synthetic-private-value", str(args) + out.getvalue())
            self.assertIn("synthetic-private-value", kwargs["input"])
            self.assertNotIn("--save-config", args[0])

        bad = subprocess.CompletedProcess([], 1, "", "sensitive-body")
        with patch.object(deploy.subprocess, "run", return_value=bad):
            with self.assertRaises(deploy.DeploymentError) as cm:
                cluster.install(obj, None)
            self.assertNotIn("sensitive-body", str(cm.exception))
        for context in ("", "-n", "two args"):
            with self.assertRaises(deploy.DeploymentError):
                deploy.Cluster(context)


if __name__ == "__main__":
    unittest.main()
