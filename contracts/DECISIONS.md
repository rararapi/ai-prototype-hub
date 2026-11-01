# Phase 0 contract decisions

- API truth: `openapi.yaml` (OpenAPI 3.1, JSON-compatible YAML). Snake case, UUID, UTC.
- Header on mutations: `X-ProtoHub-Client: console`, including DELETE; send JSON `{}` for actions.
  If Origin is present it must equal configured console origin. Host is an exact allowlist.
- Same desired action returns its active operation, including a succeeded no-op. Failed actions
  may be retried with a new generation. Delete is idempotent, including tombstones. Start/stop
  after deletion return 409. List excludes tombstones; detail retains tombstones for polling.
- New intent locks the Sandbox row and atomically increments generation, supersedes old jobs,
  clears preview/expiry/error, creates a queued Operation, and updates desired/status.
- A JobStore call is one short transaction. No runtime I/O inside that transaction. Worker
  creates `SqlJobStore(session_factory, settings)` from persistence/jobs.py. API factory is
  `protohub.api.main:create_app`; ASGI `app` is also exported. Shared engine/session factory
  is `protohub.persistence.database:create_session_factory(database_url)`.
- Claim uses SKIP LOCKED on PostgreSQL, rotates random lease_token on every claim/reclaim,
  increments attempt_count, and sets lease expiry using DB/store UTC time. Expired running
  work is reclaimable. Maximum 3 claims; retry uses bounded exponential delay (2, 4 seconds).
- heartbeat/complete/fail/supersede return false without writes unless operation is running,
  token AND owner match, lease is unexpired, generation and desired action still match.
  They lock/check Sandbox and Operation atomically in consistent order. Same generation
  with old token MUST fail. Worker checks is_current before each subsequent provider call.
- complete accepts observed running/stopped/deleted only, matching the action; observed start
  must be ready AND reachable in real mode. TTL is set at first successful start, not claim.
- fail(retryable=True) releases lease into queued with backoff if attempt_count < 3; otherwise
  persists failed + safe error. Nonretryable failure is final. Failed desired-running work is
  cleaned by reconcile, not automatically relaunched. Fresh explicit start can retry it.
- enqueue_expired creates idempotent stop intents under the same Sandbox lock. Reconcile
  includes stopped/deleted/failed targets (even tombstones) and active running targets.
  Reconcile rechecks current desired state before side effects. Stable resource name is
  `sandbox-<uuid hex>`, namespace `protohub-samples`, control namespace `protohub-system`.
- Provider calls are bounded and idempotent. Kubernetes writes must reject lower generation
  if existing resource has a higher generation label. Reconcile cleans delayed old side effects.
- Worker command `python -m protohub.worker`; preview `python -m protohub.preview` (8081).
  API container has no SA token; worker uses in-cluster config. Preview uses DB + fixed DNS,
  no Kubernetes management credentials, no arbitrary upstream.
- Local scripts: `bash scripts/local/{up-mock,up-real,down,logs,reset-local}.sh`.
  `PROTOHUB_MODE=mock|real-kind`, `PROTOHUB_CLUSTER_NAME`, `COMPOSE_PROJECT_NAME`,
  `PROTOHUB_CONSOLE_PORT=8080`, `PROTOHUB_PREVIEW_PORT=8081`. Preflight shortage = exit 78;
  real test failure = exit 1. down preserves volume/cluster; reset needs explicit opt-in.
- QA scripts: source/contracts/unit/build/public-hygiene/integration/e2e/security.sh.
  Root make targets follow HARNESS_SPEC; mandatory verify means full, never mock fallback.

API/DB owns persistence + migrations + HTTP. Runtime owns worker/providers/preview/infra.
Frontend owns its files; parent installs dependencies and locks in this shared checkout.
QA owns runners/checks/E2E/CI. Parent owns DTO/settings/Python deps/contracts and final docs.

## Coordinated addition after baseline

`JobStore.reconcile_observation(spec, observation) -> bool` records periodic real observations
when generation still matches, desired is running, status is running/starting, and no operation
is queued/running. Unhealthy observations clear preview immediately; stopped maps to starting.
Existing expires_at is preserved so periodic observation cannot extend TTL. Failed targets are
cleaned rather than relaunched. Backend and Runtime were notified together before implementing.

HTTP 500 uses the same sanitized HttpError envelope. Generic exception text is never returned.

Independent review addition: RuntimeSpec has an ephemeral `may_mutate` callback (excluded from
comparison and persistence). Worker binds it to the current lease/generation for claimed jobs;
providers check immediately before each mutation, including between Service and Deployment.
Reconcile binds it to fresh current intent. A lost fence stops subsequent writes; in-flight
network requests remain at-least-once and converge through generation checks and reconcile.

QA fixture launches set `PROTOHUB_NO_ACTIVATE=1` so E2E/security never replace the developer's
active local stack selection. Their cluster, ports, receipts and cleanup remain independent.



## 2026-11-01: development email sessions and app visibility

User authorizes development email login, filtered owned/shared apps, shared LLM configuration
and PR creation. Auth routes login/me/logout use opaque24h bearer sessions, never cookies.
All management data routes require a current principal; list/detail/operation access is
owner-or-explicit-recipient, lifecycle/share writes owner-only, inaccessible IDs404.
GET/PUT shares has normalized maximum100 email recipients, owner-only replacement semantics.
Sandbox adds owner_email; nullable legacy rows are preserved and hidden, never auto-adopted.
Production disables this impersonation login and protected management APIs. Existing localhost,
JSON/custom header, exact Origin and host boundaries remain. Preview stays a trusted fixed
sample endpoint without private data authorization; no bearer/Cookie forwarding is introduced.
Server-only shared LLM key is configured/resolved for every app with no app-specific overrides
and no external LLM calls. OpenAPI, generated frontend types, examples and tests change together.
