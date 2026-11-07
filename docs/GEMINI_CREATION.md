# Geminiで画面案を作成する

## 今回の範囲

Googleログイン済みの登録利用者が、まず作りたいアプリや実現したいことを自由に入力し、
補足を確認してGeminiで固定構成の画面案を生成する。生成された内容を確認して保存し、
後から再度Geminiへ修正を依頼できる。要件・画面設定・要約・モデル・版をDBに保存する。
GitHub Pagesの操作デモは引き続きオフラインで、実通信を行わない。

Geminiが出力するのは、承認済みの表示設定だけである。HTML、JavaScript、
任意URL、追加依存、任意のシェルやコンテナは受け付けない。
保存した画面案と、Sandboxの実行状態を混同しない。表示データは架空サンプルで、
生成結果は実アプリの起動・業務要件の実現・テスト合格を意味しない。

## 利用の流れ

1. 実環境にGoogleでログインし「Geminiでアプリを作る」を開く。
2. 空の入力欄に「作りたいアプリ・実現したいこと」を書いて「つづける」を押す。
   例はプレースホルダーだけに表示し、経営管理ダッシュボードなどの内容をあらかじめ入力しない。
   この段階ではGeminiを呼ばない。
3. 入力した目的を引き継いだ画面で、名前・使う人・確かめたいことなどを補足する。
   画面名と説明文は空から始める。最初の表示は案内ページで、経営管理画面は明示的に選べる。
   利用者が生成を押した時点で、入力をサーバー経由でGeminiに送る。
4. Geminiが返した画面設定と要約を表示し、利用者が実際の案を確認する。
5. 現在の版を確認して保存する。後から一覧で再開できる。
6. 修正の依頼は、対象の現在の版に対して新しくGeminiを呼ぶ。
   他の操作で版が変わっていた場合は、更新を拒否して最新内容の確認を求める。

## APIと状態

`/api/v1/ai/apps` は既存のBearerセッション、登録名簿、Origin/HostとJSONヘッダ境界を使う。
所有者本人だけが一覧・取得・生成・確認・削除できる。別の人のIDは404にする。

- POST一覧パス: 新規生成。結果はdraft。
- GET一覧パス/個別ID: 保存済みの自分の画面案を再開する。
- POST個別ID/revise: expected_revisionを比較して新たなdraftを作る。
- POST個別ID/confirm: 現在の版をreadyにする。Geminiは呼ばない。
- DELETE個別ID: 削除済みとして扱い、遅い生成で復活させない。

生成要求はUUIDで識別し、所有者と入力hashを保存する。同じ要求の再送は再課金せず
保存済み結果を返す。同じIDで異なる入力は409。生成中や古い版との競合も409とする。
モデル通信の間にDB transactionを保持しない。予約の期限・tokenと対象の版を
照合して結果を確定する。失敗しても以前の保存内容は変更しない。
削除後は同じ生成結果の再送でも復活させない。

## 上限と秘密

既定は1利用者あたり1時間5回、1日10回、全体で1日30回。
失敗したモデル呼び出しも回数に含め、複数APIプロセスで予約を直列化する。
同時生成は1利用者1件。自動リトライは行わず、明示的な再試行だけ受け付ける。
出力は最大2048token、通信の期限は20秒が既定。入力長と返却サイズも制限する。
回数・tokenの制限はドル建ての支出停止機能ではない。

設定はAPIサーバーに限定する。

| 設定 | 既定 |
| --- | --- |
| PROTOHUB_AI_ENABLED | false |
| PROTOHUB_AI_VERTEX_PROJECT | 未設定 |
| PROTOHUB_AI_VERTEX_LOCATION | global |
| PROTOHUB_AI_MODEL | gemini-3.5-flash-lite |
| PROTOHUB_AI_TIMEOUT_SECONDS | 20 |
| PROTOHUB_AI_MAX_OUTPUT_TOKENS | 2048 |

モデル・プロジェクト・接続先を利用者のリクエストから指定することはできない。
APIキーやアクセストークンをブラウザ、画面案、サンプルPod、ログへ渡さない。
エラーは原因の種別だけを返し、上流レスポンス、例外、接続情報を返さない。

## GCP

既存の東京GKEと2つのCloud Run入口、DB/PVC/OAuth Secret、Googleログインを再利用する。
Vertex AIのgenerateContentをサーバー側ADCで呼ぶ。専用KSA `protohub-api` には
KubernetesのRoleBindingやAPIトークンのmountを与えない。
Workload Identityの直接principalに、対象プロジェクトでの
`aiplatform.endpoints.predict` と `serviceusage.services.use` だけを与える。
新しいサービスアカウント鍵は作成しない。モデルのglobal endpointは東京への
データ所在固定を保証するものではない。

`render.py --ai-project <project>` を明示した配備だけが実Geminiを有効にする。
Cloud Buildには明示的に列挙したアプリソースだけを送る。ローカル設定・Git履歴・
worklogs・OAuthファイルは送信しない。[既存GCPの更新手順](RUN_APP.md)に従い、
公開入口を閉じた上で更新し、Google認証・匿名拒否を実測してから再公開する。
非公開GKEの管理用一時経路は更新完了後に、所有IDを照合して回収する。

## 検証

単体検査で入力・所有権・回数・再送・版・期限・削除と上流エラーの境界を確認する。
実PostgreSQLでマイグレーションと複数consumerの競合を検査する。
実Gemini呼び出し、実PodのADC、公開GCP上の認証拒否と保存・再読込は
それぞれ実観測の証拠を残し、モック検査で代用しない。

参考:
[モデル一覧](https://ai.google.dev/gemini-api/docs/models)、
[構造化出力](https://cloud.google.com/vertex-ai/generative-ai/docs/multimodal/control-generated-output)、
[Workload Identity](https://cloud.google.com/kubernetes-engine/docs/how-to/workload-identity)。
