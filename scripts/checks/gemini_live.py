"""Opt-in real Gemini probe from an owned API Pod; never runs in default CI."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MODULES = {
    "protohub.ai.gemini": "apps/server/src/protohub/ai/gemini.py",
    "protohub.api.ai": "apps/server/src/protohub/api/ai.py",
    "protohub.persistence.ai": "apps/server/src/protohub/persistence/ai.py",
    "protohub.domain.models": "apps/server/src/protohub/domain/models.py",
    "protohub.domain.settings": "apps/server/src/protohub/domain/settings.py",
}
PROBE = """
import hashlib, importlib.util, json, os
from protohub.ai.gemini import GeminiGenerator
from protohub.domain.models import AiBrief, AiConfig
from protohub.domain.settings import Settings
settings=Settings()
assert settings.ai_ready
assert not os.environ.get('GOOGLE_APPLICATION_CREDENTIALS')
modules=['protohub.ai.gemini','protohub.api.ai','protohub.persistence.ai','protohub.domain.models','protohub.domain.settings']
hashes={name:hashlib.sha256(open(importlib.util.find_spec(name).origin,'rb').read()).hexdigest() for name in modules}
plan=GeminiGenerator(settings).generate(
 AiBrief(purpose='接続確認の画面案',audience='検証担当者',success='設定されたGeminiが画面案を返す'),
 AiConfig(template='hello-web',title='接続確認',subtitle='架空の検証用画面',color='purple',trend=False,departments=False,cash_flow=False),
 '簡単な日本語の案内ページにしてください。外部接続や実データは不要です。')
assert plan.usage and plan.usage.input_tokens>0 and plan.usage.output_tokens>0
print(json.dumps({'status':'PASS','model':settings.ai_model,'usage':plan.usage.model_dump(),'module_hashes':hashes,'result_sha256':hashlib.sha256(plan.model_dump_json().encode()).hexdigest()}))
"""


class ProbeError(Exception):
    pass


def check(condition, message):
    if not condition:
        raise ProbeError(message)


def configuration(path):
    config = json.loads(Path(path).read_text())
    check(config.get("namespace") == "protohub-system", "Unexpected namespace")
    check(re.fullmatch(r"[a-z0-9][a-z0-9-]{0,62}", config.get("owner", "")), "Invalid owner")
    check(
        config.get("context")
        and not config["context"].startswith("-")
        and not any(c.isspace() for c in config["context"]),
        "Invalid context",
    )
    check(
        re.fullmatch(r"[^\s]+@sha256:[0-9a-f]{64}", config.get("server_image", "")),
        "Immutable image required",
    )
    check(re.fullmatch(r"gemini-[a-z0-9.-]{1,110}", config.get("model", "")), "Invalid model")
    check(re.fullmatch(r"[0-9a-f]{40}", config.get("source_head", "")), "Missing source commit")
    check(
        re.fullmatch(r"[0-9a-f]{64}", config.get("source_fingerprint", "")),
        "Missing source fingerprint",
    )
    output = Path(config["output"]).resolve()
    check(output.is_relative_to((ROOT / "worklogs").resolve()), "Evidence must remain in worklogs")
    check(
        Path(config["kubectl"]).is_file() and Path(config["kubeconfig"]).is_file(),
        "Missing explicit tooling or kubeconfig",
    )
    return config, output


def kubectl(config, args):
    env = dict(os.environ)
    if os.name == "nt" and config.get("windows_path"):
        env["PATH"] = config["windows_path"]
    env["CLOUDSDK_CORE_DISABLE_PROMPTS"] = "1"
    env["CLOUDSDK_CORE_LOG_HTTP"] = "false"
    command = [
        config["kubectl"],
        "--kubeconfig",
        config["kubeconfig"],
        "--context",
        config["context"],
        "--request-timeout=45s",
        *args,
    ]
    kwargs = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=65,
        cwd="C:\\Windows" if os.name == "nt" else ROOT,
        env=env,
        **kwargs,
    )
    check(
        result.returncode == 0, "Kubernetes probe command failed; no raw credentials/errors emitted"
    )
    return json.loads(result.stdout)


def inspect_pod(config, deployment, replicas, pods):
    metadata = deployment["metadata"]
    labels = metadata.get("labels", {})
    check(
        labels.get("protohub.io/owner") == config["owner"]
        and labels.get("app.kubernetes.io/managed-by") == "protohub",
        "Foreign API deployment",
    )
    template = deployment["spec"]["template"]["spec"]
    check(
        template.get("serviceAccountName") == "protohub-api"
        and template.get("automountServiceAccountToken") is False,
        "API identity/token boundary differs",
    )
    owned = {
        item["metadata"]["uid"]
        for item in replicas["items"]
        if any(
            ref.get("uid") == metadata["uid"] for ref in item["metadata"].get("ownerReferences", [])
        )
    }
    candidates = []
    for pod in pods["items"]:
        if pod["metadata"].get("deletionTimestamp") or not any(
            ref.get("uid") in owned for ref in pod["metadata"].get("ownerReferences", [])
        ):
            continue
        ready = any(
            c.get("type") == "Ready" and c.get("status") == "True"
            for c in pod.get("status", {}).get("conditions", [])
        )
        containers = [c for c in pod["spec"]["containers"] if c["name"] == "api"]
        statuses = [
            s for s in pod.get("status", {}).get("containerStatuses", []) if s["name"] == "api"
        ]
        if ready and len(containers) == len(statuses) == 1 and statuses[0].get("ready"):
            if containers[0]["image"] == config["server_image"] and statuses[0].get(
                "imageID", ""
            ).endswith(config["server_image"].split("@")[1]):
                candidates.append(pod)
    check(len(candidates) == 1, "Expected one current Ready API Pod on the immutable digest")
    pod = candidates[0]
    check(
        pod["spec"].get("serviceAccountName") == "protohub-api"
        and pod["spec"].get("automountServiceAccountToken") is False,
        "Actual Pod identity boundary differs",
    )
    return pod


def execute(config, output):
    selector = "app=protohub-api,app.kubernetes.io/managed-by=protohub"
    namespace = ["--namespace", config["namespace"]]
    deployment = kubectl(config, [*namespace, "get", "deployment/api", "-o", "json"])
    replicas = kubectl(config, [*namespace, "get", "replicasets", "-l", selector, "-o", "json"])
    pods = kubectl(config, [*namespace, "get", "pods", "-l", selector, "-o", "json"])
    pod = inspect_pod(config, deployment, replicas, pods)
    output.parent.mkdir(parents=True, exist_ok=True)
    attempt = output.with_suffix(".attempt.json")
    check(not attempt.exists(), "Paid probe already attempted; inspect before a new explicit run")
    attempt.write_text(
        json.dumps(
            {
                "started_at": datetime.now(timezone.utc).isoformat(),
                "pod_uid": pod["metadata"]["uid"],
                "source_head": config["source_head"],
            }
        )
        + "\n"
    )
    result = kubectl(
        config,
        [*namespace, "exec", pod["metadata"]["name"], "-c", "api", "--", "python", "-c", PROBE],
    )
    check(
        result.get("status") == "PASS" and result.get("model") == config["model"],
        "Real model result differs",
    )
    manifest = json.loads(Path(config["source_manifest"]).read_text())
    for module, path in MODULES.items():
        check(
            result.get("module_hashes", {}).get(module) == manifest["files"][path],
            "Deployed module differs from bounded build source",
        )
    result.update(
        {
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "source_head": config["source_head"],
            "source_fingerprint": config["source_fingerprint"],
            "server_image": config["server_image"],
            "pod_uid": pod["metadata"]["uid"],
            "service_account": "protohub-api",
            "automount_service_account_token": False,
            "mode": "real Vertex call from deployed API Pod; not browser/Google-login proof",
        }
    )
    output.write_text(json.dumps(result, indent=2) + "\n")
    print(
        "PASS actual deployed API Pod digest/source/WIF configuration and bounded real Gemini response"
    )
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--allow-paid-probe", action="store_true")
    parser.add_argument("--config")
    args = parser.parse_args()
    if not args.allow_paid_probe or not args.config:
        print("BLOCKED: explicit owned deployment config and paid-probe opt-in required")
        return 78
    try:
        config, output = configuration(args.config)
        execute(config, output)
    except (ProbeError, OSError, ValueError, KeyError, subprocess.TimeoutExpired):
        print(
            "FAIL Gemini live probe; inspect private evidence without credential output",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
