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
- Linux copy `/tmp/protohub-verification.qJtY8v/repo` at source `8d86814`: doctor-kind PASS;
  actual Docker source/contract/unit gates PASS, build running. New hardening fixes follow.
- Phase 3 in progress: real PostgreSQL, mock lifecycle and kind/browser checks next.

## Final acceptance

PASS/FAIL/BLOCKED will be recorded from current-run evidence, never copied from handoffs.

