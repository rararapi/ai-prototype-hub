# DevContainerで開発する

ProtoHubのDevContainerは、Python・Node・uvと開発用依存を揃えるための環境です。
編集、lint、型検査、unit、契約検査、package/frontend buildをコンテナ内で進められます。
アプリのCompose/kind起動と、必須の実環境検証はWSLホストから実行します。

設定は [.devcontainer/](../.devcontainer/) が正本です。DevContainerはアプリのAPI/workerや
サンプルPodとは別の開発環境であり、既存のプロセス・ServiceAccountの役割を変更しません。
一般的な仕組みは [VS Code公式ガイド](https://code.visualstudio.com/docs/devcontainers/containers)
を参照してください。

## 揃えるものと、ホストに残すもの

| 場所 | 担当 |
| --- | --- |
| DevContainer | Python 3.11.18、Node.js 24.18.0、uv 0.11.19、Git/make等の開発ツール、lockfileからの開発依存 |
| WSLホスト | ソースのLinux filesystem、既存Docker daemonへの接続、Compose/buildx、実起動用のkind/kubectl、ホスト側のdoctor/起動/検証 |
| アプリのCompose/kind | API、worker、DB、web、previewと、信頼済みサンプルの実行 |

バージョンは既存の [DEV_ENVIRONMENT.md](DEV_ENVIRONMENT.md) と整合させます。
Pythonは `apps/server/uv.lock`、Node依存は `apps/web/package-lock.json` と
`tests/e2e/package-lock.json` を使い、`uv sync --locked` / `npm ci` で導入します。
DevContainerを開いただけでlockfileを更新しません。

開発者のターミナルはnon-rootユーザーで動かします。Linux上のUID/GID同期を使い、
ソースのbind mountにroot所有の編集ファイルを増やさない構成です。
WSL側も通常のnon-rootユーザーで開き、そのユーザーがcloneへ書き込めることが前提です。
rootから開いたcloneや他ユーザー所有のソースを、UID同期で修復する仕組みではありません。
entrypointが所有者を調整する対象は、下記の依存volume3個だけです。
これはコンテナ内ユーザーの調整で、ホストユーザーのグループやsudo権限を変える操作ではありません。
[公式のnon-root/UID同期の説明](https://code.visualstudio.com/remote/advancedcontainers/add-nonroot-user)

workspaceは `/workspaces/protohub`、ターミナルのユーザーは `developer` です。
Python環境はproject内の既存 `.venv` を使わず、`UV_PROJECT_ENVIRONMENT=/opt/protohub-venv`
が指す専用volumeへ導入します。Node依存もソースとは別のvolumeに置きます。

| container内の依存path | volume名 |
| --- | --- |
| `/opt/protohub-venv` | `protohub-${devcontainerId}-venv` |
| `/workspaces/protohub/apps/web/node_modules` | `protohub-${devcontainerId}-web-node-modules` |
| `/workspaces/protohub/tests/e2e/node_modules` | `protohub-${devcontainerId}-e2e-node-modules` |

ソースは同じWSL cloneを編集し、Linux用の依存をWindows用の生成物と混ぜません。
新規作成・再作成時のhelperはuvとnpmのlockfileを同期し、`make skills-check` を実行します。
既存コンテナを再開するたびには実行しないため、lockfile変更後は明示的に再同期します。
ホスト側に作るのはNode依存のmount先となる空のdirectoryだけで、Windows側の依存内容を
コピーしません。依存volumeは通常の停止・再構築で消さず、必要なlockfileとの差分を同期します。
[named volumeの公式説明](https://code.visualstudio.com/remote/advancedcontainers/improve-performance#_use-a-targeted-named-volume)

## 最初に開く

既にあるWSLのLinux側cloneを再利用してください。推奨の場所は
`~/src/ai-prototype-hub` です。`/mnt/c` やOneDrive配下からの常用は避けます。
WSLのLinux filesystemはファイルI/Oと権限の互換性にも適しています。
[VS CodeのWSL配置ガイド](https://code.visualstudio.com/remote/advancedcontainers/improve-performance#_store-your-source-code-in-the-wsl-2-filesystem-on-windows)

Windows側にしか今回の作業ブランチがない場合は、[READMEのローカルclone手順](../README.md#初回起動wsl2)
でLinux側へ取り込みます。既存cloneや未commitの作業を上書きしません。

1. WSL側で既存Dockerへ接続できることを確認します。Dockerの導入・再起動やWSL設定の変更は、必要な場合に別途行う環境作業です。
2. VS CodeとWSL/Dev Containers拡張を使い、WSL側の作業フォルダを開きます。
3. コマンドパレットから **Dev Containers: Reopen in Container** を選びます。
4. image buildと依存導入が終わるのを待ち、VS Codeの新しいターミナルが開発コンテナ内を指すことを確認します。

WSLから開く例:

```bash
cd ~/src/ai-prototype-hub
code .
```

WSLから開いたフォルダをDevContainerで開き直す操作は
[VS Code公式手順](https://code.visualstudio.com/docs/devcontainers/containers#_open-a-wsl-2-folder-in-a-container-on-windows)
に沿います。初回はimageと依存のダウンロードが必要です。取得が失敗した場合はその段階を
未完として扱い、依存を省略して成功表示にしません。

## コンテナ内で普段使うコマンド

コンテナのターミナルで、リポジトリrootから実行します。

```bash
python3 --version
node --version
uv --version
id -u
make skills-check
make check-dev
```

`make check-dev` は、開発コンテナ内のツールでharness自己検査、public-hygiene、スキル整合性、
lint/型検査、unit、OpenAPI/生成型の一致、Python package/frontend buildを実行する
明示的な検証入口です。各検査は既存のhost executorを使います。
この結果は開発ツールとコードの検証であり、Docker image build、実PostgreSQL、
実Pod/HTTP、ブラウザE2E、live RBACの合格とは分けて記録します。

依存lockの変更を取り込んだ後は、コンテナ内で再同期できます。

```bash
bash .devcontainer/post-create.sh
make check-dev
```

依存を更新する開発作業は、lockfileを含む別の意図的な変更として扱います。
無関係な依存追加やグローバルinstallで検査を通さないでください。
開発の目的・scope・担当・証跡の扱いは [DEVELOPMENT_WORKFLOW.md](DEVELOPMENT_WORKFLOW.md)
を継続して使い、スキルは [.agents/skills/](../.agents/skills/) から必要なものだけを読みます。

## アプリ起動と必須検証はWSLホストから

VS CodeのDevContainer内ターミナルとは別に、通常のWSL Bashを開いて実行します。
どちらも同じLinux側cloneを指すようにしてください。

```bash
# WSLホスト側のターミナル
cd ~/src/ai-prototype-hub
make doctor
make up-mock
# 管理画面: http://localhost:8080
make logs
make down
```

実起動と必須full acceptanceは、ホスト側で次を使います。

```bash
make doctor-kind
make up-real
make check
make integration
make e2e
make security
make verify
make down
```

mockとreal-kindで同じポートを同時に使いません。先のstackを `make down` で停止してから
切り替えます。real-kindのpreviewは `http://localhost:8081/apps/<UUID>/` です。
DB/APIは引き続きホストへ直接公開せず、workerはkind内の専用ServiceAccountを使います。

`make check` と `make verify` の意味や必須項目は変更しません。DevContainer内でDockerを
使えないことを理由にmockへ切り替えたり、必須gateを `check-dev` に置き換えたりしません。
未実行・不足環境はそのままNOT_RUN/BLOCKEDとして残します。

## なぜDocker操作もコンテナ内にまとめないのか

既定の開発コンテナにはDocker socket、ホストのkubeconfig、privileged、host networkを
渡しません。Docker-in-Dockerも起動しません。開発支援プロセスへ、ホストの他のcontainerや
volumeを管理する能力を追加しないためです。Docker socketを共有してホストdaemonを操作する
方式自体はありますが、それはツール配置だけでなく、アクセス範囲の変更になります。
[VS Codeの方式説明](https://code.visualstudio.com/remote/advancedcontainers/use-docker-kubernetes)、
[Docker daemonの権限境界](https://docs.docker.com/engine/security/#docker-daemon-attack-surface)

この分担なら、通常の編集・コード検査はDevContainerに揃え、実行資源の作成・削除は
既存のホスト側launcherと所有検証を通せます。将来Docker制御付きprofileが必要になっても、
対象daemon、mount、資格情報、cleanupの影響を具体化して明示的な許可を得る別作業にします。
エラー時にsocketを追加mountしたり、daemonをTCP公開したりする自動fallbackはありません。

DevContainerは悪性エージェントを安全に閉じ込める保証ではありません。ソースのbind mountは
編集可能で、コンテナ内で動かすコードや拡張の信頼は必要です。利用中のCodex等のsandboxと
承認ルールを無効化する設定も追加しません。

## 停止・再開・再構築

DevContainerの作業を終えるときは、VS Codeで **Dev Containers: Reopen Folder Locally** を
選ぶか、その開発コンテナのウィンドウを閉じます。`shutdownAction: stopContainer` により
開発コンテナを停止し、依存volumeを保持します。設定値の意味は
[Dev Containersの公式仕様](https://github.com/devcontainers/spec/blob/main/docs/specs/devcontainerjson-reference.md)
を参照してください。

次回は同じWSLフォルダを **Reopen in Container** で開きます。DockerfileやDevContainer設定を
変更した場合は、**Dev Containers: Rebuild Container** で開発環境を再構築します。
ソース・lockfileはbind mountの作業フォルダに残り、named volumeの依存も通常は保持されます。

DevContainerを停止しても、WSLホストから起動済みのアプリstackは別に存在します。
アプリを止める場合はWSL側の `make down` を実行します。逆に `make down` は開発コンテナの
削除コマンドではありません。依存volumeの削除、DBの削除、全体pruneを日常の停止手順に含めません。

## 困ったとき

| 状況 | 確認すること |
| --- | --- |
| DevContainer内のDocker/アプリ起動コマンドが動かない | 既定の役割分担。通常のWSL Bashで実行する。socketや資格情報を足さない |
| Python/Node依存が見つからない | 作成時の依存導入logとlockfileを確認し、コンテナ内で明示的に同期する |
| 編集でpermission deniedになる | WSLのLinux側cloneか、terminalがnon-rootか、UID/GID同期と対象依存volumeの所有を確認する。ホストの権限を一括変更しない |
| rebuild後も古い依存に見える | named volumeは保持されるため、まずlockfileから再同期する。volumeの一括削除はしない |
| `make check-dev` はPASSだが `make verify` がBLOCKED | それぞれ検査範囲が異なる。WSLホストのdoctorと今回runの不足理由を確認する |
| real-kindがcgroup v1で拒否される | DevContainerのimage変更では解消しない。ホスト側のDocker/WSL対応を別途判断する |

コンテナはホストのLinux kernel/cgroup環境を使います。開発imageを揃えても、ホストdaemonの
cgroup版は切り替わりません。今回確認したDocker daemonはcgroup v1で、採用したkind/nodeの
実検証は引き続きBLOCKEDです。変更にはホスト側の更新・設定・再起動が関係するため、
この構成追加では実行しません。詳細は [WSL_SETUP.md](WSL_SETUP.md#この実装の追加前提-cgroup-v2)
と [検証記録](VALIDATION.md) を参照してください。
[Dockerのcgroup v2要件](https://docs.docker.com/engine/containers/runmetrics/#running-docker-on-cgroup-v2)

## この構成自体の検証状況

2026-10-30、既存のWSL2 Ubuntu / Dockerで、公式Dev Container CLI 0.90.0を使って実検証しました。
設定の初回実装commitは `6d23869`。この後のCI事前検査・CLI固定と文書修正を含む最終sourceと
再検査reportの対応は、ignoredな `.harness/reports/devcontainer-20261030/final-evidence.json` に記録します。

| 実行・確認 | 結果 |
| --- | --- |
| CLI `read-configuration` / `up` | PASS。実際にimageをbuildし、3つの空volumeへuv/npm依存を導入 |
| CLI `exec` でUID・権限・版・書き込み検査 | PASS。UID/GID 1000、実効capabilities 0、no-new-privileges、ソース/依存volumeへの書き込み |
| Docker socket / Docker CLI / kubeconfig | いずれも未付与。inspectでもworkspace以外のhost bind・privileged・host network・公開portなし |
| コンテナ内 `make check-dev` | PASS。初回report `20261030T013845Z-ea846249`、必須skipなし |
| 停止→CLI `up` | PASS。同じcontainerとvolumeを再開 |
| その検証containerだけ削除→CLI `up` | PASS。別containerを作り、同じ3volumeとfixtureの保持を確認、lockfile同期も再実行 |
| UID移行中断の再現 | PASS。volume rootの所有が正しくても、root所有の子を再開時に修復 |
| volume内symlinkの対象 | PASS。対象の所有を変更せず、linkだけを修復 |
| 必須volumeなしでimage起動 | PASS。所有変更前に起動を拒否 |
| 独立レビュー | CIのbuildx不足時の成功扱い・浮動CLI版を指摘し、事前検査とCLI 0.90.0固定で修正 |
| VS Codeの画面で対話的Reopen / GitHub CIの実行 | NOT_RUN。CLI実測と別に扱う。push/PRは行っていない |
| real-kind / 実Pod・HTTP / Playwright / live RBAC | 引き続きBLOCKED。ホストのcgroup v1が原因 |

CLIのstdout/stderr、権限probe、固定volume/所有containerのreceipt、再作成記録は
`.harness/reports/devcontainer-20261030/` に集約します。通常のharness gateは各run IDの
`report.json` とlog/JUnitを使います。これらはローカル証跡で、リポジトリへcommitしません。
OS設定・ユーザーグループ・Dockerサービスは変更していません。
