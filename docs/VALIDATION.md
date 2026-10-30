# 実装・検証記録（2026-10-30 JST）

対象ブランチは `codex/protohub-local-mvp` です。GitHubへのpush/PR/merge、公開、
クラウド作成は行っていません。各担当のhandoffだけを合格証拠にはせず、親が統合コードを検証します。

## 実行環境

最初のWSL/Docker診断は不足環境でBLOCKED。その後Docker接続が可能になりました。
WSL2 Ubuntu22.04のLinux filesystem上に一時検証コピーを作り、make4.3/kind0.33/kubectl1.37を
その検証用binへ配置しました。kind/kubectlは公式チェックサムを照合しました。makeは既存Ubuntuと
同じ22.04の検証用コンテナで用意し、バイナリだけを一時領域へ取り出しました。
ホストOSへのインストール・WSL設定変更・権限変更・Docker再起動は行っていません。

## 現在までの証跡

| 対象 | 結果 | 証跡 |
|---|---|---|
| Windows portable（source/contract/unit/build/hygiene） | PASS | `.harness/reports/20261030T001936Z-d32b14e8/report.json` |
| 同run Python / Vitest | 89 / 22 PASS、skipなし | 同runの`unit/pytest.xml`, `unit/vitest.xml` |
| WSL harness自己テスト（workflow/skills含む） | 72 PASS | 今回WSLのunittest実行。最終runnerでも再検査 |
| Docker版source / contract / unit / image build / hygiene | PASS | quick `20261030T001543Z-a4f5cdf2`、full `20261030T002409Z-fe52d19a` |
| 実PostgreSQL migration/queue/concurrency/lease/TTL/persistence | 4 PASS、skipなし | fullの`integration/postgres.xml` |
| Compose mock実API/DB lifecycle・2アプリ独立 | PASS | `mock-20261030/mock-smoke.json`、source `0c331d5` |
| mock停止後のDB volume保持・再起動後レコード保持 | PASS | 同runの`retained-volumes.txt`、`mock-smoke.json` |
| Windows→localhost HTTP | PASS | 同runの`windows-http.json`。Windows対話ブラウザは未確認 |
| Playwright spec収集 | 1件収集PASS | `npm exec -- playwright test --list --reporter=list`。実行成功とは別 |
| 実kind Pod/HTTP、real Playwright、live RBAC/security | BLOCKED | Docker cgroup v1。初回fullは実際の起動FAILを保存 |
| 必須full acceptance | 未達/BLOCKED | cgroup v2化後に`make verify`を再実行する |

初回fullはclean source `94fdde0`の同一SHAで検査し、E2E/securityの実起動がFAILになった。
診断後はdoctor-kindが不足環境を先に示すため、新しいfullでは同項目をBLOCKEDにする。
旧レポートのFAILを消したり、未実行の実Pod/HTTPをPASSに変更したりしない。
最終commitでの結果とsource fingerprintは、最終runnerの`report.json`を参照する。

初期の失敗記録も残しています。CRLF、Python3.10互換、検証buildのowner/context不整合は修正済み。
独立レビューで見つかった旧PodによるReady誤判定、lease喪失後の後続mutation、kind作成失敗の
回収不能、中断時fixture cleanupは実装・回帰テストを修正し、再レビューしました。
実WSL検証で見つかったtmpfsのYAML分割、Docker時刻の9桁小数にも回帰検査を追加した。
失敗した2つのkindノードは完全なcontainer ID・所有ID・作成receiptを照合して回収し、
`20261030T002409Z-fe52d19a/recovery-cleanup.json` に記録した。

## エージェント開発ハーネスとスキル

目的・許可/禁止パス・担当・契約判断・修復予算を実CLIへ記録する。staged/unstaged/
未追跡/renameと既存dirtyファイルを検査し、検証前後と完了時のsource fingerprintを照合する。
FAIL/BLOCKED/skip・古いHEAD・変更されたdirty内容・独立レビュー欠落では完了を拒否する。

スキル5件は `.agents/skills/` に配置し、固定SHA・同梱license/宣言・参照文書・全ファイルhashを
`harness/skills.lock.json` に保存した。第三者スキルの形式検証と `make skills-check` はPASS。
独立した一時React fixtureで、実検査FAIL→証跡登録拒否→修復1回→PASS→別担当レビュー→
`finish` PASSを確認した。評価は `.harness/skill-forward/run-cc712942b8/.harness/forward-evaluation.json`。
これは開発フローの検証であり、MVPの実Pod/ブラウザの代替証拠には数えない。

## 実装された受入シナリオ

API/worker/provider単体、実PostgreSQLテスト、実kind/Playwright検証を別に持ちます。
実PostgreSQLは実行済み。実kind/Playwright部分はPASSになるまで実証済みとしません。

- 生成OpenAPIと正本の完全一致、生成フロント型の一致、統一エラー、入力/Origin/Host拒否。
- 二重要求、generation supersede、lease期限とtoken回転、旧holder拒否、最大3回retry、TTL。
- 現generationのPod/rollout/Service経路とHTTP応答を観測してReadyにする。
- UI登録/操作/実サンプルclick、2アプリ独立、stop/restart/delete、実Pod/Service回収。
- queued/running jobのworker復旧、API再起動の永続性、readiness timeout、部分作成失敗。
- worker RBACの実allow/deny、Pod設定、preview/Host/Origin、所有外資源への操作拒否。

## 残す制約

単一開発者・localhost・固定サンプルのみ。悪性コード隔離、本番認証、公開サービス、
CNIによる敵対的通信隔離、任意コード、実組織SSO、LLM接続は未対応です。
静的hygieneはbest-effortであり秘密検出の完全保証ではありません。LICENSEは未選定です。
GitHub CIの定義は実装済みですが、pushしない依頼なのでGitHub上でのCI実行は未実施です。
次の環境作業はDocker/WSLのcgroup v2化（必要なら更新・再起動）で、明示承認が必要です。
その後にreal-kindの未実証項目を再検証します。AI-DLC製品機能、OIDC、AKS等は別フェーズです。
