# 東京の標準 HTTPS URL で使う

コンソールとプレビューにそれぞれ Cloud Run の標準 `run.app` URL を使います。TLS と公開 DNS は Google が提供します。API、PostgreSQL、ワーカー、固定サンプルは非公開の GKE に配置します。コンソールとプレビューを別オリジンにすることで、プレビュー内のコードからコンソールのセッションを読み取れないようにします。

## 費用の前提

東京の1ゾーン、1ノード、月730時間、オンデマンドでの試算です。2026年11月に確認したカタログ換算 1 USD = 158.205 円を使っています。実際の請求は月の換算と使用量に依存します。

| 項目 | 税別の月額目安 |
| --- | ---: |
| e2-medium 1台 | 約4,964円 |
| pd-balanced 30 GiB と、同単価で見た DB 1 GiB | 約638円 |
| 上記の小計 | **約5,602円** |
| GKE 管理料 | 請求先の無料枠がまるごと適用されれば0円。枠が使えない場合は約11,549円追加 |

Cloud Run、Cloud DNS、レジストリ、バックアップ、ログ、通信、税は別途です。Cloud Run は各サービス0〜1インスタンスのリクエスト課金にします。コールドスタートやアクセス急増時は待ち時間やリクエスト拒否があり得ます。月1万円を想定する場合は、ノード作成前に請求先全体の GKE 無料枠を確認してください。無料枠適用時の小計に DNS やその他の料金が加わります。クレジットが使えない場合は小計だけで約17,151円になるので、月1万円ではクラスター作成を保留します。予算通知は支払いを自動停止しません。Cloud Run 単体の spend cap が利用できる場合も、GKE・ディスク等の費用は別管理です。[GKE 管理料と無料枠](https://cloud.google.com/kubernetes-engine/pricing) · [東京の VM 料金](https://cloud.google.com/products/compute/pricing/general-purpose) · [ディスク](https://cloud.google.com/compute/disks-image-pricing) · [Cloud Run](https://cloud.google.com/run/pricing) · [予算と spend cap](https://docs.cloud.google.com/billing/docs/how-to/budgets-spend-caps)

## 1. URL だけを先に予約する

GKE 用 VPC の東京リージョンに、ノード用サブネットと Cloud Run の Direct VPC egress 専用の RFC1918 IPv4 /26 サブネット（このプロファイルで許可するサイズ）を確保します。Cloud Run 用のサービスアカウントは専用・キーレスとし、アプリデータや Kubernetes への権限を付与しません。Cloud Run API と Cloud DNS API を有効にします。以下の変数は各環境の値に設定してください。

```bash
REGION=asia-northeast1
umask 077
mkdir -p worklogs
EDGE=(--region "$REGION" --network "$NETWORK" --subnet "$RUN_SUBNET" --service-account "$EDGE_SA" --owner "$OWNER")
python3 infra/managed/run_proxy.py --role web --service "$WEB_SERVICE" "${EDGE[@]}" --parked > worklogs/run-web.yaml
python3 infra/managed/run_proxy.py --role preview --service "$PREVIEW_SERVICE" "${EDGE[@]}" --parked > worklogs/run-preview.yaml
```

`replace` は既存サービスも更新するため、初回は両サービス名が未使用であることを確認してから、対象プロジェクトに IAM 非公開のサービスを作成します。既存リソースの同名上書きを避けてください。予約構成は稼働確認パス以外に 503 を返し、バックエンドに転送しません。呼出権限のない利用者には Google が 403 を返します。サービスの UID、作成日時、最新リビジョン、Google が報告する URL を管理記録に控えます。`gcloud run services describe` の primary URL とプロジェクト番号付きの別名は、同じサービスでも別オリジンになるため、以降は検証で選んだ同一の URL を使い続けます。[Cloud Run 標準 HTTPS URL](https://docs.cloud.google.com/run/docs/triggering/https-request)

```bash
gcloud run services replace worklogs/run-web.yaml --project="$PROJECT" --region="$REGION"
gcloud run services replace worklogs/run-preview.yaml --project="$PROJECT" --region="$REGION"
PAIR=(--project "$PROJECT" --region "$REGION" --web-service "$WEB_SERVICE" --preview-service "$PREVIEW_SERVICE"
      --owner "$OWNER" --service-account "$EDGE_SA" --network "$NETWORK" --subnet "$RUN_SUBNET")
python3 infra/managed/run_proxy.py verify "${PAIR[@]}" --stage parked
```

既存の予約を引き継ぐ場合、実際の作成記録の UID と名前空間・プロジェクトを照合してください。旧ラベルの予約は `--stage legacy-parked` で検査し、該当する正確な所有サービスにのみ所定の所有ラベルを付けて `parked` 検査を再実行します。未認証公開、別リビジョンへの分岐やタグ付き URL がすでにある場合は置換を中止します。

## 2. Google ログインを登録する

`CONSOLE_ORIGIN` と `PREVIEW_ORIGIN` に検証済みの2つの URL を設定します。Google Auth Platform のウェブ OAuth クライアントには、コンソールの正確な URL を JavaScript 生成元とリダイレクト URI に登録します。シークレットは API だけが利用します。ドメイン確認を求められたらプロジェクトの実際の確認手順に従い、共有親ドメイン全体を登録しないでください。アプリの許可名簿は Google のテストユーザー一覧とは別に管理します。[Google ログイン・メンバー追加と解除](GOOGLE_LOGIN.md) · [Google OAuth コードフロー](https://developers.google.com/identity/oauth2/web/guides/use-code-model)

OAuth クライアントの種類は「ウェブ アプリケーション」です。2 か所の登録を保存してから Google Auth Platform でクライアント JSON をダウンロードし、管理端末のリポジトリ外の非公開ファイルに保存します。`OAUTH_CLIENT_JSON` にそのファイルの絶対パスを設定します。チャットへ貼り付けたり、Cloud Build の入力に加えたりしないでください。

以下はダウンロードファイルの検査対象となるフィールドです。実際の値は Google が発行したファイルのものを使います。`javascript_origins` と `redirect_uris` の両方に、検証済みのコンソール URL を末尾スラッシュやパスなしで登録してください。

```json
{
  "web": {
    "client_id": "<Google が発行したクライアント ID>",
    "client_secret": "<Google が発行したシークレット>",
    "javascript_origins": ["https://<コンソールの run.app ホスト>"],
    "redirect_uris": ["https://<コンソールの run.app ホスト>"]
  }
}
```

## 3. イメージを確定して GKE に配備する

ノードと管理 IP エンドポイントは非公開です。Cloud DNS の additive VPC scope でアプリ内の `cluster.local` を維持し、Cloud Run は VPC 内の headless Service を `protohub.gke.internal` で解決します。この名前を上書きできる private zone、DNS response policy、転送、VPC ピアリングの有無はネットワーク管理者が確認します。Cloud Run にクラスター IP や管理トークンを配布しません。[GKE Cloud DNS](https://docs.cloud.google.com/kubernetes-engine/docs/how-to/cloud-dns) · [Direct VPC egress](https://docs.cloud.google.com/run/docs/configuring/vpc-direct-vpc)

管理端末から非公開 Kubernetes API に到達する経路が必要です。既存 VPC 内の管理端末、承認済みの Fleet Connect Gateway、必要時のみ起動する専用 IAP 踏み台などを選びます。常時 VPN・NAT の費用は上の試算に含めていません。アプリの利用者にクラスタ管理権限を配らないでください。[管理接続の選択肢](https://docs.cloud.google.com/kubernetes-engine/enterprise/multicluster-management/gateway/using)

Docker が動く管理端末では [Buildx の手順](MANAGED_KUBERNETES.md) を使用できます。Cloud Build を選ぶ場合は、許可したアプリソースだけのアーカイブを生成します。ローカルの提案資料、Git 履歴、環境変数、OAuth JSON を Google に送信しないよう、作業ツリー全体をビルド入力にしないでください。新しい Tokyo レジストリと、そのリポジトリでのみ writer のビルド用サービスアカウント、非公開の東京のソースバケットが必要です。ビルドアカウントにはそのバケットの `storage.objectViewer` とプロジェクトの `logging.logWriter` を与えます。

```bash
python3 infra/managed/build_context.py --project "$PROJECT" --region "$REGION" --repository "$REPOSITORY" --output worklogs/run-build
gcloud builds submit worklogs/run-build/application-source.tar.gz --project="$PROJECT" --region="$REGION" \
  --config=worklogs/run-build/cloudbuild.yaml --service-account="projects/$PROJECT/serviceAccounts/$BUILDER_SA" \
  --gcs-source-staging-dir="gs://$SOURCE_BUCKET/staged"
```

`STORAGE_CLASS` は対象クラスターで承認済みの永続ディスク用 StorageClass 名です。Cloud Build の成功した実行の ID を `BUILD_ID` に指定し、4 イメージをその実行が返した digest で固定します。手元で Buildx を使った場合は、[レジストリの digest を取得する手順](MANAGED_KUBERNETES.md)で同じ順（server、web、hello-web、postgres）の参照を用意します。

```bash
set -euo pipefail
gcloud builds describe "$BUILD_ID" --project="$PROJECT" --region="$REGION" \
  --format='json(status,results.images)' > worklogs/run-build-result.json
python3 - "$REGION-docker.pkg.dev/$PROJECT/$REPOSITORY" <<'PY' > worklogs/run-images.txt
import json, re, sys
from pathlib import Path

build = json.loads(Path("worklogs/run-build-result.json").read_text())
tag = json.loads(Path("worklogs/run-build/source-manifest.json").read_text())["tag"]
names = [f"{sys.argv[1]}/{name}" for name in ("server", "web", "hello-web", "postgres")]
images = {item["name"]: item["digest"] for item in build.get("results", {}).get("images", [])}
if build["status"] != "SUCCESS" or set(images) != {f"{name}:{tag}" for name in names}:
    raise SystemExit("Build ID, source tag or four expected images do not match")
for name in names:
    digest = images[f"{name}:{tag}"]
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
        raise SystemExit("Missing registry digest")
    print(f"{name}@{digest}")
PY
mapfile -t RUN_IMAGES < worklogs/run-images.txt
python3 infra/managed/render.py \
  --server-image "${RUN_IMAGES[0]}" --web-image "${RUN_IMAGES[1]}" \
  --sample-image "${RUN_IMAGES[2]}" --postgres-image "${RUN_IMAGES[3]}" \
  --storage-class "$STORAGE_CLASS" --owner "$OWNER" \
  --console-origin "$CONSOLE_ORIGIN" --preview-origin "$PREVIEW_ORIGIN" > worklogs/run-managed.yaml

# マニフェストと初回 OAuth ファイルをローカルで検証。秘密値を出力しない。
python3 - "${OAUTH_CLIENT_JSON:-}" "$CONSOLE_ORIGIN" <<'PY'
import sys
from pathlib import Path
sys.path.insert(0, "infra/managed")
from deploy import load_google_client_file, read_manifest
read_manifest(Path("worklogs/run-managed.yaml"))
print("Manifest validated")
if sys.argv[1]:
    load_google_client_file(Path(sys.argv[1]), sys.argv[2])
    print("Google Web client validated")
else:
    print("OAuth file pending; database-only preparation is available")
PY
```

予算・無料枠・管理端末からの到達経路を確認し、[GKE の作成手順](MANAGED_KUBERNETES.md)の `GKE_ARGS` に `--run-app-profile` を加えます。最初のコマンドは計画表示です。新設の承認がある場合に2番目を実行すると課金が始まります。既に対象クラスターがある場合は作成手順を飛ばします。

```bash
python3 infra/managed/new_gke.py "${GKE_ARGS[@]}" --run-app-profile
python3 infra/managed/new_gke.py "${GKE_ARGS[@]}" --run-app-profile --create
```

管理端末で対象プロジェクト・クラスターの kubeconfig コンテキストを `CTX` に設定し、ノードと指定 StorageClass を読み取れることを確認します。Cloud Run はまだ IAM 非公開の予約状態です。

```bash
kubectl config get-contexts "$CTX"
kubectl --context "$CTX" get nodes
kubectl --context "$CTX" get storageclass "$STORAGE_CLASS"
python3 infra/managed/run_proxy.py verify "${PAIR[@]}" \
  --web-url "$CONSOLE_ORIGIN" --preview-url "$PREVIEW_ORIGIN" --stage parked
```

### 単一ノードの空き容量を確認する

東京の e2-medium 1 ノードで、GKE 初期構成の割り当て可能 CPU は **940m**、システム Pod の CPU requests は **841m** でした（1000m が 1 CPU）。この時点の空きは 99m で、DB の要求 100m にも足りません。配備先では、`kubectl top` の瞬間使用量ではなく、スケジューラーが使う requests で判断します。

この固定サンプル用構成ではシステム監視は `--monitoring=SYSTEM` とし、Managed Service for Prometheus を無効にします。利用していない Horizontal Pod Autoscaling と Filestore CSI ドライバーも無効にします。Dataplane V2、PostgreSQL が利用する Persistent Disk CSI ドライバー、Workload Identity、システム・ワークロードのログは有効に保ちます。既存クラスターでは他のワークロードが対象機能を利用していないことを管理者が確認してください。[GKE のクラスター設定](https://docs.cloud.google.com/sdk/gcloud/reference/container/clusters/update)

システム Pod が安定してから、次の2つの出力でノードの `allocatable` と全 Pod の予約済み CPU・メモリを確認します。

```bash
kubectl --context "$CTX" get nodes -o custom-columns='NAME:.metadata.name,CPU:.status.allocatable.cpu,MEMORY:.status.allocatable.memory'
kubectl --context "$CTX" describe nodes | sed -n '/^Allocated resources:/,/^Events:/p'
```

アプリの定常時は DB 100m、API 50m、worker 50m、preview 25m、web 25m の合計 **250m** です。起動中の固定サンプルは 1 個につき **25m** を追加で予約します。DB だけを先に配備した場合、残り 4 Pod に必要な追加分は 150m です。RollingUpdate では旧 Pod と新 Pod が同時に存在し得るため、更新する Deployment の追加 Pod の要求も見込みます。複数の更新を同時にかける場合はその合計で判断します。GKE のバージョンやアドオンにより実際の空きは変わります。余裕が足りない場合は配備を止め、予算を確認してから構成を変更してください。[Kubernetes のローリング更新](https://kubernetes.io/docs/concepts/workloads/controllers/deployment/#rolling-update-deployment)

OAuth JSON を待つ間は、必要に応じて非公開の PostgreSQL だけを先に準備できます。これはディスクと DB を作成する有料操作です。このコマンド単体で作成されるのは DB の基盤までです。ログインに必要な API と OAuth の設定は後の手順で配備します。

```bash
python3 infra/managed/deploy.py --context "$CTX" --manifest worklogs/run-managed.yaml --prepare-database
kubectl --context "$CTX" -n protohub-system rollout status deployment/db --timeout=5m
```

OAuth JSON の検証が済んだら、次のコマンドでアプリを配備します。

```bash
python3 infra/managed/deploy.py --context "$CTX" --manifest worklogs/run-managed.yaml \
  --google-client-file "$OAUTH_CLIENT_JSON"
for name in db api worker preview web; do
  kubectl --context "$CTX" -n protohub-system rollout status "deployment/$name" --timeout=5m
done
```

初回配備では `deploy.py` が OAuth JSON を読み、`protohub-system/protohub-google-oauth` を作成します。再実行時は既存 Secret を再利用します。ファイルを渡すだけでは認証情報はローテーションされません。e2-medium は共有コアなので、Pod が Pending の場合は CPU・メモリやイメージ取得状態を調べ、予算確認前のノード増設は保留します。

### 最初の利用者を登録する

許可名簿は既定で空です。DB マイグレーションの完了後は、公開を待たずに、管理者が非公開の経路から最初の利用者を登録できます。通常の全体配備では API の init コンテナがマイグレーションを実行するので、上の rollout 完了後に次のコマンドを使います。先にマイグレーションを済ませた環境なら、承認済みの管理用コンテナから同じ `python -m protohub.accounts add` を実行できます。DB の認証情報は既存の Secret を参照し、利用者には渡しません。

```bash
read -r -p '最初に利用を許可する Google メールアドレス: ' MEMBER_EMAIL
kubectl --context "$CTX" -n protohub-system exec deploy/api -c api -- \
  python -m protohub.accounts add "$MEMBER_EMAIL"
```

Gmail・Google Workspace アカウントは初回の本人確認で結び付きます。それ以外のメールアドレスを使う Google アカウントは、管理者が本人の Google subject を独立に確認し、上の `add` に `--subject "$VERIFIED_GOOGLE_SUB"` を付けます。ログイン試験では、この登録者と、登録していない別のアカウントの両方を使います。[Google アカウントの登録・解除](GOOGLE_LOGIN.md)

Cloud DNS を最初から選んだ新規ノードでも、旧 `kube-dns` とその autoscaler が残る場合があります。追加の CPU が必要な場合は、NodeLocal DNS のクラスタドメイン転送先とノードの DNS 設定、独自の DNS 設定の有無を先に確認します。DB Pod から Kubernetes と DB の Service 名を引き、旧 Deployment のレプリカ数を記録します。Google の手順で旧 autoscaler と旧 DNS を順に 0 にする場合は、NodeLocal DNS のキャッシュ期限後にも両方の名前と新規 headless Service の名前を検証してください。名前解決に失敗したら、旧 DNS と autoscaler を保存した数に戻します。NodeLocal DNS と Cloud DNS は稼働させたままにします。[Cloud DNS の動作と旧 kube-dns](https://docs.cloud.google.com/kubernetes-engine/docs/how-to/cloud-dns)

## 4. 転送を検証してから公開する

VPC ファイアウォールと Kubernetes の NetworkPolicy は別々に適用されます。専用の Cloud Run サブネットから GKE ノード用サービスアカウント宛に TCP 8080/8081 だけを許可します。既存同名ルールがあれば、ネットワーク・送信元・ポート・対象アカウントを照合してください。

```bash
gcloud compute firewall-rules create "$EDGE_RULE" --project="$PROJECT" --network="$NETWORK" \
  --direction=INGRESS --source-ranges="$RUN_CIDR" --target-service-accounts="$NODE_SA" --allow=tcp:8080,tcp:8081
```

管理者が Cloud Run 専用サブネットから web と preview のみへの通信を許可します。生成するのは2つの headless Service と、それぞれの通信を許可する NetworkPolicy です。DB・Kubernetes API・サンプル Pod を公開用の転送先にしません。

```bash
BRIDGE=(--edge-cidr "$RUN_CIDR" --console-origin "$CONSOLE_ORIGIN" --preview-origin "$PREVIEW_ORIGIN" --owner "$OWNER")
python3 infra/managed/run_bridge.py "${BRIDGE[@]}" > worklogs/run-bridge.yaml
python3 infra/managed/run_bridge.py "${BRIDGE[@]}" --apply-context "$CTX"

# プロファイル、所有 UID、匿名拒否をライブ置換の直前にも照合する。
python3 infra/managed/run_proxy.py verify "${PAIR[@]}" --web-url "$CONSOLE_ORIGIN" --preview-url "$PREVIEW_ORIGIN" --stage parked
python3 infra/managed/run_proxy.py --role web --service "$WEB_SERVICE" "${EDGE[@]}" --live > worklogs/run-web.yaml
python3 infra/managed/run_proxy.py --role preview --service "$PREVIEW_SERVICE" "${EDGE[@]}" --live > worklogs/run-preview.yaml
gcloud run services replace worklogs/run-web.yaml --project="$PROJECT" --region="$REGION"
gcloud run services replace worklogs/run-preview.yaml --project="$PROJECT" --region="$REGION"
python3 infra/managed/run_proxy.py verify "${PAIR[@]}" --web-url "$CONSOLE_ORIGIN" --preview-url "$PREVIEW_ORIGIN" --stage live-private
```

非公開状態で web が正しい Google 認証構成を返し、API とプレビューが匿名リクエストを拒否することを確認します。その後に限り、入口の2サービスにインターネット呼び出しを許可し、同じ検査を外部から行います。組織ポリシーで拒否されたら管理者と確認してください。登録したユーザーと未登録ユーザーを実ブラウザで試し、共有解除・登録解除後の拒否まで記録します。

```bash
set -eu
close_edge() {
  local restore_failed=0
  for service in "$WEB_SERVICE" "$PREVIEW_SERVICE"; do
    gcloud run services update "$service" --project="$PROJECT" --region="$REGION" --invoker-iam-check || restore_failed=1
  done
  if (( restore_failed )); then
    echo "Both restores were attempted. Check each service's IAM immediately." >&2
    return 1
  fi
  python3 infra/managed/run_proxy.py verify "${PAIR[@]}" --web-url "$CONSOLE_ORIGIN" --preview-url "$PREVIEW_ORIGIN" --stage live-private
}
if ! gcloud run services update "$WEB_SERVICE" --project="$PROJECT" --region="$REGION" --no-invoker-iam-check ||
   ! gcloud run services update "$PREVIEW_SERVICE" --project="$PROJECT" --region="$REGION" --no-invoker-iam-check ||
   ! python3 infra/managed/run_proxy.py verify "${PAIR[@]}" --web-url "$CONSOLE_ORIGIN" --preview-url "$PREVIEW_ORIGIN" --stage live-public; then
  close_edge
  exit 1
fi
```

サービスへの allUsers / allAuthenticatedUsers の IAM 付与は使いません。更新時は2サービスへ `--invoker-iam-check` を戻して匿名 403 を確認し、対象の bridge policy を外して旧アプリへの到達が停止したことを確認してから認証境界を変更します。headless Service の削除だけでは DNS キャッシュ中の Pod を遮断できないので、対象の NetworkPolicy と外部 HTTP 応答の両方を確認してください。新しい rollout、bridge、非公開プローブを検証して再公開します。管理者は配備と公開操作を直列に行います。Cloud Run のサービスを保持すれば同じ URL を再利用できます。

## Gemini連携を有効にして更新する

[Gemini連携の仕様](GEMINI_CREATION.md)に沿ってVertex APIと、API専用KSAの
直接Workload Identity権限を準備する。renderの既存引数に
`--ai-project "$PROJECT" --ai-location global --ai-model gemini-3.5-flash-lite` を加える。
出力されたAPI PodのKSAが `protohub-api` で、Kubernetes tokenをmountしないことを確認する。
worker、preview、web、サンプルへモデル権限やキーを配布しない。

Cloud Buildのsource allowlistとmigration0004を含むイメージを検証してから、
本書の既存更新手順で公開入口を一時的に閉じ、DB/PVC/OAuth Secretを保持して更新する。
`/api/v1/system` の `ai_enabled` と `ai_model` は非秘密の利用可能情報である。
実API PodからADCで1回の小さなGemini生成を観測し、匿名の生成要求が401で拒否されること、
保存・確認・再読込を検証する。実Geminiの証拠をmockや固定の成功応答で置き換えない。
