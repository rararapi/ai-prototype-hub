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

Final integrated make/check/full evidence follows in `.harness/reports/` and docs/VALIDATION.md.
Real sample Pod/HTTP/lifecycle, real Playwright and live RBAC remain BLOCKED until cgroup v2.
Do not mark full acceptance complete or convert these checks into mock passes.

