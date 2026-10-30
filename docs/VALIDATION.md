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
| WSL harness自己テスト | 42 PASS（追加CLI検査前） | Linux quick runの`harness-self.log` |
| WSL Linux copy doctor-kind | PASS | `make doctor-kind`実行出力 |
| Docker版source / contract / unit | PASS | Linux quick run `8d86814` |
| Docker image build / 実DB / mock / kind / browser / security / full | 実行中または未完 | 完了後にこの表を更新 |

初期の失敗記録も残しています。CRLF、Python3.10互換、検証buildのowner/context不整合は修正済み。
独立レビューで見つかった旧PodによるReady誤判定、lease喪失後の後続mutation、kind作成失敗の
回収不能、中断時fixture cleanupは実装・回帰テストを修正し、再レビューしました。

## 実装された受入シナリオ

API/worker/provider単体、実PostgreSQLテスト、実kind/Playwright検証を別に持ちます。
後二者は実行結果がPASSになるまで実証済みとしません。

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
