# ProtoHub implementation evidence

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

Final integrated make/check/full evidence follows in `.harness/reports/` and docs/VALIDATION.md.
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

