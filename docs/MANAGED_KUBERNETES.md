# GKE に配備し、同じ構成を AKS に移す

新規の GKE Standard に実サンプルを配備し、管理者が登録した Google アカウントにだけ利用を許可します。クラスターの管理 API・ノード・DB は非公開です。インターネットから使う場合は、コンソールとプレビューに専用の外部 HTTPS Gateway を明示して作成します。一般ユーザーはブラウザで Google にログインします。[Google ログインと公開手順](GOOGLE_LOGIN.md)

独自ドメインなしで東京に配置する場合は [標準 URL 手順](RUN_APP.md) を使います。Cloud Run から GKE に直接接続するため、以下の外部 Gateway・TLS 証明書の準備は独自ドメインを使う場合だけ必要です。

## 最初に用意するもの

| 担当 | 必要なもの |
| --- | --- |
| プロジェクト管理者 | 課金を有効にした Google Cloud プロジェクト、リージョン・ゾーン、予算、利用期間。費用の対象は GKE 管理料、ノード VM、ディスク、レジストリ、通信です。予算アラートは通知用です。 |
| ネットワーク管理者 | VPC とサブネット、Pod・Service のセカンダリ範囲、重複しない制御プレーン用 /28、許可する管理端末の CIDR、Private Google Access。端末から VPN 等を経由して非公開 API に接続できることを確認します。 |
| プラットフォーム管理者 | 専用の GKE Standard、非公開の Artifact Registry、ノード用サービスアカウント、RWO を扱う承認済み CSI StorageClass。専用クラスター内の protohub-system と protohub-samples をこの配備に確保します。 |
| 開発者 | レビュー済みソース、Bash、Python 3.10 以降と PyYAML、Docker Buildx、gcloud、gke-gcloud-auth-plugin、kubectl。ビルドには linux/amd64 用のイメージを作れる環境が必要です。 |

以降はリポジトリ直下で実行します。大文字のシェル変数には管理者が選んだ値を設定します。PROJECT はプロジェクト ID、LOCATION は単一ゾーン、REGION はそのゾーンのリージョンです。既存の専用クラスターとリポジトリがある場合は次の作成手順を飛ばしてください。

## 管理者が承認後に用意するリソース

専用の node サービスアカウントと、Private Google Access が有効な同一プロジェクトのサブネットを用意します。サブネットには Pod と Service に割り当てる2つのセカンダリ範囲を用意します。管理 CIDR は非公開 API に到達できる運用端末の範囲です。アプリ利用者には付与しません。

```bash
gcloud services enable container.googleapis.com artifactregistry.googleapis.com compute.googleapis.com iam.googleapis.com --project="$PROJECT"
gcloud iam service-accounts create "$NODE_SA_NAME" --project="$PROJECT"
NODE_SA="${NODE_SA_NAME}@${PROJECT}.iam.gserviceaccount.com"
gcloud projects add-iam-policy-binding "$PROJECT" --member="serviceAccount:$NODE_SA" --role=roles/container.defaultNodeServiceAccount

GKE_ARGS=(--project "$PROJECT" --zone "$LOCATION" --cluster "$CLUSTER" --network "$NETWORK"
          --subnet "$SUBNET" --pod-range "$POD_RANGE" --service-range "$SVC_RANGE"
          --master-cidr "$MASTER_CIDR" --admin-cidr "$ADMIN_CIDR" --node-service-account "$NODE_SA"
          --registry "$REPOSITORY" --writer-member "$WRITER_MEMBER" --owner "$OWNER")
python3 infra/managed/new_gke.py "${GKE_ARGS[@]}"
```

`WRITER_MEMBER` は承認されたビルド担当者の `user:メール` または専用の `serviceAccount:メール` です。上の Python コマンドは予定を表示するだけです。予算、期間、ネットワーク、レジストリへの書き込み権限を確認したら、管理者が次を実行します。

```bash
python3 infra/managed/new_gke.py "${GKE_ARGS[@]}" --create
```

新規作成するのは専用の Artifact Registry と、単一ゾーン・1ノードの GKE Standard です。ノードは e2-standard-2、ブートディスクは 50 GB の pd-balanced を指定しています。Gateway API は有効になりますが、公開ロードバランサーは別手順で作成します。同じ設定・所有者で再実行でき、所有者か設定が異なる同名資源は引き継ぎません。既存企業ネットワークに適用する場合は CIDR と接続経路をネットワーク管理者が確認してください。

ノードの IAM と Kubernetes の worker ServiceAccount は別々に管理します。ノードにはレジストリの読み取り権限、アップロード担当者には対象リポジトリの `roles/artifactregistry.writer`、接続担当者には `roles/container.clusterViewer` と用途別の Kubernetes RBAC を割り当てます。インストール担当者には専用 namespace、Role/RoleBinding、ポリシー、アプリリソース、Secret の作成・検査などに必要な権限を付与してください。配備担当者は専用リソースの get/create と既存リソースの patch（server dry-run）・update に加え、StorageClass の get と必要な RBAC の付与権限を持ちます。稼働中のアプリには Google IAM 権限を付与しません。Private Google Access、DNS、ファイアウォールでノードから Artifact Registry に到達できることも確認してください。[GKE ネットワーク](https://docs.cloud.google.com/kubernetes-engine/docs/how-to/latest/network-isolation) · [ノード IAM](https://docs.cloud.google.com/kubernetes-engine/security/configure-node-service-accounts) · [GKE 料金](https://cloud.google.com/kubernetes-engine/pricing)

## レジストリに4つのイメージを用意する

リポジトリ直下で、承認された宛先に push します。`TAG` に今回専用のリリースタグを指定します。ビルド端末から Docker Hub、GHCR、npm、Python パッケージ配布元に接続できることを確認してください。サーバーの Dockerfile では配備用の `runtime` ステージを指定します。

```bash
set -eu
REG="${REGION}-docker.pkg.dev/${PROJECT}/${REPOSITORY}"
gcloud auth configure-docker "${REGION}-docker.pkg.dev"
docker buildx build --platform linux/amd64 --target runtime -f infra/docker/server.Dockerfile --push -t "$REG/server:$TAG" .
docker buildx build --platform linux/amd64 -f infra/docker/web.Dockerfile --push -t "$REG/web:$TAG" .
docker buildx build --platform linux/amd64 -f examples/hello-web/Dockerfile --push -t "$REG/hello-web:$TAG" .
PG_SRC=$(awk '$1 == "image:" && $2 ~ /^postgres:.*@sha256:/ {print $2}' infra/kubernetes/stack.yaml.in)
test -n "$PG_SRC"
docker pull --platform linux/amd64 "$PG_SRC"
docker tag "$PG_SRC" "$REG/postgres:$TAG"
docker push "$REG/postgres:$TAG"

ref() {
  local image="$REG/$1" digest
  digest=$(gcloud artifacts docker images describe "$image:$TAG" --project="$PROJECT" --format='value(image_summary.digest)') || return 1
  [[ $digest =~ ^sha256:[0-9a-f]{64}$ ]] || return 1
  printf '%s@%s\n' "$image" "$digest"
}
SERVER_IMAGE=$(ref server)
WEB_IMAGE=$(ref web)
SAMPLE_IMAGE=$(ref hello-web)
POSTGRES_IMAGE=$(ref postgres)
```

4つの digest とビルドしたソースの識別子を記録します。新しいサンプルイメージを配備した際は worker の rollout 完了を確認し、サンプルを再起動して新しいバージョンを試します。[GKE のコンテナイメージ](https://docs.cloud.google.com/kubernetes-engine/docs/concepts/about-container-images)

## レンダリング・配備

VPN 等を接続した端末で実行します。`STORAGE_CLASS` は承認済みの CSI クラス名、`OWNER` はこの配置固有の短い小文字英数字・ハイフンの識別子です。再適用でも同じ値を使います。ノードは Linux/amd64、クラスター DNS ドメインは `cluster.local` が前提です。

```bash
umask 077
mkdir -p worklogs
export KUBECONFIG="$PWD/worklogs/managed-gke.kubeconfig"
gcloud container clusters get-credentials "$CLUSTER" --project="$PROJECT" --zone="$LOCATION" --internal-ip
CTX=$(kubectl config current-context)
printf '配備先コンテキスト %s\n' "$CTX"
kubectl --context "$CTX" get storageclass "$STORAGE_CLASS"
python3 harness/run.py --group managed
python3 infra/managed/render.py --server-image "$SERVER_IMAGE" --web-image "$WEB_IMAGE" \
  --sample-image "$SAMPLE_IMAGE" --postgres-image "$POSTGRES_IMAGE" \
  --storage-class "$STORAGE_CLASS" --owner "$OWNER" \
  --console-origin "$CONSOLE_ORIGIN" --preview-origin "$PREVIEW_ORIGIN" > worklogs/managed.yaml
python3 infra/managed/deploy.py --context "$CTX" --manifest worklogs/managed.yaml --configure-google
for service in db api worker preview web; do
  kubectl --context "$CTX" -n protohub-system rollout status "deploy/$service" --timeout=5m
done
kubectl --context "$CTX" -n protohub-system get pods,svc,pvc
```

全 Service が ClusterIP、DB の PVC が Bound、各 Deployment が Ready であることを確認します。DB の Secret は初回だけ生成されます。再試行時に既存の PVC に対応する Secret が失われていれば配備は停止します。元の Secret をバックアップから復元してください。既存オブジェクトの変更・削除が進行中の場合は、その所有者と状態を確認してから再実行します。専用 namespace の削除や再作成は配備と同時に行わないでください。

## ブラウザから実サンプルを確認する

インターネット利用は [HTTPS の公開と Google アカウント登録](GOOGLE_LOGIN.md) に従います。以下は管理者のローカル試験だけに使う代替手順です。localhost で試すときは render.py の2つの origin 引数を省略し、OAuth クライアントにも localhost を登録してください。

接続担当者に `protohub-system` の Service の get、Pod の get/list/watch、`pods/portforward` の get/create を許可します。この権限は namespace 内の他の Pod にも使えるため、信頼された担当者に限定します。2つの端末で同じ `KUBECONFIG` と `CTX` を設定して、それぞれ次を実行します。

```bash
kubectl --context "$CTX" -n protohub-system port-forward --address 127.0.0.1 service/web 8080:8080
```

```bash
kubectl --context "$CTX" -n protohub-system port-forward --address 127.0.0.1 service/preview 8081:8081
```

管理画面の Origin は `http://localhost:8080`、プレビューは `http://localhost:8081` です。固定ポートが既に使われている場合は別の端末を使うか、競合しているプロセスの持ち主に確認してください。Pod の入れ替えで転送が切れたら同じコマンドで再接続します。[kubectl port-forward](https://kubernetes.io/docs/reference/kubectl/generated/kubectl_port-forward/)

実クラスターでの受け入れ条件は以下です。

1. 管理者が追加した Google アカウントでログインし、固定テンプレート `hello-web` を登録します。初期状態は停止中です。
2. 「起動」を選び、Pod が Ready、管理画面が running になってから認証付きプレビューで実サンプルのカウンターを操作します。API の `real-kind` は Kubernetes 実行モードの既存識別子です。ここでは GKE の Pod が応答します。
3. 停止して Pod の終了とプレビューの無効化を確認します。再起動後に削除し、`kubectl --context "$CTX" -n protohub-samples get deployment,service,pod -l "protohub.io/sandbox-id=$SANDBOX_ID"` で対象リソースの消失を確認します。
4. CNI の実通信は管理者が承認したテストで検証します。worker/preview からサンプルの TCP 8080 へは到達し、無許可 Pod から同ポートへ、またサンプルから DB の TCP 5432 へは到達しないことを対照試験とともに記録します。ポリシーは Pod 間の通信を対象にします。ノード・制御プレーンを経由する probe や port-forward は別の経路です。システム側 worker は DNS と Kubernetes API に接続します。

クラウドの実測結果はソース識別子、イメージ digest、Ready・HTTP・停止・削除の結果とともに `worklogs/` に記録します。kubeconfig、Secret、セッショントークンは結果に含めません。

## 停止・再開と費用

まずアプリをすべて停止し、サンプル Pod の終了を確認します。端末の転送は Ctrl+C で終了します。開発環境全体を一時停止する場合は、運用担当者が次の順で停止・再開できます。PVC と DB Secret は保持します。

```bash
# 一時停止
kubectl --context "$CTX" -n protohub-system scale deploy/web deploy/preview deploy/api deploy/worker --replicas=0
kubectl --context "$CTX" -n protohub-system scale deploy/db --replicas=0
# 利用を再開するとき
kubectl --context "$CTX" -n protohub-system scale deploy/db --replicas=1
kubectl --context "$CTX" -n protohub-system rollout status deploy/db --timeout=3m
kubectl --context "$CTX" -n protohub-system scale deploy/api deploy/worker deploy/preview deploy/web --replicas=1
```

クラスター、ノード、ディスク、バックアップ、レジストリには停止後も料金が発生し得ます。完全廃止は対象ごとの所有者、保存期間、バックアップと復元を確認してから行ってください。DB を復旧する場合は整合した PostgreSQL バックアップまたは CSI スナップショットと対応する Secret を用意し、別の専用環境で復元を検証します。

## AKS に移すときの差分

| GKE 側 | AKS 側で用意するもの |
| --- | --- |
| Private GKE、Dataplane V2 | Private AKS、接続用 VNet/VPN と private DNS、Entra ID 認証、NetworkPolicy を強制する CNI |
| Artifact Registry と node SA | 非公開 ACR と kubelet マネージド ID。通常の ACR は `AcrPull`、ABAC 付き ACR は `Container Registry Repository Reader`。アップロード担当は別権限。 |
| GCE PD CSI の StorageClass | Azure Disk CSI (`disk.csi.azure.com`) で RWO を扱う StorageClass。実クラス名と reclaim policy を確認。 |
| GKE クラスター接続権限、Kubernetes RBAC | `Azure Kubernetes Service Cluster User Role` で kubeconfig を取得し、Azure RBAC または Kubernetes RBAC で必要な操作を個別に許可。 |

```bash
umask 077
mkdir -p worklogs
export KUBECONFIG="$PWD/worklogs/managed-aks.kubeconfig"
az login
az aks get-credentials --subscription "$SUBSCRIPTION" --resource-group "$RG" --name "$AKS_CLUSTER" --file "$KUBECONFIG"
kubelogin convert-kubeconfig -l azurecli
CTX=$(kubectl config current-context)
kubectl --context "$CTX" get storageclass "$STORAGE_CLASS"
```

ACR に同じ4イメージを登録し、ACR 側の digest と AKS の StorageClass を `render.py` に渡します。以降の配備・転送・実サンプルの確認は GKE と共通です。GKE のデータを引き継ぐ場合は、PostgreSQL のバックアップ転送と復元が別途必要です。[AKS プライベート接続](https://learn.microsoft.com/en-us/azure/aks/private-cluster-connect) · [AKS の kubeconfig](https://learn.microsoft.com/en-us/azure/aks/control-kubeconfig-access) · [ACR 権限](https://learn.microsoft.com/en-us/azure/aks/cluster-container-registry-integration) · [Azure Disk CSI](https://learn.microsoft.com/en-us/azure/aks/azure-disk-csi)
