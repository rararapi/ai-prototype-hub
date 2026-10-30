# frontend handoff

## Changed files / commit

- Shared checkout: `C:\Git\ai-prototype-hub`, baseline `96256a5d096109d253bd83ff1e990242f83a454d`.
- Ownership: `apps/web/**` and this handoff. Parent performs commits, installation and lock updates.
- Added React/TypeScript/Vite application, generated-contract API client, local styles,
  registration/deletion dialogs, accessible controls, unit/component tests and npm scripts.
- Parent installed dependencies and generated `src/generated/api.d.ts`; package-lock belongs
  to that parent operation. All manifest versions now use the observed installed stable versions.

## Implemented behavior

- Registers only the `hello-web` trusted template with name and 60–3600 second TTL input.
- List and selected detail use server observations; accepted operations never invent Ready.
- Start/stop/delete send JSON and `X-ProtoHub-Client: console`, including JSON `{}` on DELETE.
- Loading, initial failure, empty, retry, mutation failure and provider failure have distinct UI.
- Double submissions are suppressed while pending. API remains responsible for actual idempotency.
- Named delete confirmation explains resource deletion and retained management tombstone.
- Mock banner is permanent and mock never exposes a preview link, even for a malformed API response.
- Real observed `running` exposes only a local HTTP(S) URL without credentials in a new tab.
- Sandbox observations continue every 1.8 seconds for TTL/external changes. Terminal operation
  polling stops; queued/running operations poll until completion. Polling aborts on unmount.
- Dialog keyboard focus is contained and restored; Escape closes idle dialogs, mutation-pending
  dialogs remain open. Responsive layout, reduced-motion support and contrast-aware secondary text.

## Tests actually run

Executed from `apps/web` with existing Windows Node 24.18.0/npm 11.16.0. These are native
toolchain checks and mocked HTTP component tests, **not** WSL/Docker/real-kind verification.

| command | result | evidence |
| --- | --- | --- |
| `npm run typecheck` | PASS | TypeScript strict check, no errors |
| `npm run lint` | PASS | ESLint, max warnings 0 |
| `npm run test:unit` | PASS | 22 tests across App/client suites, no skipped tests |
| `npm run build` | PASS | Vite production output in ignored `apps/web/dist` |
| `npm run check:api` | PASS | Fresh generated types exactly match canonical OpenAPI |

Cases include registration, starting/stop, actual observed Ready vs mock, unsafe URL rejection,
named deletion/tombstone, runtime failure, API error/request ID/retry, cancellation, duplicate
clicks, persistent mutation errors, terminal operation poll stopping and unmount cancellation.

## Contract/dependency changes requested

- None to API/domain. DTO types derive from `contracts/openapi.yaml` through openapi-typescript.
- Parent should refresh package-lock metadata after replacing initial `*` devDependency
  ranges with the exact observed installed versions; no dependency graph change requested.

## Known issues and BLOCKED checks

- Actual browser/real PostgreSQL/kind lifecycle verification remains QA/parent-owned and
  BLOCKED until local Docker/WSL prerequisites are available.
- Native component success does not prove runtime readiness, HTTP routing, Pod cleanup or RBAC.
- TTL duration input is shown during registration; detail shows API-provided expiry timestamp,
  because the frozen Sandbox response contains `expires_at`, not the original TTL duration.

## Integration notes

- Build with `npm ci`, then `npm run build`. Serve `apps/web/dist` via Runtime-owned nginx.
- API client uses same-origin `/api/v1`; production nginx must proxy that path without rewrite.
- Development Vite binds loopback and proxies `/api` to loopback API:8000 (production uses nginx).
- Canonical type commands: `npm run generate:api` (intentional update), `npm run check:api` (no mutation).
- Root QA Playwright owns its dependencies/config and tests. Stable locators:
  - top/empty button `サンプルを登録` (choose first when both exist);
  - registration dialog `サンプルアプリを登録`, fields `アプリ名`, `テンプレート`,
    `自動停止までの時間（秒）`, submit `登録`;
  - list button `<name> の詳細`, `sandbox-row` test ID plus `data-sandbox-id`,
    parent list item test ID `sandbox-card-<uuid>`;
  - detail `sandbox-detail`, badge `sandbox-status`, buttons exact `起動` / `停止` / `削除`;
  - deletion dialog `アプリを削除`, confirmation `削除する`, cancel `キャンセル`;
  - link `アプリを開く`, test IDs `runtime-banner`, `operation-status`, `expires-at`.
