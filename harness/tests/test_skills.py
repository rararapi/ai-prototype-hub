"""Skill provenance catches drift without fetching or executing upstream content."""

import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "project_skills", Path(__file__).resolve().parents[2] / "scripts/checks/skills.py"
)
skills = importlib.util.module_from_spec(spec)
spec.loader.exec_module(skills)


class SkillProvenanceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="protohub-skills-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.directory = self.root / ".agents/skills/example"
        self.directory.mkdir(parents=True)
        (self.root / "harness").mkdir()
        text = b'---\nname: "example"\ndescription: Test skill\n---\nUse the existing workflow.\n'
        (self.directory / "SKILL.md").write_bytes(text)
        (self.directory / "LICENSE.txt").write_bytes(b"Synthetic license fixture")
        self.data = {
            "schema_version": 1,
            "skills": [
                {
                    "name": "example",
                    "directory": ".agents/skills/example",
                    "source": {"kind": "github", "ref": "a" * 40},
                    "license": "Synthetic",
                    "license_evidence": [".agents/skills/example/LICENSE.txt"],
                    "files": {
                        p.relative_to(self.root).as_posix(): hashlib.sha256(
                            p.read_bytes()
                        ).hexdigest()
                        for p in self.directory.iterdir()
                    },
                }
            ],
        }

    def check(self):
        (self.root / "harness/skills.lock.json").write_text(json.dumps(self.data), encoding="utf-8")
        return skills.validate(self.root)

    def test_pinned_quoted_discovery_metadata_passes(self):
        self.assertEqual(self.check(), [])

    def test_changed_skill_cannot_reuse_old_lock(self):
        (self.directory / "SKILL.md").write_text("Unreviewed instructions", encoding="utf-8")
        self.assertTrue(any("Changed skill file" in value for value in self.check()))

    def test_extra_executable_is_rejected(self):
        (self.directory / "run.py").write_text("print('unreviewed')", encoding="utf-8")
        self.assertTrue(any("Unreviewed added" in value for value in self.check()))

    def test_mutable_main_and_missing_license_are_rejected(self):
        entry = self.data["skills"][0]
        entry["source"]["ref"] = "main"
        entry["license_evidence"] = []
        findings = self.check()
        self.assertTrue(any("Unpinned source" in value for value in findings))
        self.assertTrue(any("Missing license" in value for value in findings))

    def test_supporting_reference_must_also_be_pinned(self):
        self.data["skills"][0]["reference_source"] = {"ref": "main"}
        self.assertTrue(any("Unpinned supporting" in value for value in self.check()))


if __name__ == "__main__":
    unittest.main()
