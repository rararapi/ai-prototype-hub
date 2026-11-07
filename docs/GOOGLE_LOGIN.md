# Google アカウントを追加した人だけが利用できる公開 URL

管理者が登録したユーザーは、ブラウザでコンソールの HTTPS URL を開き「Google でログイン」を選びます。利用者に Kubernetes の権限や VPN 接続を配る必要はありません。インターネット向けには2つのホスト名を使います。管理画面とプレビューを分け、どちらも HTTPS のみを受け付けます。クラスターの管理 API、ノード、DB、サンプル Pod は非公開です。

Google の標準ホストで公開する場合は [run.app 版の手順](RUN_APP.md) に従い、以下のアカウント登録・解除を共通で使います。下記の独自ドメイン・証明書・外部 Gateway の手順はカスタムドメイン構成向けです。

## 初回に管理者が用意するもの

1. 課金先、リージョン・ゾーン、利用期間、予算を決めます。専用ノードサービスアカウント、VPC とサブネット、管理端末から非公開 Kubernetes API へ到達できる経路を用意します。外部 HTTPS ロードバランサー、ノード、ディスク、通信、レジストリは費用の対象です。予算アラートは支出を自動停止しません。[GKE の作成・イメージ登録手順](MANAGED_KUBERNETES.md)
2. 自分が DNS を管理するドメインの下に、コンソール用とプレビュー用の2つのホスト名を決めます。以降、`CONSOLE_ORIGIN` と `PREVIEW_ORIGIN` には、それぞれ `https://` から始まるホスト名だけを入れます。両方をカバーする TLS 証明書と、クラスターのリージョンにある `REGIONAL_MANAGED_PROXY` 用サブネットの CIDR が必要です。証明書は担当者が更新し、秘密鍵はチャットや Git に置かず Secret に設定します。[GKE Gateway の準備](https://docs.cloud.google.com/kubernetes-engine/docs/how-to/deploying-gateways) · [HTTPS の設定](https://docs.cloud.google.com/kubernetes-engine/docs/how-to/secure-gateway)
3. Google Cloud の **Google Auth Platform** で Branding、Audience、Clients を設定します。Google Workspace 以外の個人アカウントにも許可する場合は External を選びます。OAuth クライアントの種類は **ウェブ アプリケーション** です。承認済み JavaScript 生成元にはコンソールのオリジン、承認済みリダイレクト URI にも同じコンソールのオリジンを登録します。Google のポップアップが発行する1回限りのコードを、API がこの同じオリジンで交換します。ローカル試験は `http://localhost:8080` を別途登録できます。プレビューのオリジンには OAuth クライアントを登録しません。[Google のコードフロー](https://developers.google.com/identity/oauth2/web/guides/use-code-model)
4. Clients 画面で取得したクライアント ID とシークレットを管理者の端末に保管します。公開用配備の最初の1回は `deploy.py --configure-google` の端末プロンプトで入力します。Google が発行したウェブクライアント JSON を使う場合は、Git 作業ツリーの外に保管して `deploy.py --context "$CTX" --manifest worklogs/managed.yaml --google-client-file "$PRIVATE_CLIENT_JSON"` を実行できます。登録 URI の一致を確認し、値は表示されません。Secret の名前は `protohub-system/protohub-google-oauth` です。API 本体だけにマウントし、再実行時は既存の値を利用します。ブラウザには公開情報のクライアント ID だけを渡します。API Pod から Google のトークン・UserInfo エンドポイントへの DNS/HTTPS 通信と、利用者のブラウザから Google への通信を許可してください。

Google の同意画面に登録するテストユーザーと、ProtoHub でアクセスを許可するアカウントは別々に管理します。ProtoHub は毎回、自身の登録名簿も照合します。[Google Auth Platform の公開ステータス](https://support.google.com/cloud/answer/15549945)

## 配備・最初のユーザーの登録

新規 GKE とレジストリを準備し、4イメージを digest で指定します。認証情報、実際のメール、ドメインや環境固有のマニフェストは `worklogs/` などの非公開領域で扱います。[クラスターとイメージの手順](MANAGED_KUBERNETES.md)

```bash
umask 077
mkdir -p worklogs
python3 infra/managed/render.py --server-image "$SERVER_IMAGE" --web-image "$WEB_IMAGE" \
  --sample-image "$SAMPLE_IMAGE" --postgres-image "$POSTGRES_IMAGE" \
  --storage-class "$STORAGE_CLASS" --owner "$OWNER" \
  --console-origin "$CONSOLE_ORIGIN" --preview-origin "$PREVIEW_ORIGIN" > worklogs/managed.yaml
python3 infra/managed/deploy.py --context "$CTX" --manifest worklogs/managed.yaml --configure-google
for name in db api worker preview web; do
  kubectl --context "$CTX" -n protohub-system rollout status "deploy/$name" --timeout=5m
done
kubectl --context "$CTX" -n protohub-system exec deploy/api -c api -- \
  python -m protohub.accounts add "$MEMBER_EMAIL"
```

Gmail・Google Workspace は、招待メールと Google が本人確認したメールが一致した最初のログインで、その Google アカウント固有の `sub` と結び付けます。他社メールで作成した Google アカウントは、管理者が独立に確認した `sub` を指定します。利用者が自己申告した ID は使いません。[Google のメール所有確認](https://developers.google.com/identity/sign-in/web/backend-auth)

```bash
kubectl --context "$CTX" -n protohub-system exec deploy/api -c api -- \
  python -m protohub.accounts add "$MEMBER_EMAIL" --subject "$VERIFIED_GOOGLE_SUB"
kubectl --context "$CTX" -n protohub-system exec deploy/api -c api -- \
  python -m protohub.accounts remove "$MEMBER_EMAIL"
```

`remove` で登録を無効化し、そのユーザーの Google セッションを失効させます。確認済みの `sub` は保持するため、同じメールが他人に再付与されても、元の所有・共有データを受け取れません。再登録には同じ本人がログインし直す必要があります。管理者用の `pods/exec` 権限は一般ユーザーに付与しません。

新規環境では新しい DB/PVC を使います。開発モードではメールの本人確認を行っていないため、既存 DB を移す場合は所有者と共有先を個別に確認してください。メールの一致だけで古い開発データを本番へ移さないでください。

## インターネットに HTTPS を公開する

次のコマンドは、DNS やクラウドを変更せずに Gateway の YAML を生成します。公開版は `--access internet` を指定します。Gateway と2つの HTTPRoute が接続するのは web と preview のみです。リージョン外部 HTTPS Gateway のプロキシ専用サブネットを指定し、GKE ヘルスチェックに必要な送信元 IP とともに対象 Pod のポートだけを許可します。

```bash
EDGE_ARGS=(--access internet --console-origin "$CONSOLE_ORIGIN" --preview-origin "$PREVIEW_ORIGIN"
           --proxy-cidr "$PROXY_ONLY_CIDR" --tls-secret "$TLS_SECRET" --owner "$OWNER")
python3 infra/managed/gateway.py "${EDGE_ARGS[@]}" > worklogs/public-gateway.yaml
```

予算と公開承認を得た後に、両方のホスト名を含む TLS Secret を作成します。以下の `--apply-context` が料金の発生し得る操作です。配備ツールは対象リソースの所有者と稼働中の Google 認証を検査し、匿名リクエストに対して API とプレビューがともに 401 を返すことを確認してから公開します。

```bash
kubectl --context "$CTX" -n protohub-system create secret tls "$TLS_SECRET" \
  --cert="$CERT_CHAIN_PATH" --key="$PRIVATE_KEY_PATH"
python3 infra/managed/gateway.py "${EDGE_ARGS[@]}" --apply-context "$CTX"
kubectl --context "$CTX" -n protohub-system wait --for=condition=Programmed \
  gateway.gateway.networking.k8s.io/protohub-browser --timeout=20m
kubectl --context "$CTX" -n protohub-system get gateway protohub-browser \
  -o jsonpath='{.status.addresses[0].value}'
```

その IP に両方の DNS 名の A レコードを設定します。初回はプライベートブラウザで、未登録アカウントの拒否、登録アカウントの成功、未共有プレビューの拒否、共有解除・登録解除後の再アクセス拒否を実測してください。登録者は自分の所有・共有アプリだけを表示できます。プレビューの URL を直接開いたときには、管理画面からの認証付き読み取りが必要です。

## 更新と運用

Google セッションはサーバー側で失効を確認し、最長24時間有効です。アプリ API とプレビューはリクエストごとに登録状態を確認します。読み取り済みの画面やスクリーンショットまで取り消すことはできません。

配備と経路更新は同時に走らせず、管理者が順番に実行します。公開中の認証サーバーや公開オリジンを変更する場合は、対象所有者と namespace を確認したうえで `protohub-browser-web` と `protohub-browser-preview` の HTTPRoute を一時的に外し、外部から到達しなくなったことを確認します。新リリースの rollout 後に同じ `gateway.py` を実行すると、匿名拒否の実測に合格してから経路が復帰します。DB、PVC、Secret は保持します。Gateway を残してルートだけ外す場合もロードバランサー等の料金は続きます。

AKS に移す際は Google OAuth と登録名簿を再利用できます。会社のネットワーク構成に合わせて入口の GatewayClass、ヘルスチェック、DNS/TLS とレジストリを切り替え、移行先で同じ認証・匿名拒否を確認します。
