# Active: speed-focused concept and shorter main proposal (2026-11-04)

- Work item proposal-concept-speed-20261104; preserve all earlier uncommitted proposal work.
  Coordinator owns docs/proposal/ and PLAN; independent reviewer writes ignored evidence.
- User requests prior sections3(cloud sharing),4(rollout),6(approval) in appendix. Main:
  decision,value,cost; renumber cost03 and appendixA1-A8. Keep section IDs/deep links.
- Concept: field ideas quickly become something to try; retain create/use/grow internally.
  Highlight shorter creation-test-improvement cycles without invented timing/SLA claims.
- Pricing/model assumptions and calculator unchanged: monthly113296.6125JPY, budget140000,
  three-month420000. Existing public price evidence retained without fetching or mutation.
- Required scoped browser/structure/copy/print and public-hygiene plus independent review.
  No product/runtime/contracts/cloud/paid API or permission changes.

# Active: manager approval proposal and lean pilot (2026-11-04)

- Work item proposal-manager-20261104 preserves previous uncommitted proposal work.
  Coordinator owns docs/proposal/ and PLAN; independent reviewer writes ignored evidence.
- Manager body focuses on value, illustrated As-is/To-be/cloud sharing, rollout and budget.
  Detailed Azure architecture, current gaps and math/sources move to appendix.
- Compare lean VM pilot candidate against retained AKS reference; no actual platform change.
  Fresh public VM/PG meters checked. Default infra USD245.9774167, LLM176, creation50000JPY,
  FX150=>113296.6125JPY; reserve20%,10k rounding=>140000/month420000/3months tax excluded.
- NoHA, bounded concurrency, unverified provider compatibility, self-managed operations and
  recovery conditions explicit. Lower Azure spend does not imply lower total operations cost.
- Required scoped browser/math/illustration/print and public-hygiene gates; current-source
  independent review. No product changes, installs, cloud provisioning or paid API requests.

# Active: add separate monthly app creation fee (2026-11-04)

- Work item proposal-creation-cost-20261104 preserves the prior uncommitted proposal.
  User confirms monthly JPY50,000 app creation cost is additional to Azure and LLM.
- Coordinator owns docs/proposal/ and this PLAN; product/API/runtime/infra unchanged.
  Treat fee as a user estimate, not a vendor quote; JPY-denominated and FX-independent.
- Default total JPY193,520.5125; reserve20% then monthly rounding to JPY10,000 gives
  JPY240,000/month and JPY720,000/3months. Azure/LLM meters remain unchanged.
- Required scoped gates: proposal browser/math/print and public-hygiene, followed by
  independent current-source review. No paid API calls, cloud changes or publication.

# Active: business self-service proposal and LLM budget (2026-11-04)

- Work item proposal-business-llm-20261104 builds on the previous uncommitted proposal.
  Coordinator owns docs/proposal/ and this PLAN; independent reviewer owns only ignored
  review evidence. Product/API/runtime/infra/contracts/dependencies remain unchanged.
- User expands goal to business-owner self-service creation, internal cloud sharing,
  persistent data, proposal/PD and internal work, suitable continued business use, and
  advanced architecture escalation to AI Factory. This is a planned platform, not current MVP.
- Costs now cover Azure infrastructure plus creation and runtime LLM API usage. Assumptions
  are editable; model is not selected. Reference GPT-4.1 Global Standard USD2/8 per 1M tokens
  is public price evidence, not a capability/availability recommendation or Japan-only inference.
- Default example: 10 users, system2 D4as_v5 + user1 D2as_v5,730h, PG B2s64GiB noHA,
  Blob100GB, shared ingress and retained resources. Infrastructure and LLM costs stay separate.
- Required scoped gates: calculator/browser/source-provenance and public-hygiene, followed
  by independent current-source review. Evidence under ignored worklogs/.
- No cloud resources, paid API requests, product feature implementation or publication.

# Active: approval proposal and Azure estimate (2026-11-04)

- Work item proposal-azure-20261104; clean base aa2db69. Coordinator owns docs/proposal/
  and this PLAN. Product/API/runtime/contracts/dependencies remain unchanged.
- User requests a Japanese approval proposal in HTML and Azure infrastructure costs only.
  Offline single-file HTML; public Microsoft retail meters, Japan East, tax exclusive,
  assumed exchange rate with an editable calculator. No cloud provisioning or publication.
- Compare bounded technical PoC (220 AKS hours) with always-on (730 hours); two D4as_v5
  nodes, managed PostgreSQL B1ms, private DB, authenticated ACR, NAT egress and monitoring.
  No public application ingress. Shared business use/SSO/untrusted code are later scope.
- Required scoped gates: proposal browser/calculation checks and public-hygiene; independent
  review must match the source snapshot. Full product runtime acceptance is not claimed.
- Browser checks cover 21 cases, including independent USD/JPY expectations, invalid inputs,
  retained resources, offline/no-JS, mobile and print. Print spacing removes orphan pages.
- Evidence stays under ignored worklogs/; selected public price meters are in docs/proposal/.

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


# GitHub Pages browser demo (2026-11-04)

- Work item pages-demo-20261104: coordinator owns apps/web, Pages workflow, docs/GITHUB_PAGES.md, pages-demo check and this appended plan. Prior proposal work preserved.
- User authorizes public browser-only operation demo and mocked LLM; no backend or paid API calls.
- Explicit demo build uses memory-only lifecycle/TTL, no cross-viewer sharing and labeled static sample. Normal API unchanged.
- Required pages-demo/public-hygiene checks and independent current-source review. Full real-runtime acceptance stays separate.
- Initial publication uses only built static files in the dedicated gh-pages branch. Future manual main workflow supports Actions source after integration; no main merge performed here.

# Mock AI creation and management dashboard (2026-11-04)

- Work item pages-ai-kpi-20261104: user clarified the template is business management, not KPI. Coordinator owns apps/web, Pages check, demo docs and appended PLAN. Preserve earlier dirty work.
- Browser-only fixed templates: Hello Web and management-dashboard. Typed deterministic instructions update title, copy, palette, financial trend, department table and cash-flow card; bounded history and undo. No generated code, backend calls or paid LLM.
- Existing backend/OpenAPI/generated contract and real runtime remain unchanged. Normal client rejects the demo-only template.
- Require Pages unit/build/real-browser/no-network and public-hygiene gates plus independent matching-source review; publish verified static artifacts only.
- Implemented management template and mock creation/refinement/undo. Unit/component regression and project-path browser flow observed passing; fixed initial-instruction mount race, subtitle parsing and mobile badge positioning. Final matching-source gates/review required before static republish.

# Mock app sharing demo (2026-11-04)

- Work item pages-sharing-20261104: coordinator owns apps/web, Pages check, demo docs and appended PLAN; preserve all previous source/proposal changes.
- User requests showing sharing in the existing public mock demo. Add fixed synthetic members, per-app saved read-only selection, recipient view, denial/revoke and stopped/deleted states.
- No real invitations, email, authentication, cross-browser ACL, public-link revocation, backend or paid API calls. Current localhost sharing contract stays unchanged.
- Require current-source Pages unit/build/real-browser/no-network/public-hygiene plus independent review, then update only the owned gh-pages static branch.
- Sharing mock implemented: 59 unit/component tests and browser grant/view/deny/revoke/stop flows observed passing. Visual QA adjusts narrow recipient finance cards to one column; reload check grants the same initial app before reloading. Final current-source gates/review precede static publication.

# Private GKE development deployment and AKS portability (2026-11-05)

- User selected GKE with the same application manifests for AKS. Scope `gke-aks-private` preserves the existing dirty demo and proposal. The earlier VM/static approach was superseded before source edits.
- Common renderer reuses the Kubernetes runtime, namespaces and worker RBAC. Use private registry digests, explicit storage class, ClusterIP, policy-enforced ingress, database Secret and operator loopback port forwards. The trusted single-developer mode uses the existing development login.
- Verify current manifests, ownership and retry behavior with `python3 harness/run.py --group managed`; run `make verify` for the local MVP. Cloud IAM, registry pushes, cluster resources, observed Pod/HTTP lifecycle and actual CNI behavior require an approved private cluster. Store current execution and independent review evidence under `worklogs/`.
- Implemented the common renderer, scoped policies, explicit-context installer and Japanese operator guide. Regression coverage includes sample-only worker rollouts, version-checked updates, retained credentials, foreign namespace refusal, allowed/denied Pod paths and the release build commands.
- WSL doctor observed Docker/Compose/Buildx unavailable. The separate TLS/RBAC-enabled local Kubernetes v1.34 API fixture exercises installations and updates without scheduling Pods. A cloud cluster, approved registry and live CNI/HTTP checks remain deployment-side prerequisites.

# Google member authentication and new Internet-facing GKE (2026-11-06)

- Work item google-private-gke-auth. Use the new project specified in chat; budget, location, DNS/TLS and deployment-side credentials remain operator inputs. No project identifiers or email addresses in source. The cluster management endpoint, nodes and DB stay private. Internet access is an explicit option on the two-host HTTPS Gateway.
- Production uses Google GIS popup code exchange, verified UserInfo, explicit administrator provisioning, immutable verified subject binding and per-request membership/ACL checks. Development email sessions and cloud Google sessions cannot be reused across modes. DB migration and memberships retain prior data on revocation. The trusted sample renders in a sandboxed, opaque-origin frame.
- Accept current contract/portable builds, API/UI/preview and infra tests and independent review. Separate local evidence exercises real PostgreSQL, Chromium against real FastAPI with a simulated Google exchange, and a Kubernetes API server without worker nodes. Live Google OAuth, GKE scheduling, DNS/TLS and provider network enforcement require actual deployment.
- Verified the user-selected project is ACTIVE with billing linked. Enabled the four required APIs, verified a dedicated node service account with its minimum project role and no user-managed keys created by this run, and created an empty custom-mode VPC. No GKE cluster, node VM, registry, load balancer, DNS record or real OAuth credential was created by this task. Regional resources await budget/location and DNS/TLS inputs.
- Real local evidence: PostgreSQL migration with concurrent binding/revocation and retained subject, Chromium against the actual API/preview and sample with only Google and runtime readiness simulated, and isolated Kubernetes API admission/reapply retaining the DB and OAuth secrets. WSL/Windows Docker engine was unavailable for full local runtime acceptance.

# Tokyo GKE with two default HTTPS origins (2026-11-06)

- Work item `tokyo-default-url-release`. The operator selected Japan, one zonal cluster, a monthly budget and Google sign-in for an explicit list of members. Use separate Cloud Run HTTPS origins for the console and preview. Keep the private GKE control plane and nodes, one on-demand node, and the PostgreSQL volume on the shared Kubernetes model.
- The authenticated Tokyo build produced four immutable image digests. Evidence for the build, both IAM-closed reservations, the project budget and the private network is retained in ignored local records. Use the named cluster and dedicated identities only. Cloud Run and GKE resource ownership and live authentication checks precede internet publication.
- The initial database stage accepts only fresh or partially staged private resources and preserves the original Secret/PVC. Full Google release requires the operator's genuine OAuth Web client. Verify actual PVC binding, database readiness and permitted membership on the cluster, then verify registered and unregistered browser behavior before treating public login as operational.
- Run the managed and Google-account gates and the full local acceptance gate after final integration. Record blocked dependencies separately from passed tests.
- Actual Tokyo verification reached the private Kubernetes API over TLS, validated all 21 application manifests by server dry run, observed PostgreSQL accepting connections on a bound 1 GiB PVC, migrated the schema and confirmed exactly one intended active member. A new trusted sample reached Ready on its registry digest, returned HTTP 200 for the page and health check, stopped to zero Pods, and was deleted by UID. Both reserved HTTPS services remained IAM-closed. Actual Google sign-in and the public browser lifecycle await the OAuth Web client.

# Activate the operator-provided Google Web client (2026-11-07)

- Work item `tokyo-google-live`. The operator supplied the downloaded OAuth Web client for the already approved Tokyo deployment. Validate exact origins privately, keep credentials outside the public repository, preserve the DB Secret/PVC and the one explicitly enrolled member, and deploy the existing pinned images.
- Five application components rolled out in the private cluster. Publication requires live Google-mode and anonymous-denial probes, both over private application forwarding and the two actual Cloud Run HTTPS origins. Keep any real Google browser sign-in evidence separate from synthetic checks and record residual user interaction accurately.
- The management probe must work from Windows and Linux. Replace the socket-only selector on the kubectl output pipe with a bounded reader queue, with real subprocess tests on both platforms. No application image change is required by this operator-tool correction.

# Fixed-profile creation brief (2026-11-07)

- Work item `architecture-aware-brief`. Preserve all pre-existing Google-auth, managed-deployment and static-demo changes. Coordinator owns the scoped web files, creation specification and this plan. API/runtime/infra and shared manifests remain outside scope.
- Freeze the browser-only `trusted-preview-v1` profile: explicit display configuration plus purpose, audience and success intent. Freeform business text is never interpreted as a command. No model, code executor, new backend, publication or deployment is authorized by this unit.
- Implement purpose/audience, applicable display choices and a current-plan review before the existing demo create/start path. Retain the original requirements on the app editor across display revisions and undo; label plans separately from test results and runtime observations.
- Required evidence: current-source portable checks, both production/static builds, Chromium creation/review/preview/mobile and zero API/LLM requests, independent review and scope check. Run the full local gate as an additional acceptance check and record unavailable Docker/kind execution as BLOCKED, never as a demo success.

# Publish the fixed-profile creation flow (2026-11-07)

- Work item `publish-creation-brief`. The user explicitly requested deployment after the local implementation. Publish only the current static demo to the existing `gh-pages` branch and existing Pages URL. No source-branch push, PR, repository setting, backend/cloud deployment or new paid resource belongs to this scope.
- Preserve all existing dirty implementation files. Coordinator owns the publication documentation and this plan. The Pages transport remains browser-only, with sample data and no API/LLM calls.
- Verify the current demo build, inspect the exact static artifact inventory and source fingerprint, independently review the publication scope, then advance the existing publication branch from its observed head with a lease. Preserve its parent for rollback and include public release provenance without local paths or secrets.
- Confirm actual HTTPS content and assets, then run the new purpose/review/preview interaction on the public URL. Record local-static evidence separately from public-browser evidence and the full local runtime gate's Docker-related limitation.

# Real Gemini, main integration and existing GCP update (2026-11-07)

- Work item `gemini-creation`. The user explicitly requested merge to main, real LLM calls (Gemini first) and GCP deployment. This authorizes integration/publication and bounded model/build/deployment operations for the existing project. Preserve unrelated proposal files, persistent DB/PVC/OAuth data, registered origins and private GKE management.
- Freeze shared DTO/API/ORM contracts before bounded backend/frontend workers edit their owned files. Coordinator owns shared contracts, lockfiles, integration, infra and all Git/cloud mutations. Use Vertex ADC with a dedicated API KSA and minimal prediction/service-use permissions; no new service-account key, Kubernetes RBAC/token mount or runtime-provider coupling.
- Generate schema-validated trusted display plans, retain owned revisions in PostgreSQL, count every model attempt against durable per-user/global limits, cache request IDs and reject stale completion/confirmation/deletion races. Preserve offline static demo and label screen plans separately from real runtime state.
- Required source evidence: public hygiene, lint/type/contract/unit/build, managed manifests/source archive, real PostgreSQL concurrency, current independent review. Record the full local gate separately if unavailable Docker blocks kind. Real Gemini/GCP deployment evidence must observe actual provider usage, API-Pod identity, auth rejection, migration/retention and saved plan behavior.
- Merge only current reviewed source/dependencies needed for the app and existing GCP setup. Do not publish ignored operator records, OAuth files, tokens, real user data or unrelated proposal material. Use a content-addressed bounded Cloud Build archive, immutable images, exact owned temporary admin resources, closed-edge update/private probes/reopen and precise operator cleanup.

# iPhone Safari AI draft input (2026-11-07)

- Work item mobile-draft-input. The user reports that the AI draft modal cannot accept input on iPhone Safari. Preserve the current design, API/model/auth contracts and unrelated proposal files; repair and redeploy the existing GCP target under the prior authorization.
- Coordinator owns the callback/focus implementation, gate and release. Frontend owns a realistic polling regression and mobile touch browser checks; independent review uses the current source/evidence. No new model call is needed to verify text entry.
- Reproduce with fresh JSON polling responses while a text input/textarea has focus, a non-terminal caret and an in-progress edit. Use fresh per-response objects in the deterministic component regression. Verify actual touch/slow typing, retained focus/caret across at least two production poll cycles, short-viewport scrolling and close/focus restoration with WebKit iPhone emulation. No model generation is needed. Headless WebKit is engine evidence, not a physical iPhone keyboard test.
- Publish a bounded web build with immutable digest; retain the running API/worker/preview/DB images, data, OAuth configuration, original origins and private control plane. Use the existing closed-edge/private-check/reopen procedure and remove only exact owned temporary operator resources.

- The user additionally requests a simple first screen for the desired app/outcome and no prefilled management-dashboard content. Start with one empty free-text field and examples only in placeholders; continue to neutral/empty details while retaining explicit input. Keep saved-plan review/revision and all API/UUID safety behavior unchanged. Verify the new initial field as well as later fields during real polling.
