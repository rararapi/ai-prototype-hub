import json
import re
import shlex
import subprocess
import sys
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "infra/managed"))
from render import render  # noqa: E402

VALUES = {
    f"{key}_image": f"registry.example.com/demo/{key}@sha256:" + str(i) * 64
    for i, key in enumerate(("server", "web", "sample", "postgres"), 1)
}
VALUES.update(storage_class="managed-csi", owner="test-team")


class ManagedRendererTest(unittest.TestCase):
    def setUp(self):
        self.docs = render(**VALUES)
        self.lookup = {(d["kind"], d["metadata"]["name"]): d for d in self.docs}

    def test_namespaces_policies_and_ownership(self):
        self.assertEqual([d["kind"] for d in self.docs[:2]], ["Namespace", "Namespace"])
        self.assertEqual(
            {d["metadata"]["name"] for d in self.docs[:2]}, {"protohub-system", "protohub-samples"}
        )
        policies = [i for i, d in enumerate(self.docs) if d["kind"] == "NetworkPolicy"]
        self.assertTrue(policies)
        self.assertEqual(policies, list(range(2, 2 + len(policies))))
        for d in self.docs:
            labels = d["metadata"]["labels"]
            self.assertEqual(labels["app.kubernetes.io/managed-by"], "protohub")
            self.assertEqual(labels["protohub.io/owner"], "test-team")
            self.assertEqual(labels["protohub.io/profile"], "managed")
            if d["kind"] == "Namespace":
                self.assertEqual(labels["pod-security.kubernetes.io/enforce"], "restricted")
            else:
                self.assertIn(d["metadata"]["namespace"], {"protohub-system", "protohub-samples"})

    def test_private_services_storage_and_config(self):
        for d in self.docs:
            if d["kind"] == "Service":
                self.assertEqual(d["spec"].get("type", "ClusterIP"), "ClusterIP")
                self.assertTrue(all("nodePort" not in p for p in d["spec"]["ports"]))
        self.assertEqual(
            self.lookup["PersistentVolumeClaim", "protohub-db"]["spec"]["storageClassName"],
            "managed-csi",
        )
        cfg = self.lookup["ConfigMap", "protohub-config"]["data"]
        self.assertNotIn("PROTOHUB_DATABASE_URL", cfg)
        self.assertEqual(cfg["PROTOHUB_ENVIRONMENT"], "production")
        self.assertEqual(cfg["PROTOHUB_RUNTIME_MODE"], "real-kind")
        self.assertEqual(cfg["PROTOHUB_CONSOLE_ORIGIN"], "http://localhost:8080")
        self.assertEqual(cfg["PROTOHUB_PREVIEW_ORIGIN"], "http://localhost:8081")
        self.assertEqual(json.loads(cfg["PROTOHUB_ALLOWED_HOSTS"]), ["localhost", "127.0.0.1"])
        self.assertEqual(cfg["PROTOHUB_SAMPLE_IMAGE"], VALUES["sample_image"])
        plain = yaml.safe_dump_all(self.docs)
        for forbidden in (
            "local-dev@db",
            "value: local-dev",
            "PROTOHUB_LLM_API_KEY",
            "${",
            "kind: Secret\n",
        ):
            self.assertNotIn(forbidden, plain)

    def test_gemini_is_explicit_api_only_and_has_no_kubernetes_token_or_rbac(self):
        docs = render(**VALUES, ai_project="example-project")
        lookup = {(d["kind"], d["metadata"]["name"]): d for d in docs}
        account = lookup["ServiceAccount", "protohub-api"]
        self.assertFalse(account["automountServiceAccountToken"])
        self.assertEqual(account["metadata"]["namespace"], "protohub-system")
        for document in docs:
            if document["kind"] == "Deployment":
                pod = document["spec"]["template"]["spec"]
                for container in pod["containers"]:
                    env = {e["name"]: e.get("value") for e in container.get("env", [])}
                    if container["name"] == "api":
                        self.assertEqual(pod["serviceAccountName"], "protohub-api")
                        self.assertFalse(pod["automountServiceAccountToken"])
                        self.assertEqual(env["PROTOHUB_AI_ENABLED"], "true")
                        self.assertEqual(env["PROTOHUB_AI_VERTEX_PROJECT"], "example-project")
                    else:
                        self.assertNotIn("PROTOHUB_AI_ENABLED", env)
            if document["kind"] in {"RoleBinding", "ClusterRoleBinding"}:
                self.assertNotIn(
                    "protohub-api", [s.get("name") for s in document.get("subjects", [])]
                )
        for changes in (
            {"ai_project": "bad/project"},
            {"ai_project": "example-project", "ai_model": "https://untrusted.invalid"},
            {"ai_project": "example-project", "ai_location": "global/elsewhere"},
            {"ai_location": "asia-northeast1"},
        ):
            with self.assertRaises(ValueError):
                render(**VALUES, **changes)

    def test_gemini_manifest_is_exactly_reconstructable_and_rejects_tampering(self):
        import tempfile

        from deploy import DeploymentError, read_manifest

        documents = render(**VALUES, ai_project="example-project")
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "gemini.yaml"
            path.write_text(yaml.safe_dump_all(documents, sort_keys=False))
            self.assertEqual(read_manifest(path), documents)
            account = next(
                d
                for d in documents
                if d["kind"] == "ServiceAccount" and d["metadata"]["name"] == "protohub-api"
            )
            account["automountServiceAccountToken"] = True
            path.write_text(yaml.safe_dump_all(documents, sort_keys=False))
            with self.assertRaises(DeploymentError):
                read_manifest(path)

    def test_images_and_database_secret_consumers(self):
        expected = {
            "migrate": "server",
            "api": "server",
            "worker": "server",
            "preview": "server",
            "postgres": "postgres",
            "web": "web",
        }
        seen = set()
        for d in self.docs:
            if d["kind"] != "Deployment":
                continue
            pod = d["spec"]["template"]["spec"]
            self.assertEqual(pod["automountServiceAccountToken"], d["metadata"]["name"] == "worker")
            for c in pod.get("initContainers", []) + pod["containers"]:
                name = c["name"]
                seen.add(name)
                self.assertEqual(c["image"], VALUES[f"{expected[name]}_image"])
                secrets = {
                    e["name"]: e["valueFrom"]["secretKeyRef"]
                    for e in c.get("env", [])
                    if "valueFrom" in e and "secretKeyRef" in e["valueFrom"]
                }
                if name == "web":
                    self.assertFalse(secrets)
                    continue
                variable, key = (
                    ("POSTGRES_PASSWORD", "password")
                    if name == "postgres"
                    else ("PROTOHUB_DATABASE_URL", "database-url")
                )
                self.assertEqual(secrets[variable]["name"], "protohub-db-credentials")
                self.assertEqual(secrets[variable]["key"], key)
                self.assertFalse(secrets[variable].get("optional", False))
        self.assertEqual(seen, set(expected))

    def test_google_login_credentials_are_required_only_on_the_api(self):
        expected = {
            "api": {
                "PROTOHUB_GOOGLE_CLIENT_ID": "client-id",
                "PROTOHUB_GOOGLE_CLIENT_SECRET": "client-secret",
            }
        }
        for d in self.docs:
            if d["kind"] == "ConfigMap":
                self.assertFalse(any("GOOGLE" in k for k in d["data"]))
            if d["kind"] != "Deployment":
                continue
            pod = d["spec"]["template"]["spec"]
            for c in pod["containers"] + pod.get("initContainers", []):
                env = {e["name"]: e for e in c.get("env", [])}
                if c["name"] in ("api", "preview"):
                    self.assertEqual(env.pop("PROTOHUB_GOOGLE_LOGIN")["value"], "true")
                refs = {k: v for k, v in env.items() if k.startswith("PROTOHUB_GOOGLE_")}
                keys = expected.get(c["name"], {})
                self.assertEqual(set(refs), set(keys))
                for key, value in refs.items():
                    self.assertEqual(
                        value["valueFrom"]["secretKeyRef"],
                        {"name": "protohub-google-oauth", "key": keys[key]},
                    )

    def test_https_origins_and_rollouts(self):
        origins = "https://console.example.org", "https://preview.example.org"
        desired = render(**VALUES, console_origin=origins[0], preview_origin=origins[1])
        for obj in desired:
            kind, name = obj["kind"], obj["metadata"]["name"]
            if kind == "ConfigMap":
                self.assertEqual(obj["data"]["PROTOHUB_CONSOLE_ORIGIN"], origins[0])
                self.assertEqual(obj["data"]["PROTOHUB_PREVIEW_ORIGIN"], origins[1])
                self.assertEqual(
                    json.loads(obj["data"]["PROTOHUB_ALLOWED_HOSTS"]), ["localhost", "127.0.0.1"]
                )
            if kind == "Deployment":
                template = obj["spec"]["template"]
                previous = self.lookup[kind, name]["spec"]["template"]
                self.assertEqual(template != previous, name in ("api", "worker", "preview"))
            if kind == "Service":
                self.assertEqual(obj["spec"]["type"], "ClusterIP")
            if kind == "NetworkPolicy":
                self.assertEqual(obj, self.lookup[kind, name])

    def test_https_origins_are_a_pair_of_distinct_canonical_hosts(self):
        valid = "https://console.example.org"
        bad = [
            None,
            valid,
            "http://preview.example.org",
            "https://*.example.org",
            "https://user@preview.example.org",
            "https://preview.example.org/",
            "https://preview.example.org?x=1",
            "https://preview.example.org#fragment",
            "https://127.0.0.1",
            "https://example.localhost",
            "https://preview.example.org:8443",
            "https://preview.example.org:443",
            "https://x.example.org\n",
        ]
        for value in bad:
            with self.subTest(value=value), self.assertRaises(ValueError):
                render(**VALUES, console_origin=valid, preview_origin=value)
        with self.assertRaises(ValueError):
            render(**VALUES, preview_origin=valid)

    def test_new_sample_digest_rolls_only_the_worker(self):
        replacement = VALUES["sample_image"].replace("3" * 64, "b" * 64)
        updated = render(**dict(VALUES, sample_image=replacement))
        changed = []
        for obj in updated:
            if obj["kind"] == "Deployment":
                name = obj["metadata"]["name"]
                if obj["spec"]["template"] != self.lookup["Deployment", name]["spec"]["template"]:
                    changed.append(name)
        self.assertEqual(changed, ["worker"])
        worker = next(
            d for d in updated if d["kind"] == "Deployment" and d["metadata"]["name"] == "worker"
        )
        self.assertEqual(
            worker["spec"]["template"]["metadata"]["annotations"]["protohub.io/sample-image"],
            replacement,
        )

    def test_reject_invalid_inputs(self):
        invalid = {
            "server_image": [
                "team/server:latest",
                "/bad@sha256:" + "a" * 64,
                VALUES["server_image"] + "\nkind: Secret",
                VALUES["server_image"][:-1],
            ],
            "web_image": ["https://example.com/web"],
            "sample_image": ["sample:latest"],
            "postgres_image": ["postgres:17"],
            "storage_class": ["", "../x", "a" * 254],
            "owner": ["", "-team", "a" * 64, "team\nlabels:"],
        }
        for field, candidates in invalid.items():
            for bad in candidates:
                with self.subTest(field=field, bad=bad), self.assertRaises(ValueError):
                    render(**{**VALUES, field: bad})

    def test_documented_builds_use_the_correct_dockerfiles_and_context(self):
        guide = (ROOT / "docs/MANAGED_KUBERNETES.md").read_text(encoding="utf-8")
        snippets = re.findall(r"```bash\n(.*?)\n```", guide, re.S)
        self.assertTrue(snippets)
        for snippet in snippets:
            subprocess.run(["bash", "-n"], input=snippet, check=True, text=True)
        builds = [
            shlex.split(line)
            for line in guide.splitlines()
            if line.startswith("docker buildx build ")
        ]
        self.assertEqual(len(builds), 3)
        dockerfiles = set()
        for argv in builds:
            dockerfile = argv[argv.index("-f") + 1]
            dockerfiles.add(dockerfile)
            self.assertTrue((ROOT / dockerfile).is_file())
            self.assertEqual(argv[-1], ".")
            if dockerfile.endswith("server.Dockerfile"):
                self.assertEqual(argv[argv.index("--target") + 1], "runtime")
        self.assertEqual(
            dockerfiles,
            {
                "infra/docker/web.Dockerfile",
                "infra/docker/server.Dockerfile",
                "examples/hello-web/Dockerfile",
            },
        )

    def test_cli_outputs_equivalent_yaml(self):
        argv = [sys.executable, str(ROOT / "infra/managed/render.py")]
        for name, value in VALUES.items():
            argv.extend(["--" + name.replace("_", "-"), value])
        result = subprocess.run(argv, cwd="/", check=True, text=True, capture_output=True)
        self.assertEqual(list(yaml.safe_load_all(result.stdout)), self.docs)
