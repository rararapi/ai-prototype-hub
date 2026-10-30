# ProtoHub

サンプルアプリを画面で登録し、起動して、ブラウザで試せるローカルの管理ツールです。
現在のv0は、信頼済みの固定テンプレート `hello-web` を扱うlocalhost専用MVPです。

![ProtoHubでできること。Hello WebをデモAとして登録し、起動中からReadyになるのを待ち、アプリを開いてHello ProtoHubのカウンターボタンを操作する。使った後はアプリごとに停止・起動・削除でき、デモAを止めてもデモBは動き続ける。](docs/images/protohub-concept.png)

*real-kindでの操作例を描いた生成イラストです。実画面・検証証跡ではありません。
mockでは実サンプルを開けません。*

- **名前を付けて登録する**：Hello Webテンプレートから、自分のサンプルを管理画面に追加します。
- **起動して実際に試す**：「起動」後、Readyになったら「アプリを開く」を押します。
  サンプルの `Hello ProtoHub` では、ボタンを押すとクリック回数が変わります。
- **アプリごとに管理する**：停止後も「起動」で再び使え、不要なら削除できます。
  一方の操作がもう一方に影響しない設計です。管理レコードはDBに保持します。

v0は単一開発者・信頼済みサンプルが対象です。対話しながらアプリを作る製品内AIは
[将来設計](docs/AI_DLC.md)として整理しています。開発者用のDevContainer・ハーネス・スキルは
このMVPの開発環境に含まれます。

実装・検証の到達点は [検証記録](docs/VALIDATION.md)、依存版は
[DEV_ENVIRONMENT](docs/DEV_ENVIRONMENT.md) を参照してください。

## エンジニア向け：構成と実行モード

![real-kindの通信を3段で示す。管理操作はBrowserからnginx、FastAPI、PostgreSQLへ進む。非同期処理は同じDBとWorker、ServiceAccountを使うKubernetes API制御へ進む。サンプル操作のHTTPはBrowser、Preview、Service、Podの順。下部にkindのnamespace別配置、jobと状態、別構成のmock/Composeを示す。](docs/images/protohub-architecture.png)

*構成図（生成イラスト）。[画像を開くと拡大できます](docs/images/protohub-architecture.png)。
3段の通信経路でHTTP・DBアクセス・Kubernetes制御を区別し、下部に配置とjob制御を示しています。
各段には同じコンポーネントを再掲しています。DBが複数ある構成ではありません。
構成の説明であり、実kind検証の合格を示すものではありません。*

図内の `127.0.0.1` はホストのbind先です。ブラウザでは管理画面の
`http://localhost:8080` とPreviewの `http://localhost:8081/apps/<UUID>/` を使います。
管理画面のOriginは設定済みの `localhost` と一致させてください。

real-kindでは、管理用コンポーネントもサンプルも専用kindクラスタ内で動きます。
`protohub-system` と `protohub-samples` は管理範囲を分けるnamespaceです。
悪性コードを隔離する境界としては扱いません。以下のportは既定値です。

| 経路・役割 | 実装 |
| --- | --- |
| 管理画面とAPI | `127.0.0.1:8080` → NodePort `30080` → nginx。Reactの静的ファイルを配信し、`/api/*` を内部のFastAPI `:8000` へ転送 |
| サンプル操作 | `127.0.0.1:8081/apps/<UUID>/` → NodePort `30081` → Preview `:8081` → 対象Service `:8080` → Pod `:8080`。PreviewはDBで現在の状態を確認し、固定ServiceへGET/HEADだけを転送 |
| 永続化 | PostgreSQL `:5432` の `sandboxes` / `operations` / `audit_events`。`operations` 自体がjob queue。DBはDeploymentとPVC `protohub-db` を使い、API/workerの再起動後も記録を保持 |
| 非同期処理 | APIは意図・generation・operationを同一transactionで登録し、`202` を返す。別プロセスのworkerが `FOR UPDATE SKIP LOCKED` でclaimし、実行・観測・reconcile・TTL停止を担当 |
| 遅延結果の抑止 | lease owner/token、有効期限、active operation、generation、desired stateを照合して更新。古いworkerの遅れた結果が新しい停止・削除を覆さない |
| Kubernetes制御 | WorkerのServiceAccount `protohub-worker` がサンプルnamespaceのDeployment/Serviceを操作し、Podは参照のみ。PodはDeployment配下のReplicaSet/controllerが生成・管理 |

APIとPreviewはKubernetesの管理tokenを持たず、APIとDBはホストへ直接公開しません。
PreviewはCookie/Authorizationを転送せず、任意のupstream URLを受け付けません。
API・worker・Previewは共通Pythonパッケージを使う別プロセスです。
Pod生成の標準的な制御関係は [KubernetesのDeployment解説](https://kubernetes.io/docs/concepts/workloads/controllers/deployment/) を参照してください。

実装の参照先は [配置マニフェスト](infra/kubernetes/stack.yaml.in)、[RBAC](infra/kubernetes/rbac.yaml)、
[job store](apps/server/src/protohub/persistence/jobs.py)、[RuntimeProvider実装](apps/server/src/protohub/runtime/kubernetes.py)、
[Preview](apps/server/src/protohub/preview/__init__.py) です。

| 操作・判定 | 実際の処理 |
| --- | --- |
| Ready | 現generationのDeployment rollout・Pod Ready・Serviceへの実 `GET /healthz` を確認。`202` やPod作成受付だけではReadyにしない |
| 停止 | Deploymentのreplicasを0にし、Podの停止を待つ。Deployment・Service・管理レコードは保持し、Previewを無効化 |
| 削除 | 対象のDeployment・Serviceを除去し、消失を確認。DBには墓標と監査記録を保持 |
| 自動停止 | 起動成功から60〜3600秒（既定900秒）のTTLをworkerが計測し、期限で停止要求を登録 |

| モード | 基盤 | サンプルの挙動 |
| --- | --- | --- |
| `mock` | Docker Compose | 状態遷移を模擬。実アプリを起動せず、preview URLも発行しない |
| `real-kind` | Docker上のkind | 実Podを起動し、Ready後にPreview経由でサンプルを操作する |

UIはReact/TypeScript/Vite、APIはFastAPI/Pydantic、DBはPostgreSQL/SQLAlchemy/Alembicです。
Redis、有料API、モデル接続は不要です。画像の生成方法・プロンプトは
[画像の説明](docs/images/README.md)、機能・API・状態の正本は [MVP仕様](docs/MVP_SPEC.md) を参照してください。

## 初回起動（WSL2）

WSL2 UbuntuのLinux filesystem上で作業してください。DockerのLinux daemon、Compose v2、
buildx、Git、Python 3.10以上、makeが必要です。real-kindにはkind、対応するkubectl、
**cgroup v2で動くDocker daemon**も必要です。`make doctor-kind` が事前に検査します。
Python/Nodeのアプリ依存は検証・ビルド用コンテナ内でuv/npmのlockfileからインストールします。
環境確認コマンドはOS設定変更や自動インストールを行いません。

この作業ブランチをWindows側からローカルに取り込む場合（pushは不要）:

```bash
mkdir -p ~/src
git clone --no-hardlinks --branch codex/protohub-local-mvp \
  /mnt/c/Git/ai-prototype-hub ~/src/ai-prototype-hub
cd ~/src/ai-prototype-hub
python3 harness/doctor.py --mode compose
make doctor
make up-mock
```

管理画面は [http://localhost:8080](http://localhost:8080) です。
mockでは画面に「Mock runtime — 実アプリは起動しません」を常時表示し、preview URLを発行しません。
登録・非同期操作・DB永続化を開発するモードです。

実際のサンプルを動かす場合は同じポートを使うmockを先に停止します:

```bash
make down
make doctor-kind
make up-real
```

real-kindは専用kindクラスタ`protohub-local`へweb/API/worker/preview/DBを配置します。
管理画面で登録→起動→Ready→「アプリを開く」の順に操作してください。
previewは `http://localhost:8081/apps/<UUID>/` です。サンプルのボタンを操作できます。
起動成功は現在generationのPod readiness、Deployment rollout、実HTTP応答から判定します。

Docker/WSLの起動・連携設定、ツール導入は [WSL_SETUP](docs/WSL_SETUP.md) を参照してください。
未知のcluster/context、既存ポート、所有記録のない資源を自動で再利用・削除しません。

## 日常の起動・停止

```bash
cd ~/src/ai-prototype-hub
make up-mock                 # Composeによる明示的mock
# または make up-real        # kindによる実起動。mockへフォールバックしない
make logs
make down                    # 自分のstackを停止。DB volumeとkind clusterを保持
```

同じモードを再起動すれば管理レコードを再利用します。停止はアプリの実行を止め、削除はそのアプリの
Pod/Deployment/Serviceとpreview経路を除去します。削除済みレコードは墓標としてDBに保持します。
TTLは起動成功時から60〜3600秒で計測し、期限で停止します。DBは削除しません。

ポート・資源名を分ける場合は、起動と以後の操作で同じ環境変数を使ってください:

```bash
export PROTOHUB_MODE=real-kind
export PROTOHUB_CLUSTER_NAME=protohub-personal
export PROTOHUB_CONSOLE_PORT=18080
export PROTOHUB_PREVIEW_PORT=18081
make up-real
make down
```

mockの資源名には`COMPOSE_PROJECT_NAME=protohub-personal`を使います。
全削除が必要なときだけ、表示対象と完全一致する名前を明示します（ローカルDBも失われます）:

```bash
PROTOHUB_MODE=real-kind PROTOHUB_CLUSTER_NAME=protohub-personal \
  PROTOHUB_RESET_CONFIRM=protohub-personal make reset-local
```

`reset-local`は通常の停止に使いません。全体pruneや他のcluster/volume削除は行いません。

## 開発と検証

各開発者のローカルPCでツール・依存・検査手順を揃える標準環境としてDevContainerを使います。
WSLのLinux側cloneをVS Codeで開き、
**Dev Containers: Reopen in Container** を実行できます。
Python/Node/uvとlockfileの依存を専用volumeへ用意し、non-rootで `make check-dev` を実行します。
初回設定・停止・再構築は [Dev Container手順](docs/DEV_CONTAINER.md) を参照してください。
アプリの `make up-mock` / `make up-real` と必須の `make verify` は、通常のWSLターミナルから実行します。
開発コンテナにはDocker socketやkubeconfigを渡しません。
現在の実測はWindows + WSL2 / Linux amd64です。他PC・macOS/Linux・ARMの確認状況と、
Docker/cgroup等のホストに残る条件も手順書へ記録しています。

この開発ハーネスには、タスクの目的・変更許可パス・担当・契約判断・修正予算を記録する
workflowと、実際の検査runnerを含めます。範囲外変更、既存変更の上書き、古いPASSの流用、
検証中のソース変更を検出し、必要な検査・独立レビューが揃わない完了を拒否します。
通常の工程ごとに承認を増やさず、OS・権限・課金・公開等の境界では既存の承認を守ります。
これは開発支援であり、OS sandboxの代替ではありません。

[開発ワークフロー](docs/DEVELOPMENT_WORKFLOW.md) と [導入スキル5件](docs/SKILLS.md) を参照してください。
スキルはプロジェクト内 `.agents/skills/` に配置し、固定した出所・ライセンス・hashを検査します。

```bash
# 以下はWSLホストの make check と組み合わせる例
make skills-check
python3 harness/workflow.py start --id ui-change \
  --objective '状態表示を改善する' --allow apps/web/ \
  --required-gate source --required-gate contracts --required-gate unit \
  --required-gate build --required-gate public-hygiene
WORKFLOW_ID=ui-change make workflow-check
```

Dev Container内のworkflowでは `source-host` / `contracts-host` / `unit-host` /
`build-host` と `harness-self` / `public-hygiene` をrequired gateへ指定し、
`make check-dev` の証跡を添付します。gate名はrunnerの実際のIDに合わせてください。

AI-DLCの原則はこの開発工程に採用しています。将来の対話型アプリ制作の段階・状態・成果物・
人の判断境界は [AI_DLC](docs/AI_DLC.md) に整理し、製品内のAI実行は次フェーズとして扱います。

```bash
make check          # lint/type/unit/contract/build/public-hygiene + harness自己検査
make integration    # 専用PostgreSQL fixtureでmigration/queue/並行性/復旧
make e2e            # 専用kind、実HTTP、Playwright、TTL、worker復旧、部分失敗
make security       # 別の専用kindで実RBAC allow/deny、Pod、Host/Origin/preview
make verify         # 上記の必須full gate。CIと同じ入口
```

結果は `.harness/reports/<run_id>/report.json` とgate別log/JUnitに保存します。
不足環境はBLOCKED、検査失敗はFAIL、必須skip/0 testsは非合格です。E2Eとsecurityは独立fixtureを
作成・検証・回収し、普段のstack選択を変更しません。中断時は猶予付きcleanupを行い、強制終了で
残った場合は同runの`fixture.json`と所有記録を確認して対象を限定したresetを行ってください。

Dockerを使わない補助検査もあります。これは実起動の合格を意味しません:

```bash
uv sync --project apps/server --locked
(cd apps/web && npm ci)
python3 harness/run.py --group portable
```

正本は [MVP仕様](docs/MVP_SPEC.md)、[OpenAPI](contracts/openapi.yaml)、
[契約変更記録](contracts/DECISIONS.md) です。API変更時は親担当が正本をレビューし、
`contracts/build_contract.py` と `npm --prefix apps/web run generate:api` で意図的に更新します。
通常検証は正本を書き換えず、実装OpenAPIとフロント型の差分を検出します。
分担・引継ぎは [PARALLEL_PLAN](docs/PARALLEL_PLAN.md)、`harness/handoffs/` を参照してください。

## 初期版の制約

- 単一開発者・localhost・固定`hello-web`テンプレートだけを対象とします。
- 悪性コード隔離、本番認証、インターネット公開には未対応です。local-dev principalは認証の代替ではありません。
- 任意Git/image/Dockerfile/command/env、ブラウザ内AI、外部LLMキーは受け付けません。
- kindの通常コンテナを安全な任意コードsandboxとして扱えません。対応CNIと実通信検証を伴うネットワーク隔離も未対応です。
- localhostのポートを分けてもCookieは分離されません。サンプルは認証Cookie・秘密を持ちません。
- AKS/Kata、OIDC/Entra ID、LiteLLM等は将来の差し替え対象です。今回クラウド資源を作成しません。
- リポジトリのライセンスは未選定です。依存パッケージのライセンスはそれぞれの配布元に従います。
