#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/../.."
python=python3
if ! "$python" -c 'import yaml' 2>/dev/null; then
  python="${UV_PROJECT_ENVIRONMENT:-apps/server/.venv}/bin/python"
  if ! "$python" -c 'import yaml' 2>/dev/null; then
    echo 'BLOCKED: Python 3.10+ with PyYAML is required (available in the locked server environment)' >&2
    exit 78
  fi
fi
"$python" - <<'PY'
import sys
import unittest

suite = unittest.defaultTestLoader.discover("tests/managed")
result = unittest.TextTestRunner(verbosity=2).run(suite)
sys.exit(0 if result.testsRun and result.wasSuccessful() and not result.skipped else 1)
PY
