---
name: protohub-development
description: Implement and verify scoped ProtoHub repository changes with task ownership, contract checks, bounded repair and current-source evidence. Use for ProtoHub development and harness maintenance; product end-user AI execution is a separate later feature.
---

# ProtoHub development

Use this skill to carry an authorized change through implementation, independent review
and verification without drifting into unrelated work. Work from the Git repository root.

## Establish the task

Read `AGENTS.md` and the relevant spec. For product behavior read `docs/MVP_SPEC.md`;
for execution evidence read `docs/HARNESS_SPEC.md`. Use `docs/DEVELOPMENT_WORKFLOW.md`
for the workflow CLI and evidence formats. `python3 harness/workflow.py --help` lists
the actual commands. Do not invent Codex flags, hooks, config keys or approval receipts.

Inspect the existing branch and dirty files. Start or resume a bounded work item with
an objective, allowed/forbidden paths, owners, contract paths and required gates. Keep
unrelated pre-existing changes intact. Reuse the human's current authorization; routine
implementation, test and repair steps do not need another confirmation. Record material
scope/contract decisions and obtain authorization only where the existing boundaries
require it (OS, permissions, secrets, cost, destruction or external publication).

## Implement within the contract

- Read only the skills relevant to this task: `frontend-design` for visual direction,
  `vercel-react-best-practices` for applicable React behavior, `web-design-guidelines`
  for UI review, `security-best-practices` for requested security work.
- Respect the existing React/Vite/FastAPI architecture and visual system. Next.js/RSC
  examples are not a reason to migrate the application or add unrelated dependencies.
- When parallelizing, freeze shared contracts first and give each file one owner.
  In a shared checkout the coordinator alone changes Git state and shared lockfiles.
- Run `workflow.py check --id <id>` after meaningful changes. Handle scope violations,
  changed baseline files and contract decisions before continuing. The guard inspects
  actual staged, unstaged, renamed and untracked paths; a written plan is not proof.
- Diagnose failures, record a bounded repair with its cause and next check, and rerun
  affected gates. Repeated unchanged failures require replanning or a BLOCKED record.

## Verify and hand off

Use the existing make/harness gates appropriate to the change. A full MVP acceptance
requires `make verify`. A typo or focused UI edit can use its scoped gates; do not claim
that this establishes real runtime acceptance. Never turn missing tools, zero tests,
required skips or mock observations into a PASS.

The runner records the source snapshot before and after gates. Record that gate report
and an independent review for the same current snapshot with the workflow CLI. Preserve
review findings and resolutions. `workflow.py finish` refuses stale, changed, failed or
BLOCKED evidence and missing review. A local commit changes source identity; evidence
must match the identity claimed at handoff. Keep generated task/evidence data in ignored
`.harness/`; publish no secrets, traces, real data or external resources implicitly.

Report implemented behavior, source identity, gates actually run and residual BLOCKED
checks. Distinguish mock, real PostgreSQL, kind/HTTP and browser evidence. This workflow
is an auditable development guard; OS sandbox/approval controls provide the permission
boundary. It cannot contain a malicious process that already has filesystem access.
