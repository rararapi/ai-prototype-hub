# Runtime / Infra handoff

## Changed files / commit

Shared checkout at baseline `96256a5d096109d253bd83ff1e990242f83a454d`; no agent Git operations.
Parent owns final commits. Owned changes:

- `apps/server/src/protohub/{worker,runtime,preview}/**`
- `apps/server/tests/{worker,runtime}/**`
- `infra/{docker,kind,kubernetes}/**`, `compose.yaml`, `examples/hello-web/**`
- `scripts/local/{manage.py,up-mock.sh,up-real.sh,down.sh,logs.sh,reset-local.sh}`

## Implemented behavior

- Bounded worker actions with concurrent lease heartbeat, checks before subsequent provider
  calls/completion, safe retry classification, TTL enqueue, interrupted lease recovery through
  the SQL store, and desired-state/generation-aware reconcile. Failed targets remove owned
  partial resources. Observed drift clears preview and recovers without extending TTL.
- Explicit mock produces no preview URL. Kubernetes adapter loads only in-cluster config,
  uses UUID names/owner labels, resourceVersion patches and deletion preconditions, refuses
  foreign resources/higher generations, requires a complete rollout and current-generation
  Ready Pod plus real Service health HTTP, and
  waits Pod absence after stop/delete. Stop retains a scaled-zero Deployment/Service;
  delete removes resources. Reconcile cleans delayed old side effects eventually.
- Fixed sample has a health JSON and an interactive browser-local counter; no external API.
- Preview selects a fixed Service from DB UUID only. GET/HEAD, exact Host allowlist,
  no arbitrary query/upstream, encoded-path/traversal rejection, no Cookie/Authorization/
  forwarded header transfer, redirects rejected, response body bound, no upstream Set-Cookie.
- Mock Compose and full in-kind API/worker/DB/web/preview. Only worker has a mounted
  ServiceAccount token, and its Role is restricted to sample Deployment/Service operations
  and Pod reads. Sample is nonroot, read-only, drops capabilities, no SA token, bounded resources.
- Launcher verifies a local Docker endpoint through doctor, refuses native Windows and `/mnt`
  source launch, localhost-only mappings, exact context and tracked ownership. Daily down
  retains the DB volume/kind cluster; explicit reset checks exact-name confirmation and ownership.

## Tests actually run

| command | result | evidence |
|---|---|---|
| `.venv/Scripts/python.exe -m pytest apps/server/tests/worker apps/server/tests/runtime -q --junitxml=.harness/runtime/unit.xml` | PASS: 31 tests | `.harness/runtime/unit.xml` |
| `ruff check` on owned Python source/tests/launcher | PASS | tool output |
| `ruff format --check` on owned Python source/tests/launcher | PASS | tool output |
| `mypy apps/server/src/protohub/{worker,runtime,preview}` | PASS: 7 files | tool output |
| YAML template render + PyYAML parse | PASS | tool output |

The sample HTTP test uses a real host-loopback server on an OS-selected ephemeral port.
This verifies sample HTTP only. The Kubernetes API unit tests use a fake client and do not
establish actual Pod startup. TestClient requires an elevated process in this Windows sandbox
because native asyncio socketpair otherwise hangs; this did not alter OS settings.

## Contract/dependency changes requested

Parent approved and added `JobStore.reconcile_observation(spec, observation) -> bool` and
backend implemented atomic generation/desired/current-operation checks. Parent owns locks.
No additional dependency installs or manifest edits were performed by this agent.

Independent-review repairs included in the regression suite:

- Service routes only the current generation. Old healthy Pods during a newer rollout cannot
  satisfy Ready. Complete rollout/current-generation Pod readiness and real HTTP are required.
- Parent added ephemeral `RuntimeSpec.may_mutate`. Worker binds its live lease check, and
  every provider mutation rechecks it. Losing a lease after Service creation prevents the
  following Deployment mutation. Reconcile binds a current desired-state/generation check.
- Before kind creation, exact node-name absence is checked and a per-attempt receipt/start
  time is saved. Timeout/interrupt records only a fresh matching node ID, enabling explicit
  owned reset even when kubeadm never made the API ready. Prior nodes remain rejected.

Docker Hub official API tags/digests verified read-only; app image builds remain unverified:

- Python `3.11.18-slim-bookworm@sha256:94a8fee35252d06ab75856f15f12c7bae67b10e8a6da93c7fded82b2610926cd`
- Node `24.18.0-bookworm-slim@sha256:6f7b03f7c2c8e2e784dcf9295400527b9b1270fd37b7e9a7285cf83b6951452d`
- PostgreSQL `17.11-bookworm@sha256:839fbb5a4942a7758dd93e18b42ea5649807491a0545b5eeeb8f0b8bb11857a5`
- nginx `1.30.6-alpine@sha256:0e52bd054126cdc040b1276c0af347aeb02a41b9cfe305d6094767ac30e97949`
- kind release v0.33.0 default node `v1.37.0@sha256:a1ed56cfb0e7b93589bdf97c8cd566405a265939e3620fc4f5de89adff580ae5`

## Known issues and BLOCKED checks

- BLOCKED: image build, Compose stack, real PostgreSQL, kind, in-cluster RBAC/Pod and browser
  lifecycle verification. Host daemon unavailable; WSL Docker integration/development tools absent.
- No claim of hostile-code isolation or enforced network isolation. No NetworkPolicy/CNI proof.
- Deleted records are retained as tombstones; reconcile has eventual, not instantaneous,
  cleanup of a provider call already in flight when its lease/generation was invalidated.
- Local DB password is the synthetic `local-dev` fixture, not a production secret.
- Starlette currently warns about its httpx TestClient transport deprecation; tests pass.

## Integration notes

- API probes and nginx forward `Host: localhost` or incoming validated localhost Host.
- Server Dockerfile copies its venv to the same `/app/.venv` path to preserve script shebangs;
  Alembic/migrations reside in `/app` and `script_location` resolves relative to ini.
- Preview URL: `http://localhost:8081/apps/<UUID>/`. Console: `http://localhost:8080`.
- `PROTOHUB_CONSOLE_PORT`, `PROTOHUB_PREVIEW_PORT`, `COMPOSE_PROJECT_NAME`,
  `PROTOHUB_CLUSTER_NAME`, `PROTOHUB_MODE=mock|real-kind`; default names `protohub-local`.
- Reset only with `PROTOHUB_RESET_CONFIRM=<exact project/cluster name>`.
- QA fixtures must use distinct `protohub-*` names and ports, then use the matching reset
  interface. State under `.harness/local/{compose,kind}/<name>/state.json` records ownership.
- Daily no-env `down` restores the last active mode/name/ports from ignored local state.

Official references: [kind v0.33.0](https://github.com/kubernetes-sigs/kind/releases/tag/v0.33.0),
[Python](https://hub.docker.com/_/python), [Node](https://hub.docker.com/_/node),
[PostgreSQL](https://hub.docker.com/_/postgres), [nginx](https://hub.docker.com/_/nginx).
