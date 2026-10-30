"""Execute real migration and non-skippable PostgreSQL regression suite."""

import os
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

root = Path(__file__).resolve().parents[2]
assert os.environ["PROTOHUB_TEST_DATABASE_URL"].startswith("postgresql+psycopg://")
for command in (
    ["alembic", "-c", "apps/server/alembic.ini", "upgrade", "head"],
    [
        sys.executable,
        "-m",
        "pytest",
        "apps/server/tests/api",
        "-m",
        "postgres",
        "--junitxml=/evidence/postgres.xml",
    ],
):
    result = subprocess.run(command, cwd=root, check=False)
    if result.returncode:
        raise SystemExit(1)
cases = list(ET.parse("/evidence/postgres.xml").iter("testcase"))
assert cases and not any(case.find("skipped") is not None for case in cases)
print(f"PASS real PostgreSQL: {len(cases)} tests, no skips")
