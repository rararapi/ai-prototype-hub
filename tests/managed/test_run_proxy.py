"""Offline rendering checks for both Cloud Run roles and reservation states."""

import json
import re
import subprocess
import sys
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "infra/managed"))
import run_proxy  # noqa: E402

BASE = {
    "role": "web",
    "service": "protohub-edge",
    "region": "asia-northeast1",
    "service_account": "edge-proxy@example-project.iam.gserviceaccount.com",
    "network": "protohub",
    "subnet": "run-edge",
}


class CloudRunProxyTests(unittest.TestCase):
    def test_manifest_limits_image_network_and_identity(self):
        for role in ("web", "preview"):
            for parked in (False, True):
                manifest = run_proxy.render(**{**BASE, "role": role}, parked=parked)
                self.assertEqual(manifest["kind"], "Service")
                self.assertEqual(manifest["apiVersion"], "serving.knative.dev/v1")
                metadata = manifest["metadata"]
                self.assertEqual(
                    metadata["labels"]["cloud.googleapis.com/location"], BASE["region"]
                )
                annotations = metadata["annotations"]
                self.assertEqual(annotations["run.googleapis.com/invoker-iam-disabled"], "false")
                self.assertEqual(annotations["run.googleapis.com/maxScale"], "1")
                template = manifest["spec"]["template"]
                spec, annotations = template["spec"], template["metadata"]["annotations"]
                self.assertEqual(spec["serviceAccountName"], BASE["service_account"])
                self.assertEqual(
                    annotations["run.googleapis.com/vpc-access-egress"], "private-ranges-only"
                )
                self.assertEqual(
                    json.loads(annotations["run.googleapis.com/network-interfaces"]),
                    [{"network": BASE["network"], "subnetwork": BASE["subnet"]}],
                )
                self.assertEqual(annotations["run.googleapis.com/cpu-throttling"], "true")
                self.assertEqual(annotations["autoscaling.knative.dev/minScale"], "0")
                self.assertEqual(annotations["autoscaling.knative.dev/maxScale"], "1")
                (container,) = spec["containers"]
                self.assertEqual(container["resources"]["limits"], {"cpu": "1", "memory": "512Mi"})
                digest = container["image"].removeprefix("docker.io/library/nginx@")
                self.assertRegex(digest, r"^sha256:[a-f0-9]{64}$")
                self.assertIn(digest, (ROOT / "infra/docker/web.Dockerfile").read_text())
                self.assertNotIn("env", container)
                self.assertEqual(
                    container["startupProbe"]["httpGet"], {"path": "/edge-healthz", "port": 8080}
                )
                subprocess.run(["sh", "-n"], input=container["args"][1], text=True, check=True)

    def test_parked_content_is_closed_without_a_backend(self):
        for role in ("web", "preview"):
            conf = run_proxy.nginx_config(role, True)
            self.assertIn("location / { return 503; }", conf)
            self.assertIn("location = /edge-healthz { return 200", conf)
            self.assertNotIn("proxy_pass", conf)
            self.assertNotIn("protohub.gke.internal", conf)

    def test_only_role_specific_backend_and_explicit_headers_are_forwarded(self):
        common = {
            "Host",
            "Connection",
            "Authorization",
            "Origin",
            "Accept",
            "Content-Type",
            "Access-Control-Request-Method",
            "Access-Control-Request-Headers",
        }
        for role, port in (("web", 8080), ("preview", 8081)):
            conf = run_proxy.nginx_config(role, False)
            self.assertIn(
                f"set $backend protohub-run-{role}.protohub-system.svc.protohub.gke.internal:{port};",
                conf,
            )
            self.assertIn("proxy_pass_request_headers off;", conf)
            names = set(re.findall(r"proxy_set_header (\S+) ", conf))
            self.assertEqual(
                names,
                common | ({"X-Requested-With", "X-ProtoHub-Client"} if role == "web" else set()),
            )
            self.assertIn("proxy_set_header Host localhost;", conf)
            self.assertIn("proxy_hide_header Set-Cookie;", conf)
            self.assertEqual(
                re.findall(r"proxy_pass ([^;]+);", conf),
                ["http://$backend/healthz", "http://$backend$request_uri"],
            )
            if role == "web":
                self.assertIn("add_header X-Frame-Options DENY always;", conf)
            else:
                self.assertIn("location / { return 404; }", conf)
                self.assertIn("location /apps/", conf)
                self.assertIn('if ($request_uri !~ "^/apps/")', conf)

    def test_supported_cli_and_invalid_configurations(self):
        args = [sys.executable, str(ROOT / "infra/managed/run_proxy.py"), "--parked"]
        for key, value in BASE.items():
            args += ["--" + key.replace("_", "-"), value]
        result = subprocess.run(args, capture_output=True, text=True, check=True)
        self.assertEqual(yaml.safe_load(result.stdout), run_proxy.render(**BASE, parked=True))
        for key, value in {
            "role": "http://other/",
            "service": "edge;printf",
            "region": "example",
            "service_account": "default",
            "network": "my/network",
            "subnet": "evil;return",
        }.items():
            with self.subTest(key=key), self.assertRaises(ValueError):
                run_proxy.render(**{**BASE, key: value})


NUMBER = "123456789012"
NAME = "protohub-edge"
REGION = BASE["region"]
URL = f"https://{NAME}-{NUMBER}.{REGION}.run.app"
PRIMARY = f"https://{NAME}-abcdefgh-an.a.run.app"


def sample_service(parked):
    service = run_proxy.render(**BASE, parked=parked)
    service["metadata"].update(namespace=NUMBER, uid="fixture-uid", generation=2)
    service["metadata"]["annotations"]["run.googleapis.com/urls"] = json.dumps([URL, PRIMARY])
    rev = NAME + "-00002-abc"
    service["status"] = {
        "url": PRIMARY,
        "observedGeneration": 2,
        "latestCreatedRevisionName": rev,
        "latestReadyRevisionName": rev,
        "conditions": [{"type": "Ready", "status": "True"}],
        "traffic": [{"percent": 100, "revisionName": rev, "latestRevision": True}],
    }
    return service


PROFILE = {
    "project": "example-project",
    "identity": BASE["service_account"],
    "network": BASE["network"],
    "subnet": BASE["subnet"],
}


class ReleaseVerifyTests(unittest.TestCase):
    def inspect(self, data, *, stage="parked", owner="protohub-managed", url=None, policy=None):
        return run_proxy.inspect_service(
            data, policy or {}, NAME, NUMBER, REGION, "web", owner, stage, PROFILE, url
        )

    def test_default_is_parked_and_live_requires_explicit_choice(self):
        args = [sys.executable, str(ROOT / "infra/managed/run_proxy.py")]
        for key, value in BASE.items():
            args += ["--" + key.replace("_", "-"), value]

        def read(suffix):
            return yaml.safe_load(
                subprocess.run(args + suffix, capture_output=True, text=True, check=True).stdout
            )

        self.assertEqual(read([]), read(["--parked"]))
        self.assertNotEqual(read([])["spec"], read(["--live"])["spec"])
        self.assertEqual(read([])["metadata"]["labels"]["protohub-owner"], "protohub-managed")
        self.assertEqual(
            read(["--live", "--owner", "team-fixture"])["metadata"]["labels"]["protohub-owner"],
            "team-fixture",
        )

    def test_legacy_read_only_and_owned_paths_are_mutually_exclusive(self):
        data = sample_service(True)
        self.assertEqual(self.inspect(data)["url"], URL)
        self.assertEqual(self.inspect(data, url=PRIMARY)["url"], PRIMARY)
        with self.assertRaises(ValueError):
            self.inspect(data, stage="legacy-parked")
        labels = data["metadata"]["labels"]
        del labels["protohub-profile"], labels["protohub-owner"]
        self.assertEqual(self.inspect(data, stage="legacy-parked")["uid"], "fixture-uid")
        with self.assertRaises(ValueError):
            self.inspect(data)

    def test_wrong_identity_unreported_hosts_or_stale_revision_are_rejected(self):
        cases = [
            (("metadata", "name"), "other"),
            (("metadata", "namespace"), "wrong-project"),
            (("metadata", "labels", "cloud.googleapis.com/location"), "us-central1"),
            (("metadata", "labels", "protohub-owner"), "different-owner"),
            (("metadata", "labels", "protohub-profile"), "different-profile"),
            (("metadata", "labels", "protohub-role"), "preview"),
            (("metadata", "annotations", "run.googleapis.com/invoker-iam-disabled"), "true"),
            (("status", "observedGeneration"), 1),
            (("status", "latestCreatedRevisionName"), "pending"),
            (("status", "traffic", 0, "tag"), "debug"),
            (("spec", "traffic", 0, "latestRevision"), False),
            (("status", "traffic", 0, "percent"), 50),
            (("spec", "template", "spec", "containers", 0, "command"), ["/bin/bash"]),
        ]
        for path, wrong in cases:
            data = sample_service(True)
            target = data
            for key in path[:-1]:
                target = target[key]
            target[path[-1]] = wrong
            with self.subTest(path=path), self.assertRaises(ValueError):
                self.inspect(data)
        for href in [
            "https://attacker.test",
            URL + "/next",
            URL + "?token=fixture",
            "https://tag---edge.run.app",
        ]:
            with self.subTest(href=href), self.assertRaises(ValueError):
                self.inspect(sample_service(True), url=href)
        bad = sample_service(True)
        bad["status"]["url"] = "https://attacker.test"
        with self.assertRaises(ValueError):
            self.inspect(bad, url=bad["status"]["url"])
        for principal in ["allUsers", "allAuthenticatedUsers"]:
            with self.assertRaises(ValueError):
                self.inspect(sample_service(True), policy={"bindings": [{"members": [principal]}]})
        with self.assertRaises(ValueError):
            self.inspect(sample_service(True), stage="live-private")
        public = sample_service(False)
        with self.assertRaises(ValueError):
            self.inspect(public, stage="live-public")
        public["metadata"]["annotations"]["run.googleapis.com/invoker-iam-disabled"] = "true"
        self.assertEqual(self.inspect(public, stage="live-public")["url"], URL)

    def test_actual_app_denials_are_required_and_private_token_is_not_app_bearer(self):
        services = {"web": {"url": URL}, "preview": {"url": URL.replace("edge-", "preview-")}}
        info = {
            "auth_mode": "google",
            "runtime_mode": "real-kind",
            "google_client_id": "fixture_with-underscore.apps.googleusercontent.com",
            "preview_origin": services["preview"]["url"],
        }
        replies = [
            (403, None),
            (403, None),
            (200, None),
            (200, None),
            (200, info),
            (401, {"error": {"code": "login_required"}}),
            (401, {"error": {"code": "login_required"}}),
            (401, {"error": "preview_auth_required"}),
        ]
        with (
            patch.object(run_proxy, "https_probe", side_effect=replies) as probe,
            patch.object(run_proxy, "cloud", return_value="fixture.id.token") as identity,
        ):
            run_proxy.verify_access(services, "live-private")
            identity.assert_called_once_with("auth", "print-identity-token")
            self.assertEqual(probe.call_args_list[0].args[2], None)
            self.assertEqual(probe.call_args_list[-1].args[2], "fixture.id.token")
        for i, bad in [
            (0, (200, None)),
            (4, (200, {**info, "auth_mode": "local-dev"})),
            (4, (200, {**info, "preview_origin": URL})),
            (5, (401, None)),
            (6, (200, {})),
            (7, (401, None)),
            (7, (302, None)),
        ]:
            changed = list(replies)
            changed[i] = bad
            with (
                self.subTest(step=i),
                patch.object(run_proxy, "https_probe", side_effect=changed),
                patch.object(run_proxy, "cloud", return_value="fixture.id.token"),
                self.assertRaises(ValueError),
            ):
                run_proxy.verify_access(services, "live-private")
        with (
            patch.object(run_proxy, "https_probe", side_effect=replies[2:]) as probe,
            patch.object(run_proxy, "cloud") as identity,
        ):
            run_proxy.verify_access(services, "live-public")
            identity.assert_not_called()
            self.assertTrue(all(c.args[2] is None for c in probe.call_args_list))
        with patch.object(run_proxy.http.client, "HTTPSConnection") as connect:
            response = connect.return_value.getresponse.return_value
            response.status = 401
            response.read.return_value = b'{"error":"preview_auth_required"}'
            run_proxy.https_probe(URL, "/apps/sample", "fixture.id.token", URL)
            connect.return_value.request.assert_called_once_with(
                "GET",
                "/apps/sample",
                headers={"Origin": URL, "X-Serverless-Authorization": "Bearer fixture.id.token"},
            )

    def test_changed_service_during_probe_refuses_a_release(self):
        with (
            patch.object(
                run_proxy,
                "cloud",
                return_value=json.dumps({"projectId": "example-project", "projectNumber": NUMBER}),
            ),
            patch.object(run_proxy, "observe_pair", side_effect=[{"web": "old"}, {"web": "new"}]),
            patch.object(run_proxy, "verify_access"),
            self.assertRaisesRegex(ValueError, "changed during verification"),
        ):
            run_proxy.verify(
                "example-project",
                REGION,
                NAME,
                "protohub-preview",
                "parked",
                BASE["service_account"],
                BASE["network"],
                BASE["subnet"],
            )

    def test_limits_network_and_direct_egress_are_checked_on_service_template(self):
        cases = [
            (("metadata", "annotations", "run.googleapis.com/minScale"), "1"),
            (("metadata", "annotations", "run.googleapis.com/maxScale"), "2"),
            (("metadata", "annotations", "run.googleapis.com/scalingMode"), "manual"),
            (
                ("spec", "template", "spec", "serviceAccountName"),
                "other@example-project.iam.gserviceaccount.com",
            ),
            (("spec", "template", "spec", "containers", 0, "resources", "limits", "cpu"), "2"),
            (("spec", "template", "spec", "containers", 0, "resources", "limits", "memory"), "1Gi"),
        ]
        for key, value in {
            "run.googleapis.com/network-interfaces": '[{"network":"different","subnetwork":"run-edge"}]',
            "run.googleapis.com/vpc-access-egress": "all-traffic",
            "run.googleapis.com/cpu-throttling": "false",
            "autoscaling.knative.dev/minScale": "1",
            "autoscaling.knative.dev/maxScale": "4",
        }.items():
            cases.append((("spec", "template", "metadata", "annotations", key), value))
        for path, value in cases:
            service = sample_service(True)
            target = service
            for key in path[:-1]:
                target = target[key]
            target[path[-1]] = value
            with self.subTest(path=path), self.assertRaises(ValueError):
                self.inspect(service)
        network = "projects/example-project/global/networks/protohub"
        subnet = "projects/" + NUMBER + "/regions/" + REGION + "/subnetworks/run-edge"
        service = sample_service(True)
        annotations = service["spec"]["template"]["metadata"]["annotations"]
        for expected, iface in [
            (True, {"network": network, "subnetwork": subnet}),
            (
                False,
                {
                    "network": network.replace("example-project", "outside-project"),
                    "subnetwork": subnet,
                },
            ),
            (False, {"network": network, "subnetwork": subnet.replace("run-edge", "other")}),
        ]:
            annotations["run.googleapis.com/network-interfaces"] = json.dumps([iface])
            if expected:
                self.inspect(service)
            else:
                with self.assertRaises(ValueError):
                    self.inspect(service)

    def test_actual_serving_revision_must_match_identity_image_billing_and_vpc(self):
        service = sample_service(True)
        observed = self.inspect(service)
        template = service["spec"]["template"]
        image = "mirror.gcr.io/library/nginx@" + next(iter(run_proxy.LINUX_AMD64.values()))

        def revision():
            rev = deepcopy(template)
            rev.update(
                apiVersion="serving.knative.dev/v1",
                kind="Revision",
                status={
                    "conditions": [{"type": "Ready", "status": "True"}],
                    "imageDigest": image,
                    "observedGeneration": 1,
                },
            )
            rev["metadata"].update(
                name=observed["revision"],
                namespace=NUMBER,
                uid="fixture-rev",
                generation=1,
                labels={
                    "serving.knative.dev/service": NAME,
                    "serving.knative.dev/serviceUid": observed["uid"],
                    "cloud.googleapis.com/location": REGION,
                },
            )
            rev["spec"]["containers"][0]["image"] = image
            return rev

        def check(rev):
            return run_proxy.inspect_revision(
                rev, observed, NAME, NUMBER, REGION, role="web", parked=True, **PROFILE
            )

        self.assertEqual(check(revision()), "fixture-rev")
        for path, wrong in [
            (("metadata", "name"), "stale-revision"),
            (("status", "imageDigest"), run_proxy.runtime_image()),
            (("status", "observedGeneration"), 0),
            (("metadata", "labels", "serving.knative.dev/serviceUid"), "wrong-service-uid"),
            (("metadata", "annotations", "run.googleapis.com/vpc-access-egress"), "all-traffic"),
            (("metadata", "annotations", "autoscaling.knative.dev/minScale"), "2"),
            (("metadata", "annotations", "run.googleapis.com/cpu-throttling"), "false"),
            (("spec", "serviceAccountName"), "other@example-project.iam.gserviceaccount.com"),
            (("spec", "containers", 0, "image"), image.replace("mirror.gcr.io", "other.invalid")),
        ]:
            rev = revision()
            target = rev
            for k in path[:-1]:
                target = target[k]
            target[path[-1]] = wrong
            with self.subTest(path=path), self.assertRaises(ValueError):
                check(rev)

    def test_windows_cli_wrapper_is_resolved_before_subprocess(self):
        with (
            patch.object(run_proxy.shutil, "which", return_value="C:/sdk/bin/gcloud.cmd"),
            patch.object(
                run_proxy.subprocess,
                "run",
                return_value=subprocess.CompletedProcess([], 0, stdout="ok"),
            ) as call,
        ):
            self.assertEqual(run_proxy.cloud("projects", "describe", "example-project"), "ok")
        self.assertEqual(call.call_args.args[0][0], "C:/sdk/bin/gcloud.cmd")
