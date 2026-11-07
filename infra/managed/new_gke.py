"""Plan or provision ProtoHub's private, single-zone GKE Standard development cluster."""

import argparse
import hashlib
import ipaddress
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
from dataclasses import asdict, dataclass

NAME = r"[a-z](?:[a-z0-9-]*[a-z0-9])?"
PRIVATE = [ipaddress.IPv4Network(net) for net in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")]
RUN_APP_DNS = "protohub.gke.internal"
RUN_APP_HOSTS = {
    f"protohub-run-{role}.protohub-system.svc.{RUN_APP_DNS}" for role in ("web", "preview")
}
DNS_TRUST = (
    "The network owner must verify Cloud DNS response policies, forwarding servers, cross-project "
    "zone bindings and DNS record administration for the two Cloud Run backend names."
)
NODE_ROLE = "roles/container.defaultNodeServiceAccount"
READER = "roles/artifactregistry.reader"
WRITER = "roles/artifactregistry.writer"


@dataclass(frozen=True)
class Plan:
    project: str
    zone: str
    cluster: str
    network: str
    subnet: str
    pod_range: str
    service_range: str
    master_cidr: str
    admin_cidr: str
    node_service_account: str
    registry: str
    owner: str
    writer_member: str
    run_app_profile: bool = False

    def __post_init__(self):
        if not re.fullmatch(r"[a-z][a-z0-9-]{4,28}[a-z0-9]", self.project):
            raise ValueError("provide a Google Cloud project ID")
        if not re.fullmatch(r"[a-z]+(?:-[a-z]+)+[0-9]+-[a-z]", self.zone):
            raise ValueError("provide a zone such as us-central1-a")
        for field in (
            "network",
            "subnet",
            "pod_range",
            "service_range",
            "cluster",
            "registry",
            "owner",
        ):
            value = getattr(self, field)
            if not re.fullmatch(NAME, value) or len(value) > (40 if field == "cluster" else 63):
                raise ValueError(f"invalid {field}")
        if self.pod_range == self.service_range:
            raise ValueError("pod and service range names must differ")
        if not re.fullmatch(
            r"[a-z][a-z0-9-]{4,28}[a-z0-9]@"
            + re.escape(self.project)
            + r"\.iam\.gserviceaccount\.com",
            self.node_service_account,
        ):
            raise ValueError("require a named user-managed node service account in the project")
        if not re.fullmatch(
            r"(?:user|serviceAccount):[A-Za-z0-9._%+\-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}",
            self.writer_member,
        ):
            raise ValueError("require an individual publisher user:EMAIL or serviceAccount:EMAIL")
        if self.writer_member.partition(":")[2].lower() == self.node_service_account:
            raise ValueError("node account must differ from the publisher")
        master = ipaddress.IPv4Network(self.master_cidr)
        admin = ipaddress.IPv4Network(self.admin_cidr)
        if master.prefixlen != 28 or not any(master.subnet_of(net) for net in PRIVATE):
            raise ValueError("master CIDR must be a dedicated RFC1918 /28")
        if admin.prefixlen < 16 or not any(admin.subnet_of(net) for net in PRIVATE):
            raise ValueError("admin CIDR must be an RFC1918 range between /16 and /32")
        if master.overlaps(admin):
            raise ValueError("master and admin ranges overlap")

    @property
    def region(self):
        return self.zone.rsplit("-", 1)[0]

    @property
    def labels(self):
        fields = asdict(self)
        if not self.run_app_profile:
            del fields["run_app_profile"]  # Preserve the original Gateway plan identity.
        encoded = json.dumps(fields, sort_keys=True).encode()
        return {
            "managed-by": "protohub",
            "protohub-owner": self.owner,
            "protohub-plan": hashlib.sha256(b"protohub-private-gke-v1\n" + encoded).hexdigest()[
                :32
            ],
        }

    def commands(self):
        def cmd(*args):
            return ["gcloud", *args, "--project=" + self.project, "--quiet"]

        label = "--labels=" + ",".join(f"{k}={v}" for k, v in self.labels.items())
        region = "--region=" + self.region
        loc = "--location=" + self.region
        zone = "--zone=" + self.zone
        node = "serviceAccount:" + self.node_service_account
        if self.run_app_profile:
            profile = [
                "--machine-type=e2-medium",
                "--disk-size=30",
                "--gateway-api=disabled",
                "--cluster-dns=clouddns",
                "--cluster-dns-scope=cluster",
                "--additive-vpc-scope-dns-domain=" + RUN_APP_DNS,
                "--monitoring=SYSTEM",
                "--no-enable-managed-prometheus",
                "--addons=HttpLoadBalancing=DISABLED,HorizontalPodAutoscaling=DISABLED,"
                "GcpFilestoreCsiDriver=DISABLED,GcePersistentDiskCsiDriver=ENABLED",
            ]
        else:
            profile = [
                "--machine-type=e2-standard-2",
                "--disk-size=50",
                "--gateway-api=standard",
                "--addons=HttpLoadBalancing=ENABLED,HorizontalPodAutoscaling=ENABLED,GcePersistentDiskCsiDriver=ENABLED",
            ]
        commands = {
            "network": cmd(
                "compute", "networks", "describe", self.network, "--format=json(name,selfLink)"
            ),
            "subnet": cmd(
                "compute",
                "networks",
                "subnets",
                "describe",
                self.subnet,
                region,
                "--format=json(name,network,ipCidrRange,privateIpGoogleAccess,secondaryIpRanges)",
            ),
            "account": cmd(
                "iam",
                "service-accounts",
                "describe",
                self.node_service_account,
                "--format=json(email,disabled)",
            ),
            "roles": cmd("projects", "get-iam-policy", self.project, "--format=json(bindings)"),
            # Successful listing distinguishes absence from an auth/network error.
            "repos": cmd("artifacts", "repositories", "list", loc, "--format=json(name)"),
            "clusters": cmd("container", "clusters", "list", zone, "--format=json(name,location)"),
            "repo": cmd(
                "artifacts",
                "repositories",
                "describe",
                self.registry,
                loc,
                "--format=json(name,format,mode,labels)",
            ),
            "cluster": cmd(
                "container",
                "clusters",
                "describe",
                self.cluster,
                zone,
                "--format=json(id,name,location,status,currentNodeCount,resourceLabels,network,subnetwork,networkConfig,ipAllocationPolicy,workloadIdentityConfig,nodePools,autopilot,addonsConfig,monitoringConfig,privateClusterConfig,controlPlaneEndpointsConfig,masterAuthorizedNetworksConfig)",
            ),
            "create_repo": cmd(
                "artifacts",
                "repositories",
                "create",
                self.registry,
                loc,
                "--repository-format=docker",
                label,
            ),
            "policy": cmd(
                "artifacts",
                "repositories",
                "get-iam-policy",
                self.registry,
                loc,
                "--format=json(bindings)",
            ),
            "reader": cmd(
                "artifacts",
                "repositories",
                "add-iam-policy-binding",
                self.registry,
                loc,
                "--member=" + node,
                "--role=" + READER,
                "--condition=None",
            ),
            "writer": cmd(
                "artifacts",
                "repositories",
                "add-iam-policy-binding",
                self.registry,
                loc,
                "--member=" + self.writer_member,
                "--role=" + WRITER,
                "--condition=None",
            ),
            "create_cluster": cmd(
                "container",
                "clusters",
                "create",
                self.cluster,
                zone,
                label,
                "--release-channel=regular",
                "--num-nodes=1",
                *profile,
                "--disk-type=pd-balanced",
                "--network=" + self.network,
                "--subnetwork=" + self.subnet,
                "--enable-ip-alias",
                "--cluster-secondary-range-name=" + self.pod_range,
                "--services-secondary-range-name=" + self.service_range,
                "--enable-private-nodes",
                "--enable-private-endpoint",
                "--no-enable-dns-access",
                "--enable-master-authorized-networks",
                "--enable-authorized-networks-on-private-endpoint",
                "--master-authorized-networks=" + self.admin_cidr,
                "--master-ipv4-cidr=" + self.master_cidr,
                "--no-enable-google-cloud-access",
                "--enable-dataplane-v2",
                "--workload-pool=" + self.project + ".svc.id.goog",
                "--service-account=" + self.node_service_account,
                "--scopes=cloud-platform",
            ),
        }
        if self.run_app_profile:
            commands["dns_project"] = cmd(
                "projects", "describe", self.project, "--format=json(projectId,projectNumber)"
            )
            commands["dns_zones"] = cmd(
                "dns",
                "managed-zones",
                "list",
                "--filter=visibility=private",
                "--format=json(name,dnsName,description,labels,visibility,privateVisibilityConfig,forwardingConfig,peeringConfig,serviceDirectoryConfig,reverseLookupConfig)",
            )
        return commands


def require(condition, message):
    if not condition:
        raise ValueError(message)


def owned(plan, actual):
    require(
        all(actual.get(k) == v for k, v in plan.labels.items()),
        "ownership or plan fingerprint mismatch",
    )


def check_preconditions(plan, run, commands):
    network = run(commands["network"])
    subnet = run(commands["subnet"])
    require(
        network.get("name") == plan.network
        and network.get("selfLink")
        and subnet.get("network") == network["selfLink"]
        and subnet.get("name") == plan.subnet,
        "selected subnet does not belong to the selected VPC",
    )
    require(
        subnet.get("privateIpGoogleAccess"), "enable Private Google Access on the selected subnet"
    )
    ranges = {r["rangeName"]: r["ipCidrRange"] for r in subnet["secondaryIpRanges"]}
    require(
        plan.pod_range in ranges and plan.service_range in ranges,
        "missing named secondary IP ranges",
    )
    master = ipaddress.IPv4Network(plan.master_cidr)
    require(
        not any(
            master.overlaps(ipaddress.IPv4Network(cidr))
            for cidr in [subnet["ipCidrRange"], *ranges.values()]
        ),
        "control-plane range overlaps the subnet",
    )
    account = run(commands["account"])
    require(
        account.get("email") == plan.node_service_account and not account.get("disabled"),
        "node account unavailable",
    )
    bindings = run(commands["roles"]).get("bindings", [])
    direct = [
        b for b in bindings if "serviceAccount:" + plan.node_service_account in b.get("members", [])
    ]
    require(
        any(b["role"] == NODE_ROLE and not b.get("condition") for b in direct),
        "node account needs a direct unconditional roles/container.defaultNodeServiceAccount project binding",
    )
    require(
        all(b["role"] in {NODE_ROLE, READER} for b in direct),
        "unexpected project role on the dedicated node account",
    )


def check_repo(plan, repo):
    owned(plan, repo.get("labels", {}))
    require(
        repo.get("format") == "DOCKER" and repo.get("mode") == "STANDARD_REPOSITORY",
        "repository must be a standard Docker registry",
    )


def check_cluster(plan, cluster):
    owned(plan, cluster.get("resourceLabels", {}))
    require(
        cluster.get("status") == "RUNNING",
        "owned cluster is not RUNNING; inspect it and rerun later",
    )
    endpoints = cluster.get("controlPlaneEndpointsConfig", {})
    ips = endpoints.get("ipEndpointsConfig", {})
    private = cluster.get("privateClusterConfig", {})
    auth = ips.get("authorizedNetworksConfig", cluster.get("masterAuthorizedNetworksConfig", {}))
    network = cluster.get("networkConfig", {})
    ranges = cluster.get("ipAllocationPolicy", {})
    addons = cluster.get("addonsConfig", {})
    channel = network.get("gatewayApiConfig", {}).get("channel")
    pools = cluster.get("nodePools", [])
    require(len(pools) == 1, "expected one dedicated node pool")
    pool = pools[0]
    if plan.run_app_profile:
        config = pool.get("config", {})
        disk = config.get("bootDisk", {})
        dns = network.get("dnsConfig", {})
        monitoring = cluster.get("monitoringConfig", {})
        prometheus = monitoring.get("managedPrometheusConfig")
        filestore = addons.get("gcpFilestoreCsiDriverConfig")
        # GKE omits false scalar fields inside explicit disabled configurations.
        require(
            monitoring.get("componentConfig", {}).get("enableComponents") == ["SYSTEM_COMPONENTS"]
            and isinstance(prometheus, dict)
            and prometheus.get("enabled", False) is False
            and isinstance(filestore, dict)
            and filestore.get("enabled", False) is False
            and addons.get("horizontalPodAutoscaling", {}).get("disabled") is True,
            "owned cluster's optional add-ons do not match the single-node capacity profile",
        )
        require(
            config.get("machineType") == "e2-medium"
            and disk.get("diskType", config.get("diskType")) == "pd-balanced"
            and str(disk.get("sizeGb", config.get("diskSizeGb"))) == "30"
            and not config.get("preemptible")
            and not config.get("spot")
            and cluster.get("currentNodeCount") == 1
            and not pool.get("autoscaling", {}).get("enabled")
            and dns.get("clusterDns") == "CLOUD_DNS"
            and dns.get("clusterDnsScope") == "CLUSTER_SCOPE"
            and dns.get("additiveVpcScopeDnsDomain") == RUN_APP_DNS
            and channel == "CHANNEL_DISABLED"
            and addons.get("httpLoadBalancing", {}).get("disabled") is True
            and addons.get("gcePersistentDiskCsiDriverConfig", {}).get("enabled") is True,
            "owned cluster's sizing, Cloud DNS, or add-ons do not match the run.app profile",
        )
    else:
        require(
            channel == "CHANNEL_STANDARD"
            and not addons.get("httpLoadBalancing", {}).get("disabled"),
            "expected Gateway API and HTTP load balancing for the Gateway profile",
        )
    # Optional fields distinguish inherited values from an explicit public override.
    private_nodes = pool.get("networkConfig", {}).get(
        "enablePrivateNodes",
        network.get("defaultEnablePrivateNodes", private.get("enablePrivateNodes")),
    )
    private_endpoint = (
        ips.get("enabled") is True
        and bool(ips.get("privateEndpoint"))
        and ips.get("enablePublicEndpoint") is False
        and not ips.get("publicEndpoint")
        if "ipEndpointsConfig" in endpoints
        else private.get("enablePrivateEndpoint") is True
    )
    require(
        cluster.get("location") == plan.zone
        and not cluster.get("autopilot", {}).get("enabled")
        and cluster.get("network", "").rsplit("/", 1)[-1] == plan.network
        and cluster.get("subnetwork", "").rsplit("/", 1)[-1] == plan.subnet
        and network.get("datapathProvider") == "ADVANCED_DATAPATH"
        and cluster.get("workloadIdentityConfig", {}).get("workloadPool")
        == plan.project + ".svc.id.goog"
        and ranges.get("clusterSecondaryRangeName") == plan.pod_range
        and ranges.get("servicesSecondaryRangeName") == plan.service_range
        and pool.get("config", {}).get("serviceAccount") == plan.node_service_account
        and private_nodes is True
        and private.get("masterIpv4CidrBlock") == plan.master_cidr
        and private_endpoint
        and endpoints.get("dnsEndpointConfig", {}).get("allowExternalTraffic") is False
        and auth.get("enabled")
        and auth.get("privateEndpointEnforcementEnabled")
        and not auth.get("gcpPublicCidrsAccessEnabled")
        and {block.get("cidrBlock") for block in auth.get("cidrBlocks", [])} == {plan.admin_cidr},
        "owned cluster's live settings do not match the private profile",
    )


def check_backend_zones(plan, project, zones, cluster):
    require(
        project.get("projectId") == plan.project
        and str(project.get("projectNumber", "")).isdigit(),
        "unable to identify the selected project for DNS verification",
    )
    project_ids = {plan.project, str(project["projectNumber"])}
    found_base = False
    for zone in zones:
        domain = zone.get("dnsName", "").rstrip(".").lower()
        if not (domain == RUN_APP_DNS or domain.endswith("." + RUN_APP_DNS)):
            continue
        if not any(host == domain or host.endswith("." + domain) for host in RUN_APP_HOSTS):
            continue
        require(zone.get("visibility") == "private", "cannot confirm private DNS visibility")
        scope = zone.get("privateVisibilityConfig") or {}
        networks = scope.get("networks") or []
        require(
            networks or scope.get("gkeClusters"), "cannot verify DNS domain network attachments"
        )
        selected = False
        for entry in networks:
            link = re.fullmatch(
                r"(?:(?:https://(?:www\.googleapis\.com|compute\.googleapis\.com)/compute/(?:v1|beta)/)|//compute\.googleapis\.com/)?"
                r"projects/([^/]+)/global/networks/([^/]+)",
                entry.get("networkUrl", ""),
            )
            require(link, "cannot identify DNS zone network")
            if link.group(1) in project_ids and link.group(2) == plan.network:
                selected = True
        if not selected:
            continue
        require(
            domain == RUN_APP_DNS and cluster is not None,
            "a private DNS domain in the selected VPC overrides the Cloud Run backend name",
        )
        cluster_id = cluster.get("id", "")
        require(
            re.fullmatch(r"[0-9a-f]{8}[0-9a-f-]*", cluster_id),
            "cannot verify GKE cluster identifier",
        )
        # GKE shortens the cluster hash in additive VPC zone names. The managed label
        # and scope description corroborate the name in addition to the VPC attachment.
        expected = f"gke-{plan.cluster}-{cluster_id[:4]}-dns-vpc"
        description = (
            f'Private zone for GKE cluster "{plan.cluster}" with cluster suffix "{RUN_APP_DNS}." '
            f'in project "{plan.project}" with scope "VPC_SCOPE"'
        )
        require(
            not found_base
            and zone.get("name") == expected
            and zone.get("description") == description
            and (zone.get("labels") or {}).get("goog-gke-node") == ""
            and len(networks) == 1
            and not any(
                field in zone
                for field in (
                    "forwardingConfig",
                    "peeringConfig",
                    "serviceDirectoryConfig",
                    "reverseLookupConfig",
                )
            ),
            "ambiguous additive DNS base zone; verify GKE cluster ownership",
        )
        found_base = True
    if cluster is not None:
        require(found_base, "GKE-created additive zone not verified; inspect Cloud DNS and retry")


def provision(plan, run):
    cmds = plan.commands()
    check_preconditions(plan, run, cmds)
    repo_exists = any(r["name"].rsplit("/", 1)[-1] == plan.registry for r in run(cmds["repos"]))
    cluster_exists = any(
        c["name"] == plan.cluster and c["location"] == plan.zone for c in run(cmds["clusters"])
    )
    if repo_exists:
        check_repo(plan, run(cmds["repo"]))
    cluster = None
    if cluster_exists:
        cluster = run(cmds["cluster"])
        check_cluster(plan, cluster)
    dns_project = None
    if plan.run_app_profile:
        dns_project = run(cmds["dns_project"])
        check_backend_zones(plan, dns_project, run(cmds["dns_zones"]), cluster)
    if not repo_exists:
        run(cmds["create_repo"])
        check_repo(plan, run(cmds["repo"]))
    bindings = run(cmds["policy"]).get("bindings", [])
    require(
        not any(
            {"allUsers", "allAuthenticatedUsers"}.intersection(b.get("members", []))
            for b in bindings
        ),
        "public repository IAM binding; refusing to continue",
    )
    for name, role, member in (
        ("reader", READER, "serviceAccount:" + plan.node_service_account),
        ("writer", WRITER, plan.writer_member),
    ):
        if not any(
            b["role"] == role and not b.get("condition") and member in b.get("members", [])
            for b in bindings
        ):
            run(cmds[name])
    if not cluster_exists:
        run(cmds["create_cluster"])
        cluster = run(cmds["cluster"])
        check_cluster(plan, cluster)
        if plan.run_app_profile:
            check_backend_zones(plan, dns_project, run(cmds["dns_zones"]), cluster)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, epilog=DNS_TRUST)
    parser.add_argument(
        "--run-app-profile",
        action="store_true",
        help="Plan a single e2-medium node for Cloud Run ingress",
    )
    for field in Plan.__dataclass_fields__:
        if field == "run_app_profile":
            continue
        parser.add_argument("--" + field.replace("_", "-"), required=True)
    parser.add_argument(
        "--create", action="store_true", help="Perform the approved, billable provisioning"
    )
    args = vars(parser.parse_args(argv))
    create = args.pop("create")
    try:
        plan = Plan(**args)
        if plan.run_app_profile:
            print("# " + DNS_TRUST)
        if not create:
            for key, command in plan.commands().items():
                print(f"# {key}\n{shlex.join(command)}")
            return 0
        with tempfile.TemporaryDirectory(prefix="protohub-gke-") as tempdir:
            env = {
                **os.environ,
                "KUBECONFIG": os.path.join(tempdir, "config"),
                "CLOUDSDK_CORE_DISABLE_PROMPTS": "1",
            }

            def run(command):
                query = any(arg.startswith("--format=json") for arg in command)
                result = subprocess.run(
                    [shutil.which(command[0]) or command[0], *command[1:]],
                    env=env,
                    text=True,
                    stdout=subprocess.PIPE if query else subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=1800 if command[1:4] == ["container", "clusters", "create"] else 120,
                )
                require(
                    result.returncode == 0,
                    f"gcloud {' '.join(command[1:4])} failed; inspect the selected project and retry",
                )
                return json.loads(result.stdout) if query else None

            provision(plan, run)
    except (ValueError, KeyError, OSError, subprocess.TimeoutExpired) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print("Private GKE cluster and dedicated Docker registry verified.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
