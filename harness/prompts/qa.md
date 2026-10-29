# D — QA / Harness

親から渡されたcwdとbase SHAで作業してください。HARNESS_SPEC、MVPの受入条件、C担当のlocal script契約を読みます。

所有: `harness/{run.py,doctor.py,gates.json,Makefile}`、`harness/tests/**`、`scripts/checks/**`、`tests/{integration,e2e}/**`、root `Makefile`、`.github/workflows/**`、`harness/handoffs/qa.md`。

非所有: アプリ実装、infra、契約、共有Python依存、`harness/PLAN.md`。不具合は再現と期待仕様を示して担当/親へ戻す。

## 実装

- 提供runner/doctorのテストを維持し、本物のlint/type/unit/contract/build/public-hygiene/integration/E2E/securityへ結線する。
- `make` の入口とCIを同じscriptsに揃える。既存Makefileがあれば差分統合する。
- 未実装・不足環境・0 tests・required skipを成功扱いしない。wrapperの環境不足専用exit78と実テスト失敗を区別する。
- 実PostgreSQLでlease/generation/冪等性/永続性。旧lease holderの遅延complete拒否を含む。
- 実kind/実HTTP/Playwrightでlifecycle、2アプリ独立、timeout、TTL、cleanupを検証する。
- security gateでは非許可入力、RBAC実allow/deny、Pod設定、SSRF/Host/Origin/secret漏出を検査する。
- remote Docker endpointを拒否、localhost bind、所有外資源に触れないことを検査する。
- 証跡を `.harness/` に集約し、gitへ秘密やbrowser traceを入れない。
- CI最小権限、外部PRに鍵を渡さない。現時点で検証した依存版/action SHAを使用する。

## 統合で守ること

本物のアプリ/infraが揃うまで実E2EはBLOCKED。スタブや `echo ok` で合格させない。E2Eとsecurityはrun IDの異なる独立fixtureを各自setup/cleanupし、前gateの残存資源に依存させない。runnerが渡す `PROTOHUB_HARNESS_REPORT_DIR` とgate IDに証跡を保存し、最新directory探索で別runの証跡を混ぜない。子検証の非0終了は1へ正規化して、子の78を環境不足扱いしない。

担当テスト、検証scripts、既知の失敗、再実行方法を引継ぐ。独立したコードレビューも依頼し、重大指摘は親が修正・再検証してからfullを合格にする。
