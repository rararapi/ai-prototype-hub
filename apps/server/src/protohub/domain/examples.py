"""Public synthetic examples for the HTTP contract."""

SANDBOX = {
    "id": "00000000-0000-4000-8000-000000000001",
    "name": "Example app",
    "template_id": "hello-web",
    "desired_state": "stopped",
    "status": "stopped",
    "generation": 0,
    "active_operation_id": None,
    "preview_url": None,
    "expires_at": None,
    "error": None,
    "created_at": "2026-10-30T00:00:00Z",
    "updated_at": "2026-10-30T00:00:00Z",
}
OPERATION = {
    "id": "00000000-0000-4000-8000-000000000002",
    "sandbox_id": SANDBOX["id"],
    "action": "start",
    "generation": 1,
    "status": "queued",
    "attempt_count": 0,
    "created_at": SANDBOX["created_at"],
    "updated_at": SANDBOX["updated_at"],
    "error": None,
}
EXAMPLES = {
    "health": {"status": "ok"},
    "ready": {"status": "ok"},
    "system": {
        "runtime_mode": "mock",
        "auth_mode": "local-dev",
        "constraints": [
            "Trusted templates only",
            "Mock runtime does not start applications",
        ],
    },
    "templates": {
        "items": [
            {"id": "hello-web", "name": "Hello Web", "description": "Trusted local HTTP sample"}
        ]
    },
    "create_sandbox": SANDBOX,
    "get_sandbox": SANDBOX,
    "list_sandboxes": {"items": [SANDBOX]},
    "start_sandbox": OPERATION,
    "stop_sandbox": {**OPERATION, "action": "stop"},
    "delete_sandbox": {**OPERATION, "action": "delete"},
    "get_operation": OPERATION,
}
