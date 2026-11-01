# 開発・検証ハーネス仕様

## ハーネスの意味

ここでいうハーネスは、Codexに繰り返し安全に開発させるための**仕様・分担・実行入口・テスト・観測・修正ループ**。新しいLLM製品やCodex APIの再実装ではない。

`AGENTS.md` は短い常設ルール、`CODEX_TASK.md` は今回の実行依頼、specは仕様の正本、`harness/PLAN.md` は進捗、scriptsは再現可能な検証、runnerは結果を記録する。

実装したエージェント用workflowは `harness/workflow.py`。目的、変更許可/禁止パス、担当、
契約判断、修正予算、検査・独立レビュー証跡をタスク単位に保持する。
実Git差分と既存dirty変更を検査し、現在のsource snapshotと一致しない証跡では完了できない。
詳細は [DEVELOPMENT_WORKFLOW.md](DEVELOPMENT_WORKFLOW.md)。テストrunnerだけをハーネスの
全体とは扱わない。通常工程の承認は繰り返さず、既存の権限境界を守る。

`.agents/skills/` の固定スキルはこの手順へ接続する。`make skills-check` は出所・license・hashを
確認し、上流mainからの暗黙更新や未確認の実行helper混入を検出する。[SKILLS.md](SKILLS.md)参照。
runnerは検証の前後に `git_snapshot` を記録し、HEAD・dirty内容のfingerprintが変わればFAILにする。

## 既にあるひな形

- `harness/run.py`: 標準ライブラリだけで動く。manifestのgateを依存順に実行し、timeout、FAIL、BLOCKEDを記録する。
- `harness/doctor.py`: 依存コマンドとDocker daemonを読み取り中心で診断する。
- `harness/tests/test_harness.py`: runner/doctor自身のテスト。
- `harness/gates.json`: 実装予定の検証scriptsを呼ぶ。必要ファイルがない場合はBLOCKEDとなる。
- `harness/Makefile`: root Makefileが未実装でも自己テストできる入口。

**ひな形の自己テストPASSと、ProtoHub全体の完成は別**。アプリ用の検証scriptsや実行環境が揃うまでは `quick` / `full` が非0で終わるのが正常。

## Codexが実装する共通コマンド

| root Make target | 役割 | 自動的に行わないこと |
|---|---|---|
| `doctor` | compose前提の環境確認 | install、restart、group変更、context切替 |
| `doctor-kind` | kind/kubectlまで確認 | クラスタ作成 |
| `up-mock` | Composeの開発モード。画面にmockを表示 | kindへの暗黙切替 |
| `up-real` | 所有するkindクラスタと実行stackを起動 | 既存別cluster上書き、有料クラウド |
| `check` | harness `quick` | real E2E成功と同一視 |
| `integration` | 実PostgreSQLでDB/job/復旧テスト | 稼働中ユーザーDB初期化 |
| `e2e` | real kind＋Playwright＋実HTTP | mockへのfallback、required test skip |
| `security` | 公開前チェックとPod/RBAC/proxy検査 | 悪性コード隔離を保証したと宣言 |
| `verify` | harness `full`、全必須gate | missing toolをskip成功 |
| `logs` | 自分のrunに限定したログ取得 | env/JWT/kubeconfigの丸出し |
| `down` | 所有stackの停止、永続データ保持 | DB volume破棄 |
| `reset-local` | 明示opt-in＋対象検証で自分の開発資源削除 | 既定kindや他project削除、global prune |

標準確認のroot targetは `python3 harness/run.py --group quick` / `--group full` を呼ぶ。gate内scriptから `make verify` を呼んで再帰しない。

## Gateとscriptの契約

| Script | 必須の実検査 |
|---|---|
| `scripts/checks/source.sh` | Python format/lint/type、TypeScript lint/type、shell構文/必要な静的検査 |
| `scripts/checks/contracts.sh` | OpenAPI validation、実装から生成した契約との差分、frontend生成型との一致 |
| `scripts/checks/unit.sh` | pytest、Vitest。0 testsは失敗。必須testのskipは非合格 |
| `scripts/checks/build.sh` | backend package、frontend production build、必要Docker image build |
| `scripts/checks/public-hygiene.sh` | 秘密ファイル/実キー/内部設定の検査。単なるrgのみを完全検出と称さない |
| `scripts/checks/integration.sh` | 実PostgreSQL、migration、queue lease、複数consumer、再起動/永続性 |
| `scripts/checks/e2e.sh` | テスト専用kind起動/検証、Playwright、実PodとHTTP、stop/delete/TTL |
| `scripts/checks/security.sh` | Pod設定、RBAC許可/拒否、固定template拒否、proxy SSRF防止、secret redaction |

Python/Nodeテストは可能な限り固定したDocker開発イメージ内で実行する。ユーザーのWSLへ多数のランタイムを直接インストールしない。検証image/依存をネットワークから取得できない場合は理由を分けて報告する。

scriptsは本物の検証を実行する。`echo ok`、`|| true`、`--passWithNoTests`、missing-fileならexit0などを使用しない。test依存が未実装の時にempty scriptを置かない。

## 状態・終了コード・レポート

- PASS: コマンドが実行され、定義された必須検査を満たし、exit0。
- FAIL: 実検査の不合格、非0終了、timeout。
- BLOCKED: 必須環境/ファイル/permissionが不足、または依存gateが通っていない。
- NOT_RUN: 今回選択していない検証。runnerの結果とは別に、最終報告に明記する。

ランナーの終了コードはPASS=0、FAIL=1、BLOCKED=2。runnerは信頼済みscriptのexit codeを評価するため、script自身が検査の意味を担保する必要がある。

gateの `blocked_exit_codes` は任意。doctorは `[2]`、アプリ検証wrapperは `[78]` として環境不足を明示する。wrapperは自前のpreflightで不足を確認したときだけ78を返し、pytest等の非0終了を一律BLOCKEDにしない。既定では非0はFAIL。Ctrl+C/終了signalで中断した検証は成功にせず、子process groupも停止して後続gateを実行しない。

wrapperは子検証コマンドの非0終了を1へ正規化し、元の終了コードをlogへ記録する。`set -e` だけで子の78をそのまま伝播させない。自前preflight78→BLOCKED、子test78→FAIL、assertion failure→FAILを回帰テストする。

結果を `worklogs/reports/<run_id>/report.json` とgate別logに残す。git SHA、dirty状態、開始時刻、gate所要時間・結果、失敗/不足理由、中断状態を記録する。ログはbest-effort redactionを行うが完全保証ではない。ログ・スクリーンショットは公開commitせず、利用者情報や秘密を除去してから共有する。

各テストscriptは必要に応じてJUnit、Playwright HTML/trace、Pod一覧などの証跡を同run配下に保存する。これらは今回の実行によるものと分かる時刻/commit/run IDを持つ。過去のPASSをコピーしない。

runnerは `PROTOHUB_HARNESS_RUN_ID`、`PROTOHUB_HARNESS_REPORT_DIR`（今回runの絶対path）、`PROTOHUB_HARNESS_GATE_ID` を子gateへ渡し、外から同名の値が設定されていても上書きする。scriptはこの配下にgate固有の証跡フォルダを作る。「最新reportを探索する」方式にしない。script単独実行時は専用run directoryを明示生成し、その場所を表示する。

`e2e.sh` と `security.sh` は各自のrun IDに紐づく独立fixtureをsetupし、所有を確認した資源だけcleanupする。securityがe2eの残存clusterに依存してはいけない。共通のsetup実装は再利用してよいが、名前・context・ports・volumeは衝突させない。通常終了だけでなく失敗/中断時の扱いも検証する。

## 実runtime必須シナリオ

1. 管理画面から登録→起動→Ready→URLが実サンプルを返す→停止→再起動→削除。
2. 同時に2個作成し、別URLで閲覧。一方の停止/削除がもう一方に影響しない。
3. 同じ起動を二重送信してもDeployment/Serviceが重複しない。
4. 起動中のstop/deleteの後、遅れたjobが復活させない。
5. workerを再起動し、lease回復とreconcileを確認する。同じgenerationで旧lease holderが遅れて完了しても、状態を確定できないことをintegration testで検査する。
6. readiness timeout・部分作成失敗を注入し、UIに原因概要、DBにfailed、所有資源に適切な回収を確認する。
7. テスト用短TTLでPodが停止し、管理レコードは残る。
8. API/worker再起動後も管理レコードが保持される。
9. 削除後、対象ラベルのPod/Service/preview routeが残らない。
10. cleanupが無関係なrun/アプリ/volumeへ触れないことを確認する。

状態競合の細かな組合せはunit/integrationでも検査する。E2Eを過剰に複製せず、実runtimeに依存する証拠を残す。

## CI

GitHub Actionsは次のタイミングで実行する。feature branchへのpushだけでは起動せず、
PRとの重複実行を避ける。mainとPRで同じ軽量jobも重複させない。

| 起点 | job / コマンド | 検証範囲 |
|---|---|---|
| PR作成・更新 | `devcontainer` / `make check-dev` | runner自己テスト、公開前検査、lint/type、契約、単体テスト、package/web build |
| mainへのpush（マージ含む） | `verify` / `make verify` | 実PostgreSQL、kind、ブラウザ、runtime/securityを含む全11gate |
| 手動 `workflow_dispatch` | `verify` / `make verify` | 選択branchの全体検証。軽量jobは重複実行しない |

PRでは `verify` jobはSKIPPED（実runtimeはNOT_RUN）となる。required checkでもskipped jobは
成功扱いになるため、PRの緑表示を全体検証の証拠にしない。
PRの軽量jobのPASSは、実DB・Docker image build・実runtimeの合格を意味しない。
API、worker、起動基盤、E2Eなどruntimeに関わる変更は、マージ前にも対象の現在のコードで
`make verify` を実行して証跡を残す。手動CIも利用できるが、workflow_dispatchのボタンは
このworkflowがdefault branchへ反映されてから利用できる。
手動実行はGitHub Actionsの「ProtoHub local gates」→「Run workflow」でbranchを選ぶ。
手動runはPRのrequired checkを強制する仕組みではなく、担当が対象SHAと結果を確認する。
mainの全体検証が失敗したら未解決として扱い、軽量jobの成功で置き換えない。

最小権限 `contents: read` を基本にし、外部PRへ秘密やクラウド資格情報を渡さない。
`pull_request_target` でPRの任意コードを実行しない。

quick系jobは並行でよい。実kind E2Eは独立runnerで実行し、同一環境を複数jobで奪い合わない。action/image/toolのversionは導入時に公式releaseを確認し、可能なものは不変SHA/digestで固定する。

CIはheadlessブラウザで検証し、失敗時の限定的な証跡を保存する。クラウド課金・社内鍵・実LLM呼び出しは必要としない。CIのkind成功と利用者のWSL成功は別証拠として扱う。

## 修復ループ

失敗→原因特定→最小修正→影響テスト→統合gateの順で継続。期待値を弱めたりテストを削除して緑にしない。環境の問題であればアプリの失敗と区別する。同じ原因で修正できない場合は、試行内容と必要な人間操作を記録してBLOCKEDにする。


## API再起動後の公開経路の復旧

E2EでAPIを再起動した後、Deployment rollout完了や単発GET200だけを復旧完了にしない。
古いAPI Podが消え、再起動前とは異なるReady Podが一つだけになり、その同じUIDの下で
console経由のGETが保持済みレコードのID/名前/所有者と一致し続ける3秒間を観測する。
502/503/504、接続エラー、Podの交代・再増加は観測期間をリセットする。
認可エラー、未知HTTPエラー、不正JSONや別レコードは直ちに失敗する。

観測は絶対120秒で打ち切り、各HTTP/kubectl呼び出しにも残り時間以下のtimeoutを渡す。
非冪等な登録POSTやシナリオ全体を再試行しない。実kindではこの復旧を3回繰り返し、
各回直後の登録を一度だけ実行して一件だけ作成されたことを確認する。
旧Pod残存・200→502→200・UID交代・恒久失敗・deadline超過は決定論的な単体テストで検査し、
実kindの観測値は今回runの `runtime-checks.json` に残す。
