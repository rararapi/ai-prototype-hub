# ProtoHub v0 — 実装仕様

## 1. スコープとユーザー価値

固定の信頼済みWebアプリを管理画面から起動し、URLで試用し、停止・削除するローカルMVPを作る。ユーザーはKubernetesコマンドを知らなくてもアプリのライフサイクルを操作できる。

**v0は単一開発者のlocalhost専用**。`Sandbox` はプロダクト上の管理単位の名称であり、kindの通常コンテナで悪性コードの安全性を保証する意味ではない。

対象外: 任意Git import、Dockerfile upload、任意イメージ/コマンド/env、ブラウザIDE、内部AIエージェント、WebSocketアプリ、認証付きユーザーアプリ、課金、実組織SSO、実LLM呼び出し、クラウド作成、多組織SaaS。

## 2. アーキテクチャ

UI → API → PostgreSQLの操作キュー → Worker → RuntimeProvider → Kubernetes。

- API: 検証、管理レコード、操作要求、状態参照。Kubernetesの管理資格情報を持たない。
- Worker: DB jobのclaim、実行、観測、reconcile、TTL処理。APIとは別プロセス。
- RuntimeProvider: mockとKubernetesを差し替える。mockは実Podを起動しないことをUI/APIに明示。
- Preview: UUIDから内部で登録されたサンプルServiceへのHTTP経路を作る。利用者がupstream URLを指定できない。
- DB: 管理レコード、job、lease、generation、限定的な監査イベントを永続化する。

初期ディレクトリ案:

| パス | 内容 |
|---|---|
| `apps/web/` | React + Vite UI、npm manifest/lock、component tests |
| `apps/server/src/protohub/api/` | FastAPIのHTTP層 |
| `apps/server/src/protohub/domain/` | 親が管理する共通DTO/enum/provider interface |
| `apps/server/src/protohub/persistence/` | DB model/repository/job store |
| `apps/server/src/protohub/worker/` | 別プロセスのjob/reconcile/TTL |
| `apps/server/src/protohub/runtime/` | mock/Kubernetes adapter |
| `apps/server/src/protohub/preview/` | 信頼済みテンプレート向けHTTP経路 |
| `apps/server/tests/{api,worker,runtime}/` | Pythonテスト |
| `apps/server/migrations/` | Alembic |
| `apps/server/pyproject.toml`, `apps/server/uv.lock` | 共有Python依存、親が所有 |
| `contracts/` | OpenAPI、JSON examples、契約の変更記録 |
| `examples/hello-web/` | 非rootで動く固定サンプル、Dockerfile |
| `infra/compose/`, `infra/kind/`, `infra/kubernetes/` | 開発/実起動構成 |
| `scripts/`, `tests/e2e/`, `tests/integration/` | 起動・検証スクリプト |

APIとworkerを同じPythonプロジェクトに置くのは共通型・依存の重複を減らすため。コンテナとServiceAccount、起動コマンドは分離する。

## 3. モード

### mock

Docker ComposeでUI/API/worker/PostgreSQLを起動し、RuntimeProviderはmockを使う。画面上部に「Mock runtime — 実アプリは起動しません」を常時表示。mockのreadyは実HTTP到達性の成功に数えない。preview_urlはnullとし、偽のURLを生成しない。

### real-kind

kind内にUI/API/worker/PostgreSQL/preview経路を配置する。Workerはin-cluster configと専用ServiceAccountを使用。ホスト上のkubeconfigをアプリコンテナへ配布しない。

リソースのnamespaceは親が固定したcontrol-plane用とサンプル用に分ける。サンプル操作のworker RBACはサンプルnamespaceだけを対象とする。namespace作成、RBAC作成、node操作はユーザー側の開発setup処理が担い、workerには渡さない。

アプリの登録・起動操作ではDockerイメージをビルドしない。setupが固定サンプルをビルドしkindへloadする。管理APIは `template_id=hello-web` のみを許可し、デプロイするimage/versionは基盤側設定で固定する。

## 4. API契約

API prefixは `/api/v1`。JSONはsnake_case。日時はUTCのRFC3339、IDはUUID。親が `contracts/openapi.yaml` とexamplesを先に作る。

| Method / path | 成功レスポンス | 目的 |
|---|---|---|
| `GET /healthz` | 200 | プロセス生存確認 |
| `GET /readyz` | 200、準備不可503 | DBなど依存の準備状態 |
| `GET /api/v1/system` | 200 | runtime_mode、auth_mode、制約情報 |
| `GET /api/v1/templates` | 200 | 固定テンプレート一覧 |
| `POST /api/v1/sandboxes` | 201 Sandbox | 登録のみ、初期状態stopped |
| `GET /api/v1/sandboxes` | 200 items | 削除済みを除く一覧 |
| `GET /api/v1/sandboxes/{id}` | 200 Sandbox | 詳細、状態、URL、エラー概要 |
| `POST /api/v1/sandboxes/{id}/start` | 202 Operation | 起動要求 |
| `POST /api/v1/sandboxes/{id}/stop` | 202 Operation | 停止要求 |
| `DELETE /api/v1/sandboxes/{id}` | 202 Operation | 実行リソースを削除し墓標を保持 |
| `GET /api/v1/operations/{id}` | 200 Operation | 非同期操作の進捗 |

作成入力: `name` (1–64文字)、`template_id`、`ttl_seconds` (60–3600、既定900)。未知フィールドは422。名前をshell command、Kubernetes resource名、URL upstreamへそのまま埋め込まない。

Sandboxフィールド: `id`, `name`, `template_id`, `desired_state`, `status`, `generation`, `active_operation_id`, `preview_url`, `expires_at`, `created_at`, `updated_at`, `error`。

Operationフィールド: `id`, `sandbox_id`, `action`, `generation`, `status`, `attempt_count`, `created_at`, `updated_at`, `error`。

`error` はnullまたは `{code, message}`。トレース・接続文字列・秘密値をレスポンスへ出さない。HTTPエラーは `{error: {code, message, request_id}}` に統一する。

APIから観測していない成功を返さない。202は受付であり起動完了ではない。UIはoperationとSandbox状態をpollする。404/422/409/503なども契約例に含める。

## 5. 状態と並行性

- desired_state: `running | stopped | deleted`
- status: `stopped | starting | running | stopping | deleting | deleted | failed`
- operation status: `queued | running | succeeded | failed | superseded`

real-kindの `running` はKubernetes readinessとサンプル到達性を観測してから。Pod作成APIの成功だけではrunningにしない。mockでは模擬状態であることを常に示し、実起動の成功とは区別する。

各Sandboxに単調増加generationを持つ。変更要求とjob登録は同じDB transaction内。worker結果を保存する時はgeneration/desired_stateを比較し、古い操作が新しい停止や削除を覆さないようにする。

- 同じ起動要求の二重送信は、既存の有効operationを返すか、安全なno-op operationにする。契約で一意に決め、テストする。
- 既に停止/削除された対象への同じ操作は冪等。削除済みへのstartは409。
- 起動中のstop/deleteは新しいgenerationを採番する。遅れた起動処理の副作用はreconcileで収束させる。
- job claimは `FOR UPDATE SKIP LOCKED` 等で多workerに対応し、期限付きleaseを使う。外部APIの待機中に長いDB transactionを保持しない。
- worker異常停止後はlease期限を超えたjobを再取得する。操作はat-least-once前提、runtime資源名はSandbox UUIDから安定生成する。
- jobは `lease_owner` と取得ごとに更新される `lease_token`（または単調増加claim番号）を持つ。heartbeat/成功/失敗確定は、現在のtoken・有効期限・Sandbox generationを条件にatomic更新する。同じgenerationでも古いlease holderは確定できない。leaseを失ったworkerは後続の副作用を止め、既に生じた副作用はreconcileで収束させる。
- retryは最大3回、backoffとtimeoutを明示。Kubernetesの永続的な拒否と一時エラーを分ける。
- TTLは起動成功時から計測し、期限で自動停止する。管理レコードを消さない。自動でDB volumeを消さない。
- 部分失敗はfailed＋原因概要を記録し、所有ラベルの資源だけreconcile/rollbackする。他のアプリを巻き込まない。

RuntimeProvider契約は `ensure_started`, `observe`, `ensure_stopped`, `ensure_deleted` とし、再実行可能なAPIにする。Kubernetes例外をそのままdomain/UIへ漏らさない。

BackendとRuntimeが共有する `JobStore` / `UnitOfWork` の最小契約も並行実装前に固定する。少なくともclaim、heartbeat、complete/fail/supersede、lease回収、transaction境界、token不一致時の戻り値を決める。具体SQLはBackend、呼出側の制御はRuntimeが担当する。

## 6. UI

最小画面は一覧・登録・詳細。状態badge、テンプレート、TTL、更新時刻、操作中表示、エラー概要、起動/停止/削除、Ready時の「アプリを開く」を備える。

- loading / empty / error / retryを用意。多重クリック抑止だけに依存せずAPIも冪等にする。
- 削除は対象名を表示した確認。停止と削除の差を説明。
- mockかrealかを常に見せる。URLはreadyのときだけ有効。
- 実装時点のテストデータ以外の組織名・個人名・メール・内部URLを表示しない。

## 7. HTTP公開と認証

ホストへのport bindは127.0.0.1のみ。既定の候補はconsole=8080、preview=8081。APIとDBのportをホストへ直接公開しない。既存のポートを勝手に奪わない。

v0の認証は明示的なlocal-dev principal。これは本番認証ではない。APIのCORS/Originを正確なconsole originに限定し、変更系はJSONとカスタムヘッダを要求して、ブラウザからの単純なcross-origin操作を拒否する。これはSSOや認可の代用ではない。

consoleとpreviewのHostも設定したlocalhost/127.0.0.1のみに限定する。未知Hostを拒否し、任意の `X-Forwarded-Host` を信頼しない。クラスタ内部のprobe/通信に必要なHostは別経路か明示allowlistで扱い、ワイルドカードで全許可しない。

previewは固定サンプル向けのHTTP GET/HEADのみでよい。upstreamはDBのIDから既定namespace/Service名へ決定し、任意URLを受け付けない。Cookie/Authorizationを転送しない。redirect/host/pathの扱いを検証する。

**localhostのportを分けてもCookieの分離にはならない**。v0は認証Cookieや秘密を持たない信頼済みサンプル限定とし、任意アプリやSSOを導入する前に別ホスト名、host-only cookie、cross-origin境界を設計し直す。

## 8. コンテナ・権限の最低基準

サンプルPodはnon-root、allowPrivilegeEscalation=false、capabilities drop ALL、readOnlyRootFilesystem、限定的な一時領域、CPU/memory requests/limits、automountServiceAccountToken=false。

APIとサンプルにはDocker socket、kubeconfig、hostPath、host networking、privilegedを与えない。Workerは対象namespaceで必要なDeployment/Service/Pod参照などだけを操作し、Secret読取やRBAC作成は与えない。不要なPod exec権限も与えない。

NetworkPolicyを置くだけで通信隔離が実装されたと言わない。対応CNIの導入と実通信のallow/deny検証は別条件。v0は信頼済みサンプル限定であり、敵対的ワークロード間の分離は未対応と文書化する。

## 9. 後続フェーズ

AKS/Kata実検証、OIDC/Entra ID、組織ネットワーク限定、LiteLLM、永続ワークスペース、エージェント接続、任意コードのbuild/egress/isolationは後続。v0を完成させるために実キーや組織環境を要求しない。


## 10. 開発ログインと共通キー（2026-11-01の追加依頼）

固定local-dev principalをメール入力による開発セッションへ置き換える。
新規アプリはログイン中の所有者へ結び付け、一覧/詳細/操作履歴は所有者か明示的な共有先のみ。
共有先は閲覧のみ、実行操作と共有編集は所有者のみ。所有者不明の既存レコードは保持して非表示。
Bearerセッションは24時間有効、DBはハッシュのみ、ブラウザはsessionStorage、Cookie未使用。
`PROTOHUB_ENVIRONMENT=production` では開発ログインと保護APIを無効にする。
これはメールの所有確認や本番認証を提供しない。

`PROTOHUB_LLM_API_KEY` はAPIサーバー限定の共通秘密設定として全アプリの解決に使う。
アプリ別キー設定は将来の拡張とし、現時点で実LLM通信やサンプルへのキー注入は追加しない。
console/previewのOrigin・Cookie・ヘッダ境界と既存データの扱いは
[DEVELOPMENT_AUTH.md](DEVELOPMENT_AUTH.md) を正本とする。

## 11. Gemini連携と既存GCPへの配備（2026-11-07の追加依頼）

ユーザーの追加依頼により、実Gemini連携、mainへの統合、既存GCPへの更新を行う。
v0の固定サンプルの実行境界は維持し、別ドメインの版付き画面案を生成・保存する。
新規仕様は [GEMINI_CREATION.md](GEMINI_CREATION.md) を正本とする。
静的Pagesデモは実LLMへ接続しない。生成コードの実行や新しい任意コンテナは追加しない。
