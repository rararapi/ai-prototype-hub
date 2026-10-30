# WSL2 / Docker ローカル環境

## 標準

Windows + WSL2 Ubuntuを想定し、Codex・Git・Make・Docker CLIはWSL内のBashから操作する。ソースはLinux側 `/home/<user>/src/ai-prototype-hub` へ。`/mnt/c` やOneDrive配下を作業ディレクトリにしない。

WSLのLinux filesystemを使うのはbind mountのI/Oと変更通知を安定させるため。Windowsブラウザからはlocalhostで画面を開く構成を目指す。

## Dockerは既存構成を確認して1種類を使う

### A. Docker Desktop + WSL integration（新規導入時の標準候補）

ユーザーがWindows側でDocker Desktopを起動し、WSL2 backendと対象UbuntuのWSL Integrationを有効にする。WSL内で `docker info` が通れば、そのdaemonを再利用する。

Docker DesktopとWSL内Docker Engineを二重に導入・起動しない。既にEngineがある場合、Codexが勝手にuninstallして切り替えてはいけない。企業での利用条件・契約は組織のルールに従う。

### B. WSL内Docker Engineを既に使用している場合

既存Engine + Compose v2を利用してよい。必要なときだけ、ユーザーが確認したうえでDocker serviceを起動する。systemdの有効化や再起動、`wsl --shutdown` は他作業へ影響するためCodexが無断で実行しない。

Docker groupは強い権限を持つ。`chmod 666 /var/run/docker.sock` や無認証TCP daemonを解決策にしない。アプリへDocker socketを渡さない。

## 最初の確認

Windows PowerShell（確認のみ）:

```powershell
wsl --version
wsl --list --verbose
```

WSL Bash（確認のみ）:

```bash
pwd -P
uname -r
git --version
python3 --version
make --version
docker context show
docker version
docker info --format '{{.OSType}} {{.Architecture}}'
docker compose version
docker buildx version
kind version
kubectl version --client
```

Compose開発ではkind/kubectl不在でも進められるが、real-kind検証には必要。`harness/doctor.py` は不足を報告し、自動installしない。

```bash
python3 harness/doctor.py --mode compose
python3 harness/doctor.py --mode kind
```

Docker権限、企業VPN、proxy、firewallの制約があるときは原因を分ける。WSLからDockerへ接続できない問題を、公開bindやTLS無効化で回避しない。

## リポジトリ

まだcloneしていない場合にWSLのLinux側の作業ディレクトリで実行する:

```bash
git clone https://github.com/rararapi/ai-prototype-hub.git
cd ai-prototype-hub
```

既にある場合はcloneし直さず、remoteとdirty状態を確認。パックの `repo-overlay/` はCodexに差分統合させる。既存ファイルへの無条件コピーはしない。

改行はLF。シェルスクリプトはBashで、`.gitattributes` と構文検査を用意する。Windows側から同時に別Git操作をしない。

## 2つの起動モード（Codex実装後）

| モード | 起動入口 | 目的 | 合格の意味 |
|---|---|---|---|
| mock | `make up-mock` | UI/API/DBを速く開発 | 実サンプル起動の証拠ではない |
| real-kind | `make up-real` | Docker上のKubernetesで実起動 | 実Pod/HTTP/停止/削除を検証する |

推奨のhost portはconsole=8080、preview=8081。host側bindは127.0.0.1。DB/API portをhostに直接公開しない。portは環境変数で変更でき、占有中は診断する。既存プロセスをkillしない。

Windowsブラウザで `http://localhost:8080` を開き、WSLからもHTTP応答を確認する。Windows側への到達を自動化できない場合は、その1点を手動未確認として区別する。

## kindの配置

### この実装の追加前提: cgroup v2

採用したkind nodeはKubernetes1.37です。Docker daemonのcgroup版を確認します:

```bash
docker info --format '{{.CgroupVersion}}'
make doctor-kind
```

real-kindには結果が`2`であることが必要です。今回のDocker25.0.3環境は`1`で、kubeletが
起動を拒否したため実Pod/E2E/live RBACはBLOCKEDです。Compose mockはcgroup v1でも検証できます。
`doctor-kind`は資源作成前に不足を示し、mockへのfallbackや`failCgroupV1`の強制変更を行いません。

Docker Desktop/WSLの更新・設定変更・再起動は他の作業へ影響するため、ユーザーの明示承認を
得た別作業として行ってください。確認後に`make verify`を再実行します。
参考: [Kubernetesの移行方針](https://kubernetes.io/blog/2026/10/06/kubernetes-cgroups-v2-shift/)、
[Dockerのcgroup v2](https://docs.docker.com/engine/containers/runmetrics/#running-docker-on-cgroup-v2)。

real-kindではAPI、worker、DBもクラスタ内に配置する。workerはin-cluster configとnamespace限定ServiceAccountを使用する。

host生成のkubeconfigが `127.0.0.1:<port>` を向いている場合、それをDockerコンテナ内へ渡すとコンテナ自身を指してしまう。kubeconfigのTLS検証無効化やadmin資格情報配布で修正しない。

kind設定では `networking.apiServerAddress: 127.0.0.1` とし、port mappingもloopbackを明示する。API portの不必要な固定を避ける。setupは毎回 `--context kind-<owned-name>` を明示し、ユーザーの既定Kubernetes contextへ誤applyしない。

kind node image、アプリimage、Kubernetes clientの互換性を記録する。latestを暗黙利用せず、固定image/tag/digestとbuild commitを追跡できるようにする。

## 並行作業と停止

- 各worktreeのCompose project、DB、volume、network、portを分離する。
- 統合kindの作成・apply・削除は親だけ。
- 自分が作った資源名とラベルの記録を `.harness/` に保持する。
- `make down` はデータを残して停止。kindの通常停止はworkload停止として実装し、クラスタ削除は行わない。
- クラスタ/volume削除は `make reset-local` など別操作にし、対象名を表示して明示opt-inを要求する。
- `docker system prune`、全volume削除、ユーザー既存kindクラスタ削除は禁止。

## 本番との境界

kind/DockerはこのMVPで信頼済みサンプルを動かすための環境。敵対的コード、多人数、社内ネットワークへの実接続は別のセキュリティ検証が必要。NetworkPolicyの実効性はCNIと実通信試験を伴って確認する。

一次資料は `docs/SOURCES.md` にまとめる。WSL/Docker/CLIの仕様が変わった場合、公式情報と手元の `--help` を優先し、勝手な危険回避をしない。
