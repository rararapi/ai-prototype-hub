"""Compare generated API schema with the reviewed canonical contract."""

import difflib
import json
from pathlib import Path

import yaml
from openapi_spec_validator import validate
from protohub.api.main import create_app

root = Path(__file__).resolve().parent
expected = yaml.safe_load((root / "openapi.yaml").read_text(encoding="utf-8"))
validate(expected)
actual = create_app().openapi()
if actual != expected:
    before = json.dumps(expected, indent=2, sort_keys=True).splitlines()
    after = json.dumps(actual, indent=2, sort_keys=True).splitlines()
    print("\n".join(difflib.unified_diff(before, after, "canonical", "implementation")))
    raise SystemExit(1)
print("PASS OpenAPI validation and implementation drift check")
