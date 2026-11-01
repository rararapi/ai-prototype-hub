# 開発ログイン・アプリ共有・共通LLMキー

## 開発ログイン

localhostの管理画面でメールアドレスを入力し「ログイン」を押す。
パスワード、メール送信、アドレスの所有確認は行わない。任意の開発ユーザーに
切り替えられるため、信頼できる開発者だけが使うローカル/開発環境向け。
本番の本人確認や多ユーザーサービスのセキュリティを提供する機能ではない。

`PROTOHUB_ENVIRONMENT` は既定 `local`。`local` / `development` / `test` のみで
開発ログインが使える。`production` ではログインと保護対象APIを無効化する。
本番SSOへ自動的に切り替わる実装は含まない。既存のlocalhost bind / Host / Origin /
JSON / `X-ProtoHub-Client` の制約は継続する。

アドレスは前後の空白を除去して小文字に正規化する。ログインは24時間有効のランダムな
Bearerトークンを発行し、DBにはSHA-256ハッシュだけを保存する。ログアウトはサーバー側で
そのセッションを失効させる。ブラウザはタブのsessionStorageに保存し、Cookieを使わない。
共有PCでの利用後はログアウトする。ログイン後のレスポンスには `Cache-Control: no-store`
を適用する。トークンやメールを公開ログやcommitへ保存しない。

## 所有者と共有先

- 新規登録したアプリの所有者はログイン中のメールアドレスからAPIが設定する。
- 一覧・詳細・操作履歴は、自分の所有アプリと自分宛ての共有アプリだけを返す。
- 起動・停止・削除・共有設定は所有者だけが操作できる。
- 所有者は詳細の共有設定で閲覧できるメールアドレスを追加・削除できる。
  `PUT /api/v1/sandboxes/{id}/shares` の `emails` は最大100件の置換リスト。
  空のリストで全共有を解除する。共有先同士のメール一覧は共有しない。
- 未ログインは401、権限のないアプリ/操作IDは404。表示を隠すだけでなくAPIで検査する。

認証導入前のアプリはマイグレーションで削除しない。所有者が不明な既存レコードは
`owner_email=null` のまま保持し、全ユーザーの一覧・詳細から隠す。
最初にログインしたユーザーへ一括譲渡しない。既存アプリを引き継ぐ必要がある場合は、
DB管理者が対象IDと移管先を別途確認した上で明示的に所有者を設定する。
既存の実行資源や永続ボリュームは自動削除しない。

## 共通LLMキー

全アプリで同じサーバー設定 `PROTOHUB_LLM_API_KEY` を解決する。
アプリ別のAPIキー登録欄やユーザー入力の環境変数は追加しない。
`Settings.resolve_llm_api_key(sandbox_id)` に設定解決を集約し、将来アプリ単位の
設定が必要になった場合にこの境界を拡張できるようにする。

実キーはリポジトリへ書かず、起動するWSLシェルの環境変数にだけ設定する。
例えばBashで次のように入力する（値は表示しない）。

```bash
read -rsp 'Shared LLM API key: ' PROTOHUB_LLM_API_KEY
export PROTOHUB_LLM_API_KEY
make up-mock  # kindの場合は make up-real
unset PROTOHUB_LLM_API_KEY
```

ComposeではAPIコンテナにだけ渡す。kindでは既存の所有権検査後、標準入力から
`protohub-system/protohub-llm` Secretへ設定し、APIコンテナだけが参照する。
キーをコマンド引数、生成manifest、ConfigMap、イメージ、ブラウザ、worker、preview、
サンプルアプリへ入れない。Kubernetes管理者/Docker管理者はそれぞれの管理権限で
秘密値を参照できるため、これは秘密管理サービスの代替ではない。

kindの次回起動時に環境変数が未設定なら保存済みキーを維持する。
明示的に `PROTOHUB_LLM_API_KEY='' make up-real` とすると保存済み値を空にする。
キーの更新は `make up-real` によるAPIの新しいrolloutで反映する。
Composeは毎回起動環境の値を使う（未設定なら空）。

現行テンプレートにLLM呼び出し機能はないため、この変更は共通キーの設定・配送・解決まで。
実キーを使った通信、モデル/ベンダーの選定、料金発生、任意コード実行は追加しない。

## consoleとpreviewの境界

consoleはsessionStorageのトークンをAPI Authorizationヘッダでのみ送る。
別portのpreviewへトークンやCookieを送らず、previewも上流への認証ヘッダ転送を行わない。
別portはCookieの隔離にはならないため、認証Cookieの導入は行わない。

previewは従来通り、localhostの信頼済み固定サンプル向け。URLを知るローカル利用者が
サンプルを開く経路は、今回の管理画面/APIの閲覧権限とは別であり認証対象ではない。
共有解除は管理APIへのアクセスを取り消すが、既知のpreview URLを失効する機能ではない。
非公開データ・任意アプリ・未信頼コンテンツを扱う前には別ホスト名とpreview認可を
設計し直す。この開発ログインでその境界を広げない。
