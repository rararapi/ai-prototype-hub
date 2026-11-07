import hashlib
import io
import json
import os
import re
import shlex
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "infra/managed"))
import build_context as builder  # noqa: E402


class BuildContextTests(unittest.TestCase):
    def inputs(self, root=None):
        return builder.artifacts(
            root or builder.ROOT, "example-project", "asia-northeast1", "protohub"
        )

    def fixture(self, root):
        for src in (*builder.SOURCES, "infra/kubernetes/stack.yaml.in"):
            target = root / src
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes((builder.ROOT / src).read_bytes())

    def test_archive_exact_bytes_and_docker_copy_inputs(self):
        output = self.inputs()
        payload = output["application-source.tar.gz"]
        manifest = json.loads(output["source-manifest.json"])
        self.assertEqual(manifest["sha256"], hashlib.sha256(payload).hexdigest())
        self.assertEqual(manifest["tag"], "src-" + manifest["sha256"])
        with tarfile.open(fileobj=io.BytesIO(payload), mode="r:gz") as archive:
            paths = archive.getnames()
            self.assertEqual(paths, sorted((*builder.SOURCES, builder.POSTGRES_PIN)))
            for member in archive:
                self.assertTrue(member.isfile())
                self.assertEqual(
                    (member.mode, member.uid, member.gid, member.mtime), (0o644, 0, 0, 0)
                )
                data = archive.extractfile(member).read()
                self.assertEqual(hashlib.sha256(data).hexdigest(), manifest["files"][member.name])
                if member.name != builder.POSTGRES_PIN:
                    self.assertEqual(data, (builder.ROOT / member.name).read_bytes())
            for name in ("server", "web", "hello-web"):
                path = (
                    "examples/hello-web/Dockerfile"
                    if name == "hello-web"
                    else "infra/docker/" + name + ".Dockerfile"
                )
                for line in archive.extractfile(path).read().decode().splitlines():
                    args = shlex.split(line)
                    if not args or args[0] != "COPY" or args[1].startswith("--from="):
                        continue
                    for source in args[1:-1]:
                        self.assertTrue(
                            source in paths
                            or any(p.startswith(source.rstrip("/") + "/") for p in paths),
                            source,
                        )
            self.assertRegex(
                archive.extractfile(builder.POSTGRES_PIN).read().decode(),
                r"^postgres:.*@sha256:[0-9a-f]{64}\n$",
            )

    def test_frontend_imports_and_gemini_server_files_are_in_bounded_archive(self):
        sources = set(builder.SOURCES)
        expected = {
            "apps/server/src/protohub/api/ai.py",
            "apps/server/src/protohub/ai/gemini.py",
            "apps/server/src/protohub/persistence/ai.py",
            "apps/server/migrations/versions/0004_ai_applications.py",
            "apps/web/src/AiStudio.tsx",
            "apps/web/src/AppCanvas.tsx",
            "apps/web/src/AppBriefSummary.tsx",
        }
        self.assertTrue(expected <= sources)
        pattern = re.compile(r"""(?:from\s*|import\s*\(\s*|import\s+)["'](\.[^"']+)["']""")
        for source in sorted(sources):
            if not source.endswith((".ts", ".tsx")):
                continue
            path = builder.ROOT / source
            for relative in pattern.findall(path.read_text()):
                resolved = path.parent / relative
                options = (
                    [resolved]
                    if resolved.suffix
                    else [
                        resolved.with_suffix(suffix) for suffix in (".ts", ".tsx", ".css", ".json", ".d.ts")
                    ]
                )
                matches = [
                    str(candidate.resolve().relative_to(builder.ROOT))
                    for candidate in options
                    if candidate.is_file()
                ]
                self.assertTrue(
                    matches and any(name in sources for name in matches), (source, relative)
                )

    def test_recipes_build_and_publish_four_content_tagged_images(self):
        output = self.inputs()
        config = yaml.safe_load(output["cloudbuild.yaml"])
        tag = json.loads(output["source-manifest.json"])["tag"]
        prefix = "asia-northeast1-docker.pkg.dev/example-project/protohub/"
        self.assertEqual(
            config["images"],
            [prefix + n + ":" + tag for n in ["server", "web", "hello-web", "postgres"]],
        )
        self.assertEqual(config["timeout"], "900s")
        self.assertEqual(config["options"]["logging"], "CLOUD_LOGGING_ONLY")
        server, web, sample, mirror = config["steps"]
        for step in (server, web, sample):
            self.assertEqual(step["args"][:2], ["build", "--platform=linux/amd64"])
        self.assertEqual(server["args"][server["args"].index("--target") + 1], "runtime")
        self.assertNotIn("--target", web["args"])
        self.assertNotIn("--target", sample["args"])
        self.assertEqual(mirror["entrypoint"], "sh")
        self.assertIn("docker pull --platform=linux/amd64", mirror["args"][2])
        self.assertIn(builder.POSTGRES_PIN, mirror["args"][2])
        self.assertEqual(mirror["args"][-1], config["images"][-1])

    def test_unlisted_files_and_metadata_never_affect_context(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name).resolve()
            self.fixture(root)
            with patch("socket.socket.connect", side_effect=AssertionError("network access")):
                first = self.inputs(root)
                for subpath in (
                    ".env",
                    ".git/config",
                    "docs/proposal/private.md",
                    "apps/web/src/unrelated.tsx",
                    "apps/server/src/protohub/credentials.py",
                    "apps/web/public/private.pem",
                    "apps/web/node_modules/package/private.js",
                    "apps/server/.venv/bin/python",
                ):
                    file = root / subpath
                    file.parent.mkdir(exist_ok=True, parents=True)
                    file.write_text("not build input")
                os.utime(root / builder.SOURCES[0], (123, 123))
                self.assertEqual(first, self.inputs(root))
                source = root / "examples/hello-web/server.py"
                source.write_bytes(source.read_bytes() + b"\n")
                self.assertNotEqual(first, self.inputs(root))

    def test_changing_digest_changes_tag_and_unpinned_base_rejected(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name).resolve()
            self.fixture(root)
            original = self.inputs(root)
            path = root / "infra/kubernetes/stack.yaml.in"
            old = builder.postgres_image(root)
            path.write_text(path.read_text().replace(old, "postgres:new@sha256:" + "a" * 64))
            self.assertNotEqual(
                original["application-source.tar.gz"],
                self.inputs(root)["application-source.tar.gz"],
            )
            path.write_text(path.read_text().replace("@sha256:" + "a" * 64, ""))
            with self.assertRaises(ValueError):
                self.inputs(root)

    def test_refuse_source_symlinks_and_invalid_identifiers(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name).resolve()
            self.fixture(root)
            app = root / "apps/web/src/App.tsx"
            app.rename(app.with_suffix(".private"))
            app.symlink_to(app.with_suffix(".private"))
            with self.assertRaisesRegex(ValueError, "symlink"):
                self.inputs(root)
            app.unlink()
            app.with_suffix(".private").rename(app)
            directory = root / "apps/web/src"
            directory.rename(directory.with_name("extra"))
            directory.symlink_to(directory.with_name("extra"), target_is_directory=True)
            with self.assertRaisesRegex(ValueError, "symlink"):
                self.inputs(root)
        for project, region, repo in [
            ("-bad", "us-east1", "repo"),
            ("example-project", "bad;cmd", "repo"),
            ("example-project", "us-east1", "../escape"),
        ]:
            with (
                self.subTest(project=project, region=region, repo=repo),
                self.assertRaises(ValueError),
            ):
                builder.artifacts(builder.ROOT, project, region, repo)

    def test_publish_only_matching_sets_and_safe_destinations(self):
        with tempfile.TemporaryDirectory() as tmp:
            outer = Path(tmp).resolve()
            root = outer / "repo"
            root.mkdir()
            content = {"a": b"x", "b": b"y"}
            path = root / "worklogs" / "test"
            builder.write_artifacts(root, path, content)
            builder.write_artifacts(root, path, content)
            with self.assertRaises(ValueError):
                builder.write_artifacts(root, path, {"a": b"change"})
            self.assertEqual((path / "a").read_bytes(), b"x")
            private = outer / "private"
            private.mkdir(mode=0o700)
            builder.write_artifacts(root, private, content)
            symlink = root / "worklogs/link"
            symlink.symlink_to(private, target_is_directory=True)
            for bad in [root / "public", root / "worklogs", symlink, outer / "absent"]:
                with self.subTest(path=bad), self.assertRaises(ValueError):
                    builder.write_artifacts(root, bad, content)
            (path / "a").unlink()
            (path / "a").symlink_to(private / "a")
            with self.assertRaises(ValueError):
                builder.write_artifacts(root, path, content)
