"""Public synthetic examples for the HTTP contract."""

SANDBOX = {
    "id": "00000000-0000-4000-8000-000000000001",
    "name": "Example app",
    "owner_email": "owner@example.test",
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
    "login": {
        "token": "synthetic-session-token",
        "email": "owner@example.test",
        "expires_at": "2026-11-02T00:00:00Z",
    },
    "me": {"email": "owner@example.test"},
    "logout": {"status": "ok"},
    "get_shares": {"emails": ["reader@example.test"]},
    "set_shares": {"emails": ["reader@example.test"]},
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

EXAMPLES["google_login"] = EXAMPLES["login"]

AI_APPLICATION = {
    "id": "00000000-0000-4000-8000-000000000003",
    "brief": {
        "purpose": "月次会議で予実を確認する",
        "audience": "会議の参加者",
        "success": "部門ごとの差が分かるか確認する",
    },
    "config": {
        "template": "management-dashboard",
        "title": "月次レポート",
        "subtitle": "サンプルの予実を確認",
        "color": "blue",
        "trend": True,
        "departments": True,
        "cash_flow": False,
    },
    "summary": "予実と部門別の違いを確認する画面案です。",
    "model": "gemini-3.5-flash-lite",
    "status": "draft",
    "revision": 1,
    "usage": {"input_tokens": 100, "output_tokens": 120},
    "created_at": "2026-11-07T00:00:00Z",
    "updated_at": "2026-11-07T00:00:00Z",
}
EXAMPLES.update(
    {
        "ai_list": {"items": [AI_APPLICATION]},
        "ai_get": AI_APPLICATION,
        "ai_create": AI_APPLICATION,
        "ai_revise": {**AI_APPLICATION, "revision": 2},
        "ai_confirm": {**AI_APPLICATION, "status": "ready"},
        "ai_delete": {"status": "ok"},
    }
)
