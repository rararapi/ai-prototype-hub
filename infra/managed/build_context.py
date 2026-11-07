"""Prepare a bounded source archive and Cloud Build config locally."""

import argparse
import gzip
import hashlib
import io
import json
import os
import re
import tarfile
import tempfile
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
POSTGRES_PIN = "infra/managed/postgres-image.txt"
# Do not glob source trees: untracked scratch work and local config may be private.
REQUIRED = (
    ".dockerignore",
    "contracts/openapi.yaml",
    "infra/docker/nginx.conf",
    "infra/docker/server.Dockerfile",
    "infra/docker/web.Dockerfile",
    "examples/hello-web/Dockerfile",
    "examples/hello-web/server.py",
    "apps/server/pyproject.toml",
    "apps/server/uv.lock",
    "apps/server/alembic.ini",
    "apps/server/migrations/env.py",
    "apps/server/migrations/versions/0001_initial.py",
    "apps/server/migrations/versions/0002_local_users.py",
    "apps/server/migrations/versions/0003_google_accounts.py",
    "apps/server/migrations/versions/0004_ai_applications.py",
    "apps/web/package.json",
    "apps/web/package-lock.json",
    "apps/web/tsconfig.json",
    "apps/web/vite.config.ts",
    "apps/web/index.html",
)
SERVER = (
    "__init__.py",
    "accounts.py",
    "api/__init__.py",
    "api/google.py",
    "api/ai.py",
    "ai/__init__.py",
    "ai/gemini.py",
    "api/main.py",
    "domain/__init__.py",
    "domain/examples.py",
    "domain/http_contract.py",
    "domain/models.py",
    "domain/ports.py",
    "domain/settings.py",
    "persistence/__init__.py",
    "persistence/auth.py",
    "persistence/ai.py",
    "persistence/database.py",
    "persistence/jobs.py",
    "persistence/models.py",
    "persistence/repository.py",
    "preview/__init__.py",
    "preview/__main__.py",
    "runtime/__init__.py",
    "runtime/kubernetes.py",
    "runtime/mock.py",
    "worker/__init__.py",
    "worker/__main__.py",
)
WEB = (
    "App.tsx",
    "AiStudio.tsx",
    "AppCanvas.tsx",
    "AppBriefSummary.tsx",
    "ai-client.ts",
    "ai-studio.css",
    "app-brief.ts",
    "app-brief.css",
    "DemoBuilder.tsx",
    "DemoCreation.tsx",
    "DemoPreview.tsx",
    "DemoShareEditor.tsx",
    "GoogleLogin.tsx",
    "GooglePreview.tsx",
    "api.ts",
    "demo-builder.ts",
    "demo-mode.ts",
    "demo-sharing.ts",
    "demo-studio.css",
    "demo.ts",
    "generated/api.d.ts",
    "main.tsx",
    "styles.css",
)
SOURCES = (
    *REQUIRED,
    *(f"apps/server/src/protohub/{p}" for p in SERVER),
    *(f"apps/web/src/{p}" for p in WEB),
)


def read_source(root, name):
    path = root / name
    if path.resolve(strict=True) != path or not path.is_file():
        raise ValueError(f"expected a regular source file without symlinks: {name}")
    return path.read_bytes()


def postgres_image(root):
    documents = yaml.safe_load_all(read_source(root, "infra/kubernetes/stack.yaml.in"))
    images = [
        container.get("image")
        for doc in documents
        if doc["kind"] == "Deployment" and doc["metadata"]["name"] == "db"
        for container in doc["spec"]["template"]["spec"]["containers"]
        if container["name"] == "postgres"
    ]
    if len(images) != 1 or not re.fullmatch(
        r"(?:docker\.io/library/)?postgres(?::[a-zA-Z0-9_.-]+)?@sha256:[0-9a-f]{64}",
        images[0] or "",
    ):
        raise ValueError("the trusted PostgreSQL base must have a pinned official image digest")
    return images[0]


def pack(files):
    stream = io.BytesIO()
    with gzip.GzipFile(filename="", mode="wb", fileobj=stream, mtime=0) as compressed:
        with tarfile.open(fileobj=compressed, mode="w", format=tarfile.USTAR_FORMAT) as archive:
            for name, data in sorted(files.items()):
                entry = tarfile.TarInfo(name)
                entry.size = len(data)
                entry.mode = 0o644
                archive.addfile(entry, io.BytesIO(data))
    return stream.getvalue()


def docker_step(*args, entrypoint=None):
    step = {"name": "gcr.io/cloud-builders/docker", "args": list(args)}
    if entrypoint:
        step["entrypoint"] = entrypoint
    return step


def artifacts(root, project, region, repository):
    if not re.fullmatch(r"[a-z][a-z0-9-]{4,28}[a-z0-9]", project):
        raise ValueError("invalid Google Cloud project ID")
    if not re.fullmatch(r"[a-z]+(?:-[a-z]+)+[0-9]+", region):
        raise ValueError("invalid Google Cloud region")
    if not re.fullmatch(r"[a-z](?:[a-z0-9-]{0,61}[a-z0-9])?", repository):
        raise ValueError("invalid Artifact Registry repository name")
    files = {name: read_source(root, name) for name in SOURCES}
    # The mirror step reads this pin, so changing the upstream digest changes the source tag.
    files[POSTGRES_PIN] = (postgres_image(root) + "\n").encode()
    archive = pack(files)
    digest = hashlib.sha256(archive).hexdigest()
    tag = "src-" + digest
    prefix = f"{region}-docker.pkg.dev/{project}/{repository}"
    images = {name: f"{prefix}/{name}:{tag}" for name in ("server", "web", "hello-web", "postgres")}
    steps = []
    for name, path in (
        ("server", "infra/docker/server.Dockerfile"),
        ("web", "infra/docker/web.Dockerfile"),
        ("hello-web", "examples/hello-web/Dockerfile"),
    ):
        target = ["--target", "runtime"] if name == "server" else []
        steps.append(
            docker_step(
                "build", "--platform=linux/amd64", *target, "-f", path, "-t", images[name], "."
            )
        )
    # Cloud Build unescapes $$ before the shell evaluates the generated, validated pin.
    steps.append(
        docker_step(
            "-eu",
            "-c",
            f'base=$$(cat {POSTGRES_PIN}); docker pull --platform=linux/amd64 "$$base"; docker tag "$$base" "$$1"',
            "mirror",
            images["postgres"],
            entrypoint="sh",
        )
    )
    build = {
        "steps": steps,
        "images": list(images.values()),
        "timeout": "900s",
        "options": {"logging": "CLOUD_LOGGING_ONLY"},
    }
    manifest = {
        "sha256": digest,
        "tag": tag,
        "files": {name: hashlib.sha256(data).hexdigest() for name, data in sorted(files.items())},
    }
    return {
        "application-source.tar.gz": archive,
        "cloudbuild.yaml": yaml.safe_dump(build, sort_keys=False).encode(),
        "source-manifest.json": (json.dumps(manifest, indent=2) + "\n").encode(),
    }


def write_artifacts(root, directory, contents):
    target = directory.absolute()
    if ".." in target.parts or target.resolve() != target:
        raise ValueError("output path must be direct and must not use symlinks")
    ignored = root / "worklogs"
    if target == ignored:
        raise ValueError("use a dedicated output directory inside worklogs")
    if not target.is_relative_to(ignored):
        if target.is_relative_to(root) or not target.is_dir():
            raise ValueError(
                "choose a worklogs subdirectory or an existing private directory outside the repository"
            )
        access = target.stat()
        if access.st_uid != os.geteuid() or access.st_mode & 0o077:
            raise ValueError("external output directory must be owned by the caller and private")
    target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if target.exists():
        if not target.is_dir():
            raise ValueError("output must be a directory")
        existing = list(target.iterdir())
        if existing:
            if {p.name for p in existing} == set(contents) and all(
                not p.is_symlink() and p.is_file() and p.read_bytes() == contents[p.name]
                for p in existing
            ):
                return
            raise ValueError("output already contains different files; use a fresh directory")
    # Publish all three matching files together, with no partial output on failure.
    with tempfile.TemporaryDirectory(prefix=".build-context-", dir=target.parent) as temporary:
        stage = Path(temporary)
        for name, data in contents.items():
            (stage / name).write_bytes(data)
        stage.replace(target)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("project", "region", "repository", "output"):
        parser.add_argument("--" + name, required=True)
    args = parser.parse_args(argv)
    try:
        contents = artifacts(ROOT, args.project, args.region, args.repository)
        write_artifacts(ROOT, Path(args.output), contents)
    except (ValueError, OSError, yaml.YAMLError) as exc:
        parser.exit(1, f"Build context unavailable: {exc}\n")
    print(json.loads(contents["source-manifest.json"])["tag"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
