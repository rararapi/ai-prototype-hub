# B — Frontend

親から渡されたcwdとbase SHAで作業してください。OpenAPIとexamples、MVP仕様を先に読みます。

所有: `apps/web/**`（package.json/package-lock含む）、`harness/handoffs/frontend.md`。

非所有: `contracts/**`、backend、infra、root Makefile、共通仕様。契約に不足があれば親に通知し、独自APIを生やさない。

## 実装

- React + TypeScript + Vite。型付きAPI client、一覧・登録・詳細。
- 名前/テンプレート/TTL、状態、operation進行、起動/停止/削除、Ready時のpreviewリンク。
- loading/empty/error/retry、削除確認、二重クリック抑止、pollの終了/再試行。
- runtime modeを常時表示。mockには実アプリ起動済みと見えるリンクや成功表示を出さない。
- backendの観測状態を表示し、タイマーや画面上の仮定でrunningにしない。
- 操作可能性を状態に合わせる。アクセシブルなlabel、keyboard、contrast、狭い画面を考慮。
- local-only前提と対応範囲を示す。会社名/個人名/実メール/内部URLをサンプルへ入れない。

## 検証・引継ぎ

type/lint/build/Vitestを実施。登録/起動中/ready/失敗/停止/削除とAPI errorを検査する。component mockはmockと明記する。Playwrightの安定locatorと初期状態の作り方をQA担当へ共有する。

component testに成功しただけで実runtimeやE2Eの成功を報告しない。変更ファイル・実行コマンド・残課題・統合時のURL設定を引継ぎに記録する。共有worktreeでは依存install/lock更新の実行を親に依頼する。
