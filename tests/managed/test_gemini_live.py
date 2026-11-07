"""Guard tests; these never contact Kubernetes or a model."""

import importlib.util
import unittest
from pathlib import Path
from unittest.mock import patch

spec = importlib.util.spec_from_file_location(
    "gemini_live", Path(__file__).resolve().parents[2] / "scripts/checks/gemini_live.py"
)
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


class GeminiLiveGuards(unittest.TestCase):
    def test_no_opt_in_never_executes_a_probe(self):
        with (
            patch("sys.argv", ["gemini_live.py"]),
            patch.object(probe, "execute", side_effect=AssertionError("network forbidden")),
        ):
            self.assertEqual(probe.main(), 78)

    def test_foreign_owner_or_token_mount_is_rejected_before_a_model_call(self):
        config = {
            "owner": "owned",
            "server_image": "registry.example.test/server@sha256:" + "a" * 64,
        }
        deployment = {
            "metadata": {
                "uid": "deploy",
                "labels": {
                    "protohub.io/owner": "foreign",
                    "app.kubernetes.io/managed-by": "protohub",
                },
            },
            "spec": {
                "template": {
                    "spec": {
                        "serviceAccountName": "protohub-api",
                        "automountServiceAccountToken": False,
                    }
                }
            },
        }
        with self.assertRaises(probe.ProbeError):
            probe.inspect_pod(config, deployment, {"items": []}, {"items": []})
        deployment["metadata"]["labels"]["protohub.io/owner"] = "owned"
        deployment["spec"]["template"]["spec"]["automountServiceAccountToken"] = True
        with self.assertRaises(probe.ProbeError):
            probe.inspect_pod(config, deployment, {"items": []}, {"items": []})

    def test_ready_pod_must_belong_to_current_deployment_and_digest(self):
        digest = "sha256:" + "a" * 64
        image = "registry.example.test/server@" + digest
        config = {"owner": "owned", "server_image": image}
        podspec = {
            "serviceAccountName": "protohub-api",
            "automountServiceAccountToken": False,
            "containers": [{"name": "api", "image": image}],
        }
        deployment = {
            "metadata": {
                "uid": "deploy",
                "labels": {
                    "protohub.io/owner": "owned",
                    "app.kubernetes.io/managed-by": "protohub",
                },
            },
            "spec": {"template": {"spec": podspec}},
        }
        replicas = {"items": [{"metadata": {"uid": "rs", "ownerReferences": [{"uid": "deploy"}]}}]}
        pod = {
            "metadata": {"uid": "pod", "name": "api-pod", "ownerReferences": [{"uid": "rs"}]},
            "spec": podspec,
            "status": {
                "conditions": [{"type": "Ready", "status": "True"}],
                "containerStatuses": [{"name": "api", "ready": True, "imageID": image}],
            },
        }
        self.assertEqual(
            probe.inspect_pod(config, deployment, replicas, {"items": [pod]})["metadata"]["uid"],
            "pod",
        )
        pod["status"]["containerStatuses"][0]["imageID"] = (
            "registry.example.test/server@sha256:" + "b" * 64
        )
        with self.assertRaises(probe.ProbeError):
            probe.inspect_pod(config, deployment, replicas, {"items": [pod]})
