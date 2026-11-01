# Active: simplify CI scheduling (2026-11-02)

- Work item ci-simplify-20261102, clean base d5118d7; branch codex/simplify-ci.
- Coordinator owns workflow, policy regressions, HARNESS_SPEC and this PLAN; ci_review
  independently reviews. API/state/provider contracts, runtime fixtures and dependencies stay fixed.
- PR runs the existing Dev Container make check-dev; only main push and manual dispatch run
  make verify. Feature-branch push no longer duplicates PR runs; main/manual omit the duplicate
  Dev Container job. Full group still requires all11 gates, including real DB/kind/browser/security.
- PR quick success is not runtime acceptance. Runtime changes require current-source full
  evidence before merge. Manual dispatch becomes available after default-branch adoption.
- Observed previous local full gate: about18min, e2e742s + security224s; main CI quick87s.
  These are measurements, not a guaranteed future CI duration.
- All11 local full gates and independent review required for this change; generated evidence
  lives in worklogs/workflows/ci-simplify-20261102/. Publication is a separate requested action.

# Active: generated work records renamed to worklogs (2026-11-02)

- Work item worklogs-rename-20261102, clean maine366e2c; local branch codex/worklogs.
  User selects worklogs/ for generated work records. No new publication/PR/merge requested.
- Source tools remain harness/. API/state/provider contracts and package dependencies are unchanged.
- Coordinator owns common paths, runner/workflow/check tooling, CI/ignore/docs/local skill hash;
  local-worker owns launcher and migration regressions. Shared checkout Git stays coordinator-only.
- worklogs_dir(root) verifies ignore rules in Git checkouts, rejects symlink/non-directory or
  conflicting old/new roots, then atomically renames legacy .harness/ to worklogs/ without
  rewriting historical JSON. It does not create a new owner alongside old receipts.
- New paths are excluded from Git, Docker contexts, source fingerprints and hygiene scans;
  legacy exclusions remain. CI binaries and artifacts use worklogs/. Historical paths are
  explicitly marked as original records. Unit tests verify bytes/inode/mode preservation;
  actual retained resource IDs/owner receipts and6 historical recorded hashes match.
- Preliminary checks:117 stdlib harness tests PASS,71 launcher-related tests PASS with
  readonly source bind, skills integrity PASS. Existing fixture isolation was repaired so
  unit tests no longer invoke migration on the actual checkout.
- Full11 gates plus independent current-source review required. Exact receipts live under
  worklogs/workflows/worklogs-rename-20261102/; persistent DB/cluster resources are retained.

# Active: post-API-rollout public recovery barrier (2026-11-01)

- Work item api-rollout-recovery-20261101, clean base46755f5 on existing PR1 branch.
  User authorizes repair, regressions, full verification and PR update; no merge/deploy.
- Failed push CI41288648133 artifact run20261101T082323Z-92ac93ba records browser2 PASS,
  restart/read persistence PASS, then POST /sandboxes returns nginx502. Same-source local
  and PR CI41288670157 passed. Evidence establishes a readiness race, not an nginx defect.
- Coordinator owns tests/e2e/, apps/server/tests/runtime/, HARNESS_SPEC and this PLAN;
  rollout_review independently reviews without tracked edits. API/state/provider contracts,
  production proxy/auth/runtime, dependencies and CI permissions are unchanged.
- Recovery contract: after rollout, require old Pods absent, exactly one different Ready
  API Pod UID, then matching retained-record GETs through console spanning3 stable seconds.
  Reset on transient502/503/504/transport failures or Pod/UID changes; fail immediately for
  permanent HTTP/auth/malformed/wrong-record responses. All probes share a120s deadline.
- POST and whole-scenario retries remain disabled. Real E2E repeats3 rollouts then one
  registration each, asserting exactly one matching ID; sanitized recovery observations
  are retained in runtime-checks.json. Unit regressions are collected by the existing gate.
- Targeted deterministic regressions35 PASS; independent pre-freeze review found no blocker.
- Final acceptance requires all11 gates and independent review on the integrated HEAD;
  exact receipts live in worklogs/workflows/api-rollout-recovery-20261101/ and PR1.

# Active: development login, sharing and shared LLM configuration (2026-11-01)

- Work item: dev-login-shared-llm-20261101, base a5ab05b, clean main; branch
  codex/dev-login-shared-llm. User explicitly authorizes implementation, tests and PR.
- Shared checkout: coordinator alone performs Git, dependency and generated-contract operations.
- Frozen contract: POST auth/login {email} returns {token,email,expires_at}; GET auth/me
  returns {email}; POST auth/logout {} revokes bearer session. Sessions expire after 24h,
  random token stored hashed in PostgreSQL, no authentication cookies or preview forwarding.
- Auth exists only in local/development/test environments. Production disables login and
  protected endpoints. Email-only login is impersonation for trusted local development.
- Sandbox owner_email is nullable only for legacy records. New registrations bind server-side
  to principal. Legacy rows remain retained and hidden; no automatic user adoption.
- List/detail/operation visibility: owner or explicit shared recipient. Lifecycle/share writes
  are owner-only. PUT shares {emails} replaces up to100 normalized recipients; GET shares
  is owner-only. Unauthorized resource IDs return404. Shared preview stays trusted localhost
  sample only; this change does not enable private or untrusted hosted app authentication.
- Shared LLM key: PROTOHUB_LLM_API_KEY SecretStr, server-only resolver for all app IDs.
  No real key, billable calls, arbitrary code or new LLM provider is introduced.
- Ownership: coordinator domain/contracts/generated types, settings, infra/key plumbing,
  docs/PLAN and integration; Backend API/persistence/migrations/server tests; Frontend
  web source/styles/tests except generated types; QA tests/integration and tests/e2e.
- Preliminary evidence: backend API70 PASS, frontend36 PASS plus lint/type/build; real
  PostgreSQL5 PASS including migration/session/ownership/share persistence and revocation.
- Independent review repaired named-stack environment persistence on success/failure and
  disabled-control modal keyboard focus. Deterministic regressions retain these findings.
- Acceptance: all eleven full gates and independent review must match the integrated HEAD.
  Exact PASS/FAIL/BLOCKED reports and source identity are recorded under ignored
  worklogs/workflows/dev-login-shared-llm-20261101/ and linked in the PR; earlier partial
  reports do not establish final acceptance. Daily stack/PVC are retained.

# ProtoHub implementation evidence

## Current acceptance and main integration (2026-10-31)

- Clean e904814 passed all11 local full gates (run20261031T105929Z-f614eec3), manual real
  browser/counter/lifecycle and daily PVC/record persistence. Failed earlier runs remain intact.
- The same e904814 also passed GitHub CI41205573111: devcontainer and verify, all11 full gates.
- The human then authorized main integration and selected MIT. Work item mit-main-20261031
  adds LICENSE, updates the local skill license metadata and stale setup/status claims, and
  documents residual issues in docs/ROADMAP.md. Runtime/API/dependencies are unchanged.
- This documentation/license commit receives its own scoped gates and independent review;
  main is advanced only after its exact CI head succeeds. No extra OS/permission/cost change.
- Residual work is described, not silently started: dev-tool advisory compatibility update,
  targeted bootstrap diagnostics, additional host/architecture coverage and product AI design.

## Starting state (2026-10-30 JST)

- Branch: `codex/protohub-local-mvp`, base repository commit `5bd9059`.
- Existing tracked code: README only; untracked user input pack in docs/setup retained.
- Input filenames were mismatched. Contents compared and copied to canonical docs/prompts.
- Shared checkout: one file owner; parent alone performs Git/install/lock operations.
- Native Windows: Python 3.11.4, Node 24.18.0, npm 11.16.0, uv 0.11.19 available.
- Read-only WSL access requires sandbox escalation. Existing Ubuntu is WSL2/running.
- WSL has Python but no make/node/uv/kind/kubectl; Docker WSL integration unavailable.
- Windows Docker client 25.0.3 exists, daemon pipe unavailable. No OS changes performed.
- Linux filesystem development is currently unavailable as a complete toolchain; independent
  checks may use existing native tools. These do not establish WSL/Docker acceptance.

## Progress

- Phase 0 complete: baseline `96256a5`, canonical OpenAPI/examples, DTOs, settings, provider,
  JobStore/UnitOfWork, generation/lease token and bounded retry contracts. uv.lock resolved.
- Phase 1 complete: A Backend, B Frontend, C Runtime worked in parallel; parent owned D QA.
  Shared checkout Git/install/lock updates stayed with parent. Handoffs exist per role.
- Phase 2 integrated in A→C→B→D order: `7f33fdc`, `38986b3`, `0d71c12`, `8d86814`.
- Independent reviews completed by Frontend (Backend/Runtime) and Backend (QA). Fixed false
  current-generation Ready, mutation fencing after lease loss, failed kind creation receipts,
  build owner/context, checksum filename, fixture active selection and interruption cleanup.
- Native portable run `20261030T001936Z-d32b14e8`: source/contract/unit/build/hygiene PASS;
  Python 89 + Vitest 22 tests, no required skips. Harness WSL self-tests 42 PASS at that point.
- Docker became available during verification. Original kubectl1.29 is too old for node1.37.
  Temporary Linux validation copy and workspace-local make4.3/kind0.33/kubectl1.37 prepared;
  kind/kubectl official checksums verified. No host OS configuration/install was performed.
- Linux quick `20261030T001543Z-a4f5cdf2` at `8d86814`: all selected gates PASS, including
  actual Docker builds. Full `20261030T002409Z-fe52d19a` at clean source `94fdde0` passed
  source/contract/unit/build/hygiene and real PostgreSQL integration (4 tests, no skips).
- Real kind bootstrap failed: Docker25.0.3 daemon uses cgroup v1; node1.37 kubelet refuses it.
  Initial full report preserves actual FAIL for E2E/security. Doctor now detects this as
  BLOCKED before resource creation. No cgroup override or host OS change was performed.
- Real bootstrap also exposed Docker RFC3339 nanosecond parsing on Python3.10. Fixed and
  tested at the minimum interpreter. Recovered the two known failed nodes using exact
  observed container IDs + original receipts; verified cleanup, no foreign resources touched.
- Mock actual startup exposed YAML tmpfs splitting; fixed in `0c331d5` with regression checks.
  The isolated mock copy passed register/start/duplicate/stop/restart/delete, two-app independence,
  Windows localhost HTTP, and full DB stop/start persistence. Its volume retention was observed;
  the explicitly named test project and test volume were then reset.
- User clarified developer harness + skills. Added scoped task CLI, baseline/ownership/contract
  decisions, bounded repair, exact source snapshots, gate+independent review linkage, and
  refusal of stale/missing/failed evidence. WSL harness self-tests: 72 PASS at this stage.
- Added four pinned upstream skills + one local development skill, license notices/hash lock,
  offline reference adaptation and source gate validation. Independent synthetic forward-test
  exercised actual FAIL→repair→PASS→independent review→finish without routine approvals.
- AI-DLC principles adopted for development; product conversational workflow is design-only
  in docs/AI_DLC.md. No embedded AI, paid API/model choice or arbitrary-code execution added.

## Final acceptance

Dev Container follow-up: task `devcontainer-20261030` adds a non-root coding/check
toolchain, three instance-specific dependency volumes, existing harness/skills integration,
and CI using `make check-dev`. Runtime/Backend/Frontend split config, boundary tests and
the operator guide; parent owns shared checks, CI and integration. No Docker socket,
host kubeconfig, host permissions or OS settings are added. Actual CLI/host results are
recorded in docs/DEV_CONTAINER.md; this does not clear the existing real-kind blocker.

Local-PC clarification: `local-pc-dev-standard` documents the shared per-developer
clone/reopen/check baseline, tested Windows/WSL2 amd64 scope, untested other PCs/OS/ARM,
and residual host/runtime and image-rebuild differences. This is a documentation-only
clarification; it does not add runtime permissions or claim cross-PC acceptance.

README illustrations: `readme-concept-images` uses the built-in image generation tool
for concept/lifecycle and logical architecture assets in docs/images/. Parent owns
the assets, prompts and README; Backend/Frontend independently review factual scope
and image readability. Images explain the current trusted-template MVP, distinguish
mock from real-kind, and do not claim product AI execution or runtime verification.
Image/reference/hygiene checks and an independent review cover this documentation change.

Diagram revision: `readme-diagrams-v2` replaces the vague concept artwork with a
three-panel registration/start/wait/open/click story and per-app lifecycle examples.
The engineering diagram now covers real-kind namespaces, actual localhost/NodePort
entrypoints, Preview traffic, PostgreSQL/PVC, scoped worker control and job fencing;
mock remains a separate Compose alternative. Source/config audits by Backend and
concrete sample UI/design audit by Frontend inform generation and final review.

Final integrated make/check/full evidence follows in `worklogs/reports/` and docs/VALIDATION.md.
On 2026-10-31 the human authorized WSL/Docker Desktop updates and approved UAC on the PC.
Both installers exited 0. Offline DB/VHDX backups, all five baseline volumes and the unrelated
stopped container were verified; mock DB counts and HTTP recovery passed. Engine29.9.2 now
reports cgroup2 and kind control-plane starts. Initial real bootstrap exposed an incorrect
server Docker build target, and review found a worker shutdown race; both are fixed with
regressions in 5575c23. Current scoped work is real-kind-completion-20261031. The interrupted
initial full report remains evidence of that attempt, not a PASS. Real lifecycle/browser/live
RBAC and final full acceptance must follow the current report; no mock substitution is allowed.

Real validation follow-up: browser register/start/Ready/counter/stop/restart/delete passed,
with actual sample Pod/Service existence and removal observed. Full 20261031T083523Z-ef7fa992
at 5575c23 passed 10 of 11 gates, including four real PostgreSQL tests and five live security
checks. E2E's fixture port58867 conflicted with Windows reservations; owned cleanup succeeded.
dc7fc38 adds bounded non-ephemeral fixture port selection and wall-clock subprocess limits
for drain; launcher28 and port7 regressions plus independent reviews passed. Re-run full on
the integrated documentation/source HEAD and record that exact report before workflow finish.

Supplemental daily stop found the empty sample selector scale failure. Repair scope was
replanned (the earlier three-attempt budget was not silently extended) to
real-kind-down-empty-20261031. f98381d fixes the empty case while always draining remaining
Pods; actual daily down/all control Pods gone/up passed with a new DB Pod and the same PVC
and management record. An independent review also checks the foreground-delete/scale
disappearance race before final acceptance. The interrupted eb31499 full is not a PASS.
The narrow race handler requires explicit target-disappearance diagnostics, a fresh empty
Deployment selection and successful Pod drain; other errors remain failures. Runtime's
related launcher suites now contain 51 passing tests. Final full/review must match the new
integrated HEAD; no resource-reset or OS-setting change was used for these repairs.
The first real browser run on5a7b64f reached deletion but hit the aggregate180s budget.
The two-app scenario now has420s while each expectation remains100s, retries remain0,
and assertions are unchanged. Failed trace/screenshots/report are preserved; security in
that run was interrupted before repetition. Config/spec collection passes; final runtime
acceptance still requires all eleven gates on the new integrated HEAD.
Post-image-extraction Ubuntu CLI timeouts also blocked that fixture's cleanup. Read-only
native plugin/socket/daemon probes confirmed recovery; the exact retained node was then
removed using its original ID/receipt and normal ownership guard. Recovery cleanup PASS;
daily resources retained, no additional OS restart/config/permission change was needed.

Full f3a8289 / 20261031T093017Z-4a52d79b passed10/11, including browser1/1 and live security5.
The remaining E2E runtime check observed public502 immediately after API rollout; owned cleanup
succeeded. New bounded scope real-public-readiness-20261031 waits for actual HTTP recovery of
the same retained record, stabilizes the sole worker holder before enqueue/death injection,
and strengthens failed/timeout cleanup to all owned resources plus the exact timeout code.
No whole-scenario retries or contract changes are introduced. Final full/review must match HEAD.

At515c789 / 20261031T100446Z-4e908c19, browser1/1 + real runtime8 + live security5 all passed,
but both gates correctly failed because cleanup's CLI-info probe timed out before deletion.
New scope doctor-server-metadata-20261031 replaces only server capability reads with one
verified AF_UNIX GET/info, absolute12s/1MiB bounds and no TCP/auth/proxy/CLI fallback; all
context, tool, mode and ownership guards remain. 5d3ae05 passed107/107 WSL harness tests,
live doctor-kind, and exact normal guarded cleanup of the two retained fixtures. Full on the
integrated HEAD is still required; earlier functional PASS counts do not complete acceptance.

