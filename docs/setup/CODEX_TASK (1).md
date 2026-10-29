# A — Backend

親から渡されたcwdとbase SHAで作業してください。共通spec、API契約、JobStore/UnitOfWorkの型を先に読みます。

所有: `apps/server/src/protohub/api/**`、`apps/server/src/protohub/persistence/**`、`apps/server/migrations/**`、`apps/server/tests/api/**`、`harness/handoffs/backend.md`。

非所有: domain interface、共通manifest/lock、worker/runtime、UI、infra、root Makefile。変更が必要なら親へ理由と最小差分を連絡し、競合編集しない。

## 実装

- Sandbox/Operationの永続API、入力validation、統一エラー、health/ready、migration。
- 操作要求とjob登録をatomicにする。generationで新しい停止/削除を守る。
- PostgreSQL job claim、lease、token照合付きheartbeat/complete/fail、期限切れ回収を実装する。
- 二重要求・再試行の冪等性を契約どおりにする。旧lease holderは同generationでも完了できない。
- DB接続/例外に秘密を含めない。任意URL/image/env/commandを受け付けない。
- APIとworkerの外部I/Oを結合しない。APIは起動完了を待たず202を返す。

## 検証・引継ぎ

正常/404/422/409/503、migration、二重要求、古いgeneration、lease再取得と旧token拒否、DB transaction境界をテストする。SQL固有の性質はSQLiteではなく実PostgreSQLで検証する。DBを利用できない場合はモックの結果と未実行を分ける。

担当のテストを実行し、変更ファイル・実行コマンド・PASS/FAIL/BLOCKED・契約変更要求を引継ぎに残す。共有worktreeならcommit/lock更新は親に任せる。独立worktreeなら自分の変更だけをcommitしSHAを返す。remoteへpushしない。
