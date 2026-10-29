# C — Runtime / Infra

親から渡されたcwdとbase SHAで作業してください。MVP/WSL仕様、RuntimeProvider、JobStore/UnitOfWork、lease token契約を先に読みます。

所有: `apps/server/src/protohub/{worker,runtime,preview}/**`、`apps/server/tests/{worker,runtime}/**`、`infra/**`、`examples/**`、`scripts/local/**`、`compose.yaml`、`harness/handoffs/runtime.md`。

非所有: persistence/API/domain、Python manifest/lock、root Makefile、検証scripts。共通依存追加は親に依頼。

## 実装

- workerのclaim/reconcile/lease heartbeat/retry/timeout/TTL。lease喪失や新generationで古い結果を確定しない。
- 明示的mock adapterと実Kubernetes adapter。実runningはreadiness＋実HTTPで観測する。
- UUID由来の安定資源名・所有label・namespace限定操作。二重実行でも重複せず、他アプリへ触れない。
- `hello-web` の固定イメージ。setupでbuildしkindへload、アプリ作成時はbuildしない。
- Composeは開発mock。real-kindではweb/API/worker/DBもkind内へ。workerのみ専用SAでin-clusterアクセス。
- localhost console/preview、固定サービスへのGET/HEAD経路、Host/Origin/path/redirect/header制御。任意upstream、Cookie/Auth転送を禁止。
- 非root/制限付きsample Pod。API/sampleへsocketやkubeconfigを渡さない。workerへSecrets/cluster-admin/execを渡さない。
- WSL Linux filesystem、既存local Docker再利用、ports/project/cluster分離。setup前にremote Dockerを拒否。
- 日常downは永続データとkindクラスタを残す。resetは対象表示＋明示opt-in。global pruneは禁止。

## 検証・引継ぎ

まずfake clientで状態や例外をunit test。実kindの実証は親と調整し、共有統合クラスタへ勝手に同時applyしない。必要なspikeは専用名と所有記録を使う。

WSL起動/停止scriptsの入口・exit code・必要envをQAへ伝える。実行できた範囲と未実行を引継ぐ。kindを悪性コード隔離環境として宣伝しない。ネットワーク分離はCNIと実通信の証拠なしに保証しない。
