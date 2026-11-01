# Backend handoff

## Changed files / commit

Shared checkout `C:\Git\ai-prototype-hub`, base contract commit
`96256a5d096109d253bd83ff1e990242f83a454d`; no agent Git operations or commits.

- `apps/server/src/protohub/api/{__init__,main}.py`
- `apps/server/src/protohub/persistence/{__init__,database,models,repository,jobs}.py`
- `apps/server/alembic.ini`, `apps/server/migrations/env.py`, `versions/0001_initial.py`
- `apps/server/tests/api/{conftest,test_api,test_jobs,test_migrations,test_postgres}.py`
- This handoff. No shared dependency or domain files edited.

## Implemented behavior

- Persisted Sandbox and Operation queue; UTC timestamps, generation uniqueness, bounded
  retry count, limited audit events. Alembic creates the schema; app startup never creates it.
- Full frozen API, sanitized 400/403/404/409/422/500/503 errors and generated request IDs.
  Exact Host/Origin, JSON and custom client header checks. Fixed template and strict fields.
- Atomic intent plus job transaction; duplicate actions return active/succeeded operations.
  New stop/delete supersedes earlier jobs. Tombstones remain queryable and deletion is idempotent.
- PostgreSQL SKIP LOCKED claims; Sandbox then Operation lock ordering in all writers.
  Eligibility is rechecked after locking to reject a just-renewed lease from an older snapshot.
- Owner/token/expiry/generation/desired-state fencing on heartbeat, completion, failure,
  supersede and is_current. Expired leases are reclaimed with a new token, maximum 3 attempts;
  retries wait 2 then 4 seconds. Exhausted crashed leases become failed.
- TTL begins on successful start and atomically enqueues stop, preserving management data.
  Observation never renews TTL. Reconcile clears stale preview on unhealthy observations,
  rejects stale generations/active jobs, retains terminal-starting targets for later recovery,
  and makes failed targets available for cleanup without automatic relaunch.
- Mock completion forces preview URL null. Real completion requires a provider URL;
  the runtime provider is responsible for readiness plus HTTP proof before reporting running.

## Tests actually run

| Command | Result | Evidence |
|---|---|---|
| `apps/server/.venv/Scripts/python.exe -m pytest apps/server/tests/api -m "not postgres" -q --junitxml=.harness/reports/backend-unit/junit.xml` | PASS: 48 passed, 4 deselected | Ignored local JUnit at that exact path |
| `apps/server/.venv/Scripts/ruff.exe check apps/server/src/protohub/api apps/server/src/protohub/persistence apps/server/migrations apps/server/tests/api` | PASS | Actual local tool run |
| `apps/server/.venv/Scripts/ruff.exe format --check` on the same owned paths | PASS: 14 files already formatted | Actual local tool run |
| `apps/server/.venv/Scripts/mypy.exe apps/server/src/protohub/api apps/server/src/protohub/persistence --config-file apps/server/pyproject.toml` | PASS: 7 source files | Actual local tool run |
| `apps/server/.venv/Scripts/python.exe contracts/check.py` | PASS: validation + exact schema equality | Actual local tool run |

Tests include input/security errors, registration and async lifecycle, duplicate intent,
transaction rollback after injected audit insertion failure, old generation/owner/token
rejection, same-generation lease reclaim, bounded retry/lease exhaustion, first-success TTL,
two-app independence, deletion tombstones, restart persistence and Alembic reentrancy.

Native Windows TestClient initially hung while creating Python's internal asyncio socketpair
under the sandbox. Those two own sessions were stopped. The successful runs above used a
reviewed sandbox escalation for localhost test sockets only; no OS configuration was changed.

## Contract/dependency changes requested

- Parent approved and owns `JobStore.reconcile_observation(spec, observation) -> bool`.
- Parent owns production allowed_hosts removal of testserver and HTTP500 response metadata.
- Shared uv.lock used unchanged. Starlette emits an httpx TestClient deprecation warning;
  current tests pass; no unrequested dependency added.

## Known issues and BLOCKED checks

- Actual PostgreSQL execution is BLOCKED by unavailable local Docker/WSL integration. Four
  mandatory `postgres`-marked tests are implemented, never skipped when explicitly selected.
  Select them with `-m postgres` and `PROTOHUB_TEST_DATABASE_URL` pointing at an owned local
  PostgreSQL test DB. They create/migrate/drop one generated schema only, preserving other data.
- Those tests cover 8 concurrent duplicate requests, locked-row SKIP LOCKED behavior,
  old lease completion rejection after same-generation reclaim, new stop beating delayed start,
  TTL and persisted records. SQLite results do not prove PostgreSQL locking.
- No real runtime or browser acceptance was claimed by this role.

## Integration notes

- `protohub.api.main:create_app(settings=None, session_factory=None)` and ASGI `app` exported.
- `create_session_factory(url)` returns `sessionmaker[Session]`; PostgreSQL connect/pool timeout 5s.
- `SandboxRepository(factory, settings)` exposes create/list/get/request/get_operation;
  get returns the frozen Sandbox DTO and raises `NotFound` for absent IDs.
- `SqlJobStore(factory, settings)` implements the frozen protocol plus approved observation method.
- Run `alembic -c apps/server/alembic.ini upgrade head` from repo root, or `alembic upgrade head`
  with cwd apps/server. `PROTOHUB_DATABASE_URL` overrides the migration target.
- Internal API probes/proxies must send `Host: localhost`. Mutations need JSON `{}` even DELETE.
- Unit selection must use `-m "not postgres"`; integration selects `-m postgres`. A missing real
  DB should be detected by the harness preflight, never converted into an empty passing suite.


保存先の補足（2026-11-02）: 現在の作業記録・所有記録は `worklogs/` に保存する。
上記の実行証跡パスは当時の表記であり、移行後は先頭の `.harness/` を読み替える。
