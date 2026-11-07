#!/usr/bin/env bash
# Offline Google protocol fixture, account lifecycle, API schema and browser components.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/../.."
python="${UV_PROJECT_ENVIRONMENT:-$PWD/apps/server/.venv}/bin/python"
if [[ ! -x "$python" || ! -x apps/web/node_modules/.bin/vitest ]] || ! command -v npm >/dev/null; then
  echo "BLOCKED: install the locked server and web test dependencies first" >&2
  exit 78
fi
evidence="${PROTOHUB_HARNESS_REPORT_DIR:-$PWD/worklogs}/google-login"
mkdir -p "$evidence"
"$python" -m pytest -q -o "cache_dir=$evidence/pytest-cache" \
  apps/server/tests/api/test_google_login.py apps/server/tests/api/test_google_accounts.py \
  apps/server/tests/api/test_identity.py apps/server/tests/api/test_migrations.py \
  apps/server/tests/runtime/test_google_preview.py --junitxml="$evidence/server.xml"
"$python" contracts/check.py
npm --prefix apps/web run check:api
npm --prefix apps/web run test:unit -- --no-file-parallelism src/google-auth.test.tsx \
  --reporter=default --reporter=junit "--outputFile=$evidence/web.xml"
"$python" - "$evidence" <<'PY'
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

for name in ("server.xml", "web.xml"):
    cases = list(ET.parse(Path(sys.argv[1]) / name).iter("testcase"))
    if not cases or any(case.find(tag) is not None for case in cases for tag in ("skipped", "error", "failure")):
        raise SystemExit(f"Empty, skipped or unsuccessful suite: {name}")
    print(f"PASS {name}: {len(cases)} tests")
PY
