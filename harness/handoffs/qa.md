# QA / Harness handoff (parent-owned role D)

## Implemented behavior

- Stdlib runner: validated manifest/dependencies/paths, bounded drained/redacted logs,
  private per-run reports, exact Git metadata, interruption state and whole-process-group cleanup.
- Same make/CI entrypoints for source, contract, unit, package/image build, public hygiene,
  actual PostgreSQL, independent real-kind browser and security fixtures. Explicit host-only
  portable group supplements Docker evidence. No empty/skipped required suite can PASS.
- PostgreSQL fixture uses a unique project, internal network and tmpfs DB; four migration,
  duplicate intent, SKIP LOCKED, old-token recovery, generation/TTL/persistence tests.
- Browser lifecycle covers two apps, real sample clicks, stop/restart/delete. Live assertions
  cover duplicate requests, queue and running-lease recovery, TTL, partial creation failure,
  readiness timeout, resource removal, scoped RBAC allow/deny and Pod/API/preview boundaries.
- Fixtures preserve developer active selection, carry exact cluster/project receipts, and
  clean only their own resources. Signals get bounded cleanup grace before forced termination.
- CI actions verified at official tag SHAs. Tool binaries verified against official checksums.

## Verification

Native portable run `20261030T001936Z-d32b14e8`: all five selected gates PASS; Python89,
Vitest22 no skips. WSL harness42 self-tests PASS before final hardening. Docker/Linux source,
contract, unit passed in current integration run; full real evidence is recorded by parent
in docs/VALIDATION.md and harness/PLAN.md after completion. Handoff results are not substitutes
for the integrated source SHA's gates.

Later integrated evidence: source94fdde0 actual Docker source/contract/unit/build/hygiene and
four real PostgreSQL tests PASS. Kind failed on cgroupv1; doctor now blocks that prerequisite
before creating resources. Mock actual lifecycle/Windows HTTP/DB stop-start persistence PASS
after fixing tmpfs YAML. Python3.10 timestamp cleanup repaired; both known failed clusters were
removed with exact-ID/receipt verification. New developer workflow + pinned skills integrated;
72 stdlib self-tests PASS and independent synthetic forward-test complete. Final reports record
the latest source identity; real Pod/HTTP/browser/live RBAC remain BLOCKED, never mocked green.

## Review repairs

Compose build owner interpolation and hello-web build context fixed; termination grace waits
for fixture descendants; integration signal cleanup tested with fake Docker; kind checksum
filename corrected; explicit no-activate fixture mode; running-job worker death test added.

## Limits

Public hygiene is a bounded heuristic plus human review, never a guarantee. No hostile-code
isolation, CNI isolation assertion, cloud credentials, real LLM or public deployment is used.
