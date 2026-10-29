{
  "schema_version": 1,
  "groups": {
    "bootstrap": ["harness-self"],
    "quick": ["harness-self", "doctor-compose", "source", "contracts", "unit", "build", "public-hygiene"],
    "full": ["harness-self", "doctor-kind", "source", "contracts", "unit", "build", "public-hygiene", "integration", "e2e", "security"]
  },
  "gates": [
    {
      "id": "harness-self",
      "argv": ["python3", "-m", "unittest", "discover", "-s", "harness/tests", "-v"],
      "cwd": ".",
      "timeout_seconds": 90,
      "required_paths": ["harness/run.py", "harness/doctor.py", "harness/tests/test_harness.py"],
      "depends_on": []
    },
    {
      "id": "doctor-compose",
      "argv": ["python3", "harness/doctor.py", "--mode", "compose"],
      "cwd": ".",
      "timeout_seconds": 120,
      "required_paths": ["harness/doctor.py"],
      "depends_on": [],
      "blocked_exit_codes": [2]
    },
    {
      "id": "doctor-kind",
      "argv": ["python3", "harness/doctor.py", "--mode", "kind"],
      "cwd": ".",
      "timeout_seconds": 150,
      "required_paths": ["harness/doctor.py"],
      "depends_on": ["doctor-compose"],
      "blocked_exit_codes": [2]
    },
    {
      "id": "source",
      "argv": ["bash", "scripts/checks/source.sh"],
      "cwd": ".",
      "timeout_seconds": 900,
      "required_paths": ["scripts/checks/source.sh", "apps/server/pyproject.toml", "apps/web/package.json"],
      "depends_on": ["doctor-compose"],
      "blocked_exit_codes": [78]
    },
    {
      "id": "contracts",
      "argv": ["bash", "scripts/checks/contracts.sh"],
      "cwd": ".",
      "timeout_seconds": 600,
      "required_paths": ["scripts/checks/contracts.sh", "contracts/openapi.yaml"],
      "depends_on": ["doctor-compose"],
      "blocked_exit_codes": [78]
    },
    {
      "id": "unit",
      "argv": ["bash", "scripts/checks/unit.sh"],
      "cwd": ".",
      "timeout_seconds": 900,
      "required_paths": ["scripts/checks/unit.sh", "apps/server/tests", "apps/web/package.json"],
      "depends_on": ["doctor-compose"],
      "blocked_exit_codes": [78]
    },
    {
      "id": "build",
      "argv": ["bash", "scripts/checks/build.sh"],
      "cwd": ".",
      "timeout_seconds": 1800,
      "required_paths": ["scripts/checks/build.sh", "apps/server/pyproject.toml", "apps/web/package.json", "examples/hello-web/Dockerfile"],
      "depends_on": ["doctor-compose"],
      "blocked_exit_codes": [78]
    },
    {
      "id": "public-hygiene",
      "argv": ["bash", "scripts/checks/public-hygiene.sh"],
      "cwd": ".",
      "timeout_seconds": 600,
      "required_paths": ["scripts/checks/public-hygiene.sh"],
      "depends_on": [],
      "blocked_exit_codes": [78]
    },
    {
      "id": "integration",
      "argv": ["bash", "scripts/checks/integration.sh"],
      "cwd": ".",
      "timeout_seconds": 1200,
      "required_paths": ["scripts/checks/integration.sh", "tests/integration"],
      "depends_on": ["doctor-compose", "build"],
      "blocked_exit_codes": [78]
    },
    {
      "id": "e2e",
      "argv": ["bash", "scripts/checks/e2e.sh"],
      "cwd": ".",
      "timeout_seconds": 1800,
      "required_paths": ["scripts/checks/e2e.sh", "tests/e2e", "infra/kind"],
      "depends_on": ["doctor-kind", "build", "integration"],
      "blocked_exit_codes": [78]
    },
    {
      "id": "security",
      "argv": ["bash", "scripts/checks/security.sh"],
      "cwd": ".",
      "timeout_seconds": 1200,
      "required_paths": ["scripts/checks/security.sh", "infra/kubernetes"],
      "depends_on": ["doctor-kind", "build", "public-hygiene"],
      "blocked_exit_codes": [78]
    }
  ]
}
