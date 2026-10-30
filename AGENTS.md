# ProtoHub repository instructions

## Purpose

Build a local-first prototype hosting MVP: register a trusted sample, start it, open its URL, stop it, and delete it. The repository is public; never add organization-specific configuration, private code, real data, credentials, or personal information.

## Read on demand

- Start with `CODEX_TASK.md` and `docs/MVP_SPEC.md`.
- For coordination: `docs/PARALLEL_PLAN.md` and your role prompt in `harness/prompts/`.
- For verification: `docs/HARNESS_SPEC.md`.
- For local setup: `docs/WSL_SETUP.md`.
- Keep `harness/PLAN.md` current. It is a project convention, not a Codex built-in.

## Working agreements

1. Inspect the current repository and applicable instructions before editing. Preserve unrelated changes. Do not overwrite existing setup files from this starter pack without comparing them.
2. Use one coordinator and up to four bounded workers for independent implementation. Freeze API/state/provider contracts before parallel edits. Each file has one owner.
3. Prefer a separate Git worktree per worker. If all agents share one checkout, only the coordinator performs Git operations or updates shared manifests/lockfiles.
4. Do not stop at scaffolding or a proposal. Continue through implementation, tests, repair, integration, and the defined acceptance checks. Make low-risk choices and record them; ask only for material missing decisions or permissions.
5. Local branches and commits may be used for handoff. Do not push, create/merge PRs, change repository settings, publish packages, or deploy cloud resources unless separately requested.
6. Use WSL2/Linux Bash for development. Keep source under the Linux filesystem. Reuse the existing Docker engine; do not install/restart Docker, change WSL settings, or change user groups without approval.
7. Every new behavior needs tests. Use deterministic tests for state transitions and jobs; use real PostgreSQL and kind for integration evidence. A mocked API/runtime test is not real runtime verification.
8. Run the relevant gates, then the full gate on the integrated branch. Record PASS, FAIL, or BLOCKED with evidence. Missing tools, empty test suites, ignored failures, and skipped required checks are not success.
9. Treat logs/reports as potentially sensitive. Never dump all environment variables, kubeconfigs, authorization headers, or tokens. Keep local generated evidence under ignored `.harness/`.
10. Keep this file short. Put requirements in the spec, commands in scripts, and lessons in focused tests or decision records.

## Safety boundaries

- Initial runtime: fixed trusted template only; localhost-only. Public source code does not authorize public service exposure.
- No arbitrary Git URL, Dockerfile, image, shell command, uploaded code, or user-provided environment variables in v0.
- No Docker socket, host filesystem mount, or cluster-admin credential in API or sample app containers. The worker uses a dedicated in-cluster ServiceAccount and scoped RBAC.
- kind node containers are development infrastructure and may need elevated runtime capabilities. This is not permission for privileged application pods.
- Local kind is not a hostile-code isolation boundary. Kata/AKS, real SSO, real LLM access, and multi-user security are later work.
- Never use broad cleanup (`docker system prune`, global volume deletion, recursive workspace deletion). Cleanup must identify the exact resources owned by the current run. Preserve persistent data unless deletion is expressly requested.
- Do not disable sandbox/approval controls, TLS verification, RBAC, or tests to make progress appear successful.

## Code review rules

- Flag status claims that are not backed by observed runtime state, stale jobs that can resurrect stopped/deleted apps, and non-idempotent retries.
- Flag API/provider coupling, Docker socket mounts, unbounded retries, public default port binds, arbitrary upstream proxy targets, and secrets in source or logs.
- Flag a full gate that passes while real-runtime tests are skipped, or an API contract that changed without coordinated updates and tests.
- Require review of browser origin/cookie boundaries before enabling untrusted app content or authentication.

## Agent development workflow and skills

- For a meaningful implementation task, start or resume a scoped record with `harness/workflow.py`.
  Read `docs/DEVELOPMENT_WORKFLOW.md` for exact commands and evidence formats. Routine steps
  reuse the user's authorization; only material scope or safety-boundary changes need a decision.
- Record allowed/forbidden paths, one owner per scope, relevant contracts and required gates.
  Check actual changes after each unit. Preserve initial unrelated dirty files; never revert them
  to make scope checks pass. Record bounded repair attempts and stop unchanged failure loops.
- Verification and independent review must match the current HEAD and source fingerprint.
  `workflow.py finish` refuses scope violations, failed/BLOCKED or stale evidence. This is
  development assistance; the OS sandbox and approval controls remain the permission boundary.
- Read `.agents/skills/protohub-development/SKILL.md` for ProtoHub implementation work. Use
  frontend-design, applicable Vite/React best practices and web-design-guidelines for UI work;
  use security-best-practices for requested security work. Do not load every skill by default.
- Skill guidance does not authorize framework migrations, extra services, permission changes,
  paid APIs or publication. Preserve the current visual system unless redesign is requested.
  Skills are versioned with source/license/hash provenance in `harness/skills.lock.json`;
  `make skills-check` detects unreviewed drift. Read `docs/SKILLS.md` for the selected set.
- AI-DLC principles guide this development workflow. Product-internal conversational creation
  remains a later design in `docs/AI_DLC.md`; v0 does not gain arbitrary AI/code execution.
