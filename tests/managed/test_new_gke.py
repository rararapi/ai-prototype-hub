import contextlib
import io
import sys
import unittest
from dataclasses import asdict, replace
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "infra/managed"))
from new_gke import NODE_ROLE, READER, WRITER, Plan, main, provision  # noqa: E402


def example_plan():
    return Plan(
        project="example-project",
        zone="us-central1-a",
        cluster="protohub",
        network="dev-network",
        subnet="dev-subnet",
        pod_range="dev-pods",
        service_range="dev-services",
        master_cidr="172.16.42.0/28",
        admin_cidr="10.20.1.0/24",
        node_service_account="cluster-nodes@example-project.iam.gserviceaccount.com",
        registry="protohub",
        owner="dev-team",
        writer_member="user:publisher@example.test",
    )


class FakeCloud:
    def __init__(self, plan):
        self.command_keys = {tuple(command): name for name, command in plan.commands().items()}
        link = f"projects/{plan.project}/global/networks/{plan.network}"
        self.replies = {
            "network": {"name": plan.network, "selfLink": link},
            "subnet": {
                "name": plan.subnet,
                "network": link,
                "ipCidrRange": "10.50.0.0/22",
                "privateIpGoogleAccess": True,
                "secondaryIpRanges": [
                    {"rangeName": plan.pod_range, "ipCidrRange": "10.52.0.0/16"},
                    {"rangeName": plan.service_range, "ipCidrRange": "10.54.0.0/20"},
                ],
            },
            "account": {"email": plan.node_service_account},
            "roles": {
                "bindings": [
                    {"role": NODE_ROLE, "members": ["serviceAccount:" + plan.node_service_account]}
                ]
            },
            "repo": {"format": "DOCKER", "mode": "STANDARD_REPOSITORY", "labels": plan.labels},
            "cluster": {
                "location": plan.zone,
                "status": "RUNNING",
                "resourceLabels": plan.labels,
                "network": plan.network,
                "subnetwork": plan.subnet,
                "networkConfig": {
                    "datapathProvider": "ADVANCED_DATAPATH",
                    "gatewayApiConfig": {"channel": "CHANNEL_STANDARD"},
                },
                "workloadIdentityConfig": {"workloadPool": plan.project + ".svc.id.goog"},
                "ipAllocationPolicy": {
                    "clusterSecondaryRangeName": plan.pod_range,
                    "servicesSecondaryRangeName": plan.service_range,
                },
                "nodePools": [
                    {
                        "config": {"serviceAccount": plan.node_service_account},
                        "networkConfig": {"enablePrivateNodes": True},
                    }
                ],
                "privateClusterConfig": {"masterIpv4CidrBlock": plan.master_cidr},
                "controlPlaneEndpointsConfig": {
                    "dnsEndpointConfig": {"allowExternalTraffic": False},
                    "ipEndpointsConfig": {
                        "enablePublicEndpoint": False,
                        "privateEndpoint": "172.16.42.2",
                        "enabled": True,
                        "authorizedNetworksConfig": {
                            "enabled": True,
                            "privateEndpointEnforcementEnabled": True,
                            "cidrBlocks": [{"cidrBlock": plan.admin_cidr}],
                        },
                    },
                },
            },
            "repos": [],
            "clusters": [],
            "policy": {"bindings": []},
        }
        if plan.run_app_profile:
            self.replies["dns_zones"] = []
            self.replies["dns_project"] = {"projectId": plan.project, "projectNumber": "321654987"}
            cluster = self.replies["cluster"]
            cluster["id"] = "1234abcde987f000"
            cluster["currentNodeCount"] = 1
            cluster["nodePools"][0]["config"].update(
                machineType="e2-medium", diskSizeGb=30, diskType="pd-balanced"
            )
            cluster["networkConfig"].update(
                gatewayApiConfig={"channel": "CHANNEL_DISABLED"},
                dnsConfig={
                    "clusterDns": "CLOUD_DNS",
                    "clusterDnsScope": "CLUSTER_SCOPE",
                    "additiveVpcScopeDnsDomain": "protohub.gke.internal",
                },
            )
            cluster["addonsConfig"] = {
                "httpLoadBalancing": {"disabled": True},
                "gcePersistentDiskCsiDriverConfig": {"enabled": True},
                "gcpFilestoreCsiDriverConfig": {},
                "horizontalPodAutoscaling": {"disabled": True},
            }
            cluster["monitoringConfig"] = {
                "componentConfig": {"enableComponents": ["SYSTEM_COMPONENTS"]},
                "managedPrometheusConfig": {},
            }
        self.plan = plan
        self.calls = []
        self.fail_on = None

    def zone(self, domain, network=None):
        plan = self.plan
        network = network or f"projects/{plan.project}/global/networks/{plan.network}"
        return {
            "name": f"gke-{plan.cluster}-1234-dns-vpc",
            "description": (
                f'Private zone for GKE cluster "{plan.cluster}" with cluster suffix "{domain}" '
                f'in project "{plan.project}" with scope "VPC_SCOPE"'
            ),
            "labels": {"goog-gke-node": ""},
            "visibility": "private",
            "dnsName": domain,
            "privateVisibilityConfig": {"networks": [{"networkUrl": network}]},
        }

    def run(self, command):
        key = self.command_keys[tuple(command)]
        self.calls.append(key)
        if key == self.fail_on:
            raise ValueError("simulated command failure")
        if key == "create_repo":
            self.replies["repos"].append({"name": self.plan.registry})
        elif key == "create_cluster":
            self.replies["clusters"].append({"name": self.plan.cluster, "location": self.plan.zone})
            if self.plan.run_app_profile:
                self.replies["dns_zones"].append(self.zone("protohub.gke.internal."))
        elif key in {"reader", "writer"}:
            role, member = (
                (READER, "serviceAccount:" + self.plan.node_service_account)
                if key == "reader"
                else (WRITER, self.plan.writer_member)
            )
            self.replies["policy"]["bindings"].append({"role": role, "members": [member]})
        return self.replies.get(key)

    def mutations(self):
        return [k for k in self.calls if k in {"create_repo", "create_cluster", "reader", "writer"}]


class NewGkeTests(unittest.TestCase):
    def test_default_cli_prints_scoped_commands_without_subprocess(self):
        plan = example_plan()
        args = []
        for name, value in asdict(plan).items():
            if name == "run_app_profile":
                continue
            args += ["--" + name.replace("_", "-"), value]
        output = io.StringIO()
        with (
            patch("new_gke.subprocess.run", side_effect=AssertionError("unexpected gcloud call")),
            contextlib.redirect_stdout(output),
        ):
            self.assertEqual(main(args), 0)
        self.assertIn("gcloud container clusters create", output.getvalue())
        for command in plan.commands().values():
            self.assertIn("--project=" + plan.project, command)
        create = plan.commands()["create_cluster"]
        for flag in (
            "--enable-dataplane-v2",
            "--gateway-api=standard",
            "--addons=HttpLoadBalancing=ENABLED,HorizontalPodAutoscaling=ENABLED,GcePersistentDiskCsiDriver=ENABLED",
            "--enable-private-nodes",
            "--enable-private-endpoint",
            "--enable-authorized-networks-on-private-endpoint",
            "--no-enable-google-cloud-access",
            "--no-enable-dns-access",
            "--num-nodes=1",
        ):
            self.assertIn(flag, create)

    def test_run_app_profile_preserves_default_identity_and_parameters(self):
        base = example_plan()
        self.assertEqual(base.labels["protohub-plan"], "a8504712e4c7cc30b4b58ca04f0906bc")
        run_app = replace(base, run_app_profile=True)
        self.assertNotEqual(run_app.labels, base.labels)
        flags = run_app.commands()["create_cluster"]
        for option in (
            "--num-nodes=1",
            "--machine-type=e2-medium",
            "--disk-size=30",
            "--disk-type=pd-balanced",
            "--enable-private-nodes",
            "--enable-private-endpoint",
            "--enable-dataplane-v2",
            "--gateway-api=disabled",
            "--cluster-dns=clouddns",
            "--cluster-dns-scope=cluster",
            "--additive-vpc-scope-dns-domain=protohub.gke.internal",
            "--monitoring=SYSTEM",
            "--no-enable-managed-prometheus",
            "--addons=HttpLoadBalancing=DISABLED,HorizontalPodAutoscaling=DISABLED,"
            "GcpFilestoreCsiDriver=DISABLED,GcePersistentDiskCsiDriver=ENABLED",
        ):
            self.assertIn(option, flags)
        self.assertNotIn("--spot", flags)
        args = ["--run-app-profile"]
        for name, value in asdict(base).items():
            if name != "run_app_profile":
                args += ["--" + name.replace("_", "-"), value]
        with (
            patch("new_gke.subprocess.run", side_effect=AssertionError("gcloud called")),
            contextlib.redirect_stdout(io.StringIO()) as out,
        ):
            self.assertEqual(main(args), 0)
        self.assertIn("--machine-type=e2-medium", out.getvalue())
        self.assertNotIn("--machine-type=e2-standard-2", out.getvalue())

    def test_run_app_profile_create_reuse_and_foreign_dns(self):
        plan = replace(example_plan(), run_app_profile=True)
        cloud = FakeCloud(plan)
        cloud.replies["dns_zones"] = [
            {"dnsName": "protohub.gke.internal.", "visibility": "private"}
        ]
        with self.assertRaisesRegex(ValueError, "DNS domain"):
            provision(plan, cloud.run)
        self.assertEqual(cloud.mutations(), [])
        cloud.replies["dns_zones"] = []
        provision(plan, cloud.run)
        self.assertEqual(cloud.mutations(), ["create_repo", "reader", "writer", "create_cluster"])
        cloud.calls.clear()
        provision(plan, cloud.run)
        self.assertFalse(cloud.mutations())
        self.assertIn("dns_zones", cloud.calls)

    def test_backend_zones_reject_delegated_names_on_create_and_reuse(self):
        plan = replace(example_plan(), run_app_profile=True)
        for exists in (False, True):
            for domain in (
                "svc.protohub.gke.internal.",
                "protohub-system.svc.protohub.gke.internal.",
                "protohub-run-web.protohub-system.svc.protohub.gke.internal.",
                "protohub-run-preview.protohub-system.svc.protohub.gke.internal.",
            ):
                with self.subTest(exists=exists, domain=domain):
                    cloud = FakeCloud(plan)
                    if exists:
                        provision(plan, cloud.run)
                    cloud.calls.clear()
                    cloud.replies["dns_zones"].append(cloud.zone(domain))
                    with self.assertRaisesRegex(ValueError, "overrides"):
                        provision(plan, cloud.run)
                    self.assertEqual(cloud.mutations(), [])

    def test_irrelevant_zones_and_other_vpcs_do_not_block(self):
        plan = replace(example_plan(), run_app_profile=True)
        cloud = FakeCloud(plan)
        cloud.replies["dns_zones"] = [
            cloud.zone("other.protohub.gke.internal."),
            cloud.zone("example.internal."),
            cloud.zone(
                "protohub-system.svc.protohub.gke.internal.",
                "projects/example-project/global/networks/other-vpc",
            ),
            cloud.zone(
                "protohub.gke.internal.", "projects/other-project/global/networks/dev-network"
            ),
        ]
        provision(plan, cloud.run)
        cloud.calls.clear()
        provision(plan, cloud.run)
        self.assertEqual(cloud.mutations(), [])

    def test_reuse_requires_only_expected_authoritative_base_in_vpc(self):
        plan = replace(example_plan(), run_app_profile=True)
        for failure in (
            "missing",
            "wrong_name",
            "peering",
            "forward",
            "extra_network",
            "long_hash",
            "missing_label",
            "incorrect_description",
            "unknown_scope",
            "duplicate",
        ):
            with self.subTest(failure=failure):
                cloud = FakeCloud(plan)
                provision(plan, cloud.run)
                zones = cloud.replies["dns_zones"]
                if failure == "missing":
                    zones.clear()
                elif failure == "wrong_name":
                    zones[0]["name"] = "gke-someone-else-1234abcd-dns-vpc"
                elif failure == "long_hash":
                    zones[0]["name"] = f"gke-{plan.cluster}-1234abcd-dns-vpc"
                elif failure == "missing_label":
                    del zones[0]["labels"]
                elif failure == "incorrect_description":
                    zones[0]["description"] = zones[0]["description"].replace(
                        "VPC_SCOPE", "CLUSTER_SCOPE"
                    )
                elif failure in {"peering", "forward"}:
                    zones[0]["peeringConfig" if failure == "peering" else "forwardingConfig"] = {}
                elif failure == "extra_network":
                    zones[0]["privateVisibilityConfig"]["networks"].append(
                        {"networkUrl": "projects/other-project/global/networks/other"}
                    )
                elif failure == "unknown_scope":
                    zones[0]["privateVisibilityConfig"] = {}
                else:
                    zones.append(dict(zones[0]))
                cloud.calls.clear()
                with self.assertRaises(ValueError):
                    provision(plan, cloud.run)
                self.assertEqual(cloud.mutations(), [])

    def test_run_app_profile_rejects_live_setting_drift_before_changes(self):
        plan = replace(example_plan(), run_app_profile=True)
        paths = [
            (("resourceLabels", "protohub-plan"), example_plan().labels["protohub-plan"]),
            (("currentNodeCount",), 2),
            (("nodePools", 0, "config", "machineType"), "e2-standard-2"),
            (("nodePools", 0, "config", "bootDisk"), {"sizeGb": "50", "diskType": "pd-balanced"}),
            (("nodePools", 0, "config", "diskType"), "pd-ssd"),
            (("nodePools", 0, "config", "spot"), True),
            (("nodePools", 0, "autoscaling"), {"enabled": True}),
            (("networkConfig", "dnsConfig", "additiveVpcScopeDnsDomain"), "other.test"),
            (("networkConfig", "dnsConfig", "clusterDnsScope"), "VPC_SCOPE"),
            (("networkConfig", "gatewayApiConfig", "channel"), "CHANNEL_STANDARD"),
            (("addonsConfig", "httpLoadBalancing", "disabled"), False),
            (("addonsConfig", "gcePersistentDiskCsiDriverConfig", "enabled"), False),
            (("addonsConfig", "gcpFilestoreCsiDriverConfig", "enabled"), True),
            (("addonsConfig", "horizontalPodAutoscaling", "disabled"), False),
            (("monitoringConfig", "managedPrometheusConfig", "enabled"), True),
            (("monitoringConfig", "managedPrometheusConfig"), None),
            (
                ("monitoringConfig", "componentConfig", "enableComponents"),
                ["SYSTEM_COMPONENTS", "POD"],
            ),
        ]
        for path, value in paths:
            with self.subTest(path=path):
                cloud = FakeCloud(plan)
                cloud.replies["clusters"] = [{"name": plan.cluster, "location": plan.zone}]
                node = cloud.replies["cluster"]
                for key in path[:-1]:
                    node = node[key]
                node[path[-1]] = value
                with self.assertRaises(ValueError):
                    provision(plan, cloud.run)
                self.assertEqual(cloud.mutations(), [])

    def test_reject_unsafe_values_locally(self):
        plan = example_plan()
        for name, value in [
            ("project", "$(touch x)"),
            ("network", "parent/example"),
            ("zone", "us-central1"),
            ("admin_cidr", "0.0.0.0/0"),
            ("admin_cidr", "10.0.0.0/8"),
            ("admin_cidr", "8.8.8.8/32"),
            ("master_cidr", "192.168.2.0/24"),
            ("master_cidr", "10.20.1.0/28"),
            ("node_service_account", "default"),
            ("node_service_account", "123456-compute@developer.gserviceaccount.com"),
            ("writer_member", "allAuthenticatedUsers"),
            ("writer_member", "serviceAccount:" + plan.node_service_account),
            ("service_range", plan.pod_range),
        ]:
            with self.subTest(name=name, value=value), self.assertRaises(ValueError):
                replace(plan, **{name: value})

    def test_create_retry_partial_and_reuse(self):
        plan = example_plan()
        cloud = FakeCloud(plan)
        cloud.fail_on = "writer"
        with self.assertRaisesRegex(ValueError, "simulated"):
            provision(plan, cloud.run)
        self.assertNotIn("create_cluster", cloud.calls)
        cloud.fail_on = None
        cloud.calls.clear()
        provision(plan, cloud.run)
        self.assertEqual(cloud.mutations(), ["writer", "create_cluster"])
        cloud.calls.clear()
        provision(plan, cloud.run)
        self.assertEqual(cloud.mutations(), [])

    def test_foreign_names_and_private_profile_drift_stop_before_changes(self):
        plan = example_plan()
        for kind in ["repo", "cluster", "drift"]:
            with self.subTest(kind=kind):
                cloud = FakeCloud(plan)
                if kind == "repo":
                    cloud.replies["repos"] = [{"name": plan.registry}]
                    cloud.replies["repo"]["labels"]["protohub-owner"] = "another-team"
                else:
                    cloud.replies["clusters"] = [{"name": plan.cluster, "location": plan.zone}]
                    cluster = cloud.replies["cluster"]
                    if kind == "cluster":
                        cluster["resourceLabels"]["protohub-plan"] = "old-config"
                    else:
                        cluster["controlPlaneEndpointsConfig"]["ipEndpointsConfig"][
                            "enablePublicEndpoint"
                        ] = True
                with self.assertRaises(ValueError):
                    provision(plan, cloud.run)
                self.assertEqual(cloud.mutations(), [])

    def test_node_privacy_precedence_and_missing_setting(self):
        plan = example_plan()
        for node, default, legacy, safe in [
            (False, True, True, False),
            (None, False, True, False),
            (None, True, None, True),
            (None, None, True, True),
            (None, None, None, False),
        ]:
            with self.subTest(node=node, default=default, legacy=legacy):
                cloud = FakeCloud(plan)
                cloud.replies["clusters"] = [{"name": plan.cluster, "location": plan.zone}]
                cluster = cloud.replies["cluster"]
                pool = cluster["nodePools"][0]["networkConfig"]
                pool.clear()
                if node is not None:
                    pool["enablePrivateNodes"] = node
                if default is not None:
                    cluster["networkConfig"]["defaultEnablePrivateNodes"] = default
                if legacy is not None:
                    cluster["privateClusterConfig"]["enablePrivateNodes"] = legacy
                if safe:
                    provision(plan, cloud.run)
                else:
                    with self.assertRaises(ValueError):
                        provision(plan, cloud.run)
                    self.assertEqual(cloud.mutations(), [])

    def test_unverified_dns_and_ip_access_stop_before_iam_changes(self):
        plan = example_plan()
        for change in (
            "public_dns",
            "unknown_dns",
            "missing_dns",
            "unknown_public_ip",
            "wrong_node_account",
        ):
            with self.subTest(change=change):
                cloud = FakeCloud(plan)
                cloud.replies["clusters"] = [{"name": plan.cluster, "location": plan.zone}]
                cluster = cloud.replies["cluster"]
                endpoints = cluster["controlPlaneEndpointsConfig"]
                if change == "public_dns":
                    endpoints["dnsEndpointConfig"]["allowExternalTraffic"] = True
                elif change == "unknown_dns":
                    endpoints["dnsEndpointConfig"] = {}
                elif change == "missing_dns":
                    del endpoints["dnsEndpointConfig"]
                elif change == "unknown_public_ip":
                    del endpoints["ipEndpointsConfig"]["enablePublicEndpoint"]
                else:
                    cluster["nodePools"][0]["config"]["serviceAccount"] = "default"
                with self.assertRaises(ValueError):
                    provision(plan, cloud.run)
                self.assertEqual(cloud.mutations(), [])

    def test_invalid_project_state_stops_before_mutation(self):
        plan = example_plan()
        for key, values in [
            ("subnet", {"network": "other"}),
            ("subnet", {"privateIpGoogleAccess": False}),
            ("subnet", {"ipCidrRange": "172.16.0.0/16"}),
            ("subnet", {"secondaryIpRanges": []}),
            ("account", {"disabled": True}),
            ("roles", {"bindings": []}),
            (
                "roles",
                {
                    "bindings": [
                        {
                            "role": NODE_ROLE,
                            "members": ["serviceAccount:" + plan.node_service_account],
                        },
                        {
                            "role": "roles/editor",
                            "members": ["serviceAccount:" + plan.node_service_account],
                        },
                    ]
                },
            ),
        ]:
            with self.subTest(key=key, values=values):
                cloud = FakeCloud(plan)
                cloud.replies[key].update(values)
                with self.assertRaises(ValueError):
                    provision(plan, cloud.run)
                self.assertEqual(cloud.mutations(), [])

    def test_denied_list_does_not_trigger_creation_and_public_registry_is_rejected(self):
        plan = example_plan()
        cloud = FakeCloud(plan)
        cloud.fail_on = "repos"
        with self.assertRaises(ValueError):
            provision(plan, cloud.run)
        self.assertEqual(cloud.mutations(), [])
        cloud.fail_on = None
        cloud.replies["repos"] = [{"name": plan.registry}]
        cloud.replies["policy"]["bindings"].append({"role": READER, "members": ["allUsers"]})
        with self.assertRaises(ValueError):
            provision(plan, cloud.run)
        self.assertEqual(cloud.mutations(), [])
