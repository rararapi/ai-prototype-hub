# READMEの図と生成プロンプト

利用者とエンジニアで読む目的を分け、v2では構成から描き直しました。
実画面のキャプチャ・動作証跡ではありません。仕様の正本は [MVP_SPEC.md](../MVP_SPEC.md)、
実検証の到達点は [VALIDATION.md](../VALIDATION.md) を参照してください。

| ファイル | 読む人 | 図で伝えること |
| --- | --- | --- |
| [protohub-concept.png](protohub-concept.png) | 初めて使う人 | 登録フォーム、起動待ち、Ready後にサンプルを開いてカウンターボタンを押す体験と、アプリごとの停止・起動・削除 |
| [protohub-architecture.png](protohub-architecture.png) | 実装を読むエンジニア | 管理操作・非同期制御・サンプル操作の3つの通信経路、kindのnamespace別配置、job制御、別構成のmock/Compose |

2026-10-30に内蔵の `image_gen` ツールで編集生成し、採用PNGをそのまま保存しました。
元のv1画像はcommit `696ae83` の同じpathにあります。利用者向けは管理画面とサンプルを
簡略化した操作例です。テンプレート名・サンプル名・カウンター・操作ラベルを実装と照合しています。
構成図では同じコンポーネントを経路ごとに再掲します。たとえばDBは共通で、経路ごとの別DBではありません。
PNG内のReadyや接続線は実kind検証の合格を表しません。

## 再生成手順

以下は採用画像に使用したプロンプトです。操作図はv1画像を参照して全体構成を編集しました。構成図はv1から3段の通信図を生成し、
その出力に対して、同一コンポーネントの再掲とWorkerのServiceAccount所属の表記を修正しました。
同じ入力でも再生成結果は変わり得るため、採用前に文字・接続先・仕様を確認します。
外部API用CLIや実APIキーは使用していません。

詳細構成の途中案では接続線が重なり誤解を生んだため採用せず、通信経路を3段に分ける
構成へ変更しました。採用図ではHTTPがPreview → Service → Podの順であること、
WorkerのKubernetes制御とSQLアクセスが区別できること、mockのmigrationがAPI通信の
中継点にならないことを確認します。

### 利用者向け：登録して実際に試す操作例

参照画像: v1の `protohub-concept.png`。

```text
Use case: infographic-diagram, full composition revision of an existing README illustration.
Edit target: the referenced ProtoHub concept image. Replace the entire vague laptop/desk composition with a concrete THREE-PANEL PRODUCT STORYBOARD. Preserve only brand identity, cool off-white background #f5f6f8, purple management controls #6750b6, charcoal text, and green Ready. Remove the desk, plant, laptop hardware, generic landscape webpage, oversized logo, and icon-only flow.
Primary goal: A new visitor should immediately understand what the product lets them DO and what happens after they click. Show an actual example: register the trusted Hello Web template as デモA, start it, wait for Ready, open the sample, click its counter button; later stop one app while another stays running. This is a conceptual illustration of the real-kind mode, not a screenshot or runtime test result.
Canvas: wide landscape around 2000x1250, highly legible, crisp flat editorial diagram with large Japanese labels and clean simplified UI panels. No tiny text or decorative props. Header occupies only 12% height. Main three panels occupy 62%; practical per-app management footer 26%. Visible arrows connect the panels left-to-right. Panel3 should be the largest (~40% width), showing the concrete outcome.
Header exact: "サンプルを起動して、ブラウザで操作できる" with small "ProtoHub / real-kind".
PANEL1 heading "1 登録する". A simplified actual registration form: label "アプリ名", value "デモA"; label "テンプレート", value "Hello Web"; a purple text button "登録". No code editor, arbitrary upload, or invented template choices.
PANEL2 heading "2 起動を待つ". Same app "デモA", clear purple text button "起動", arrow to an amber status "起動中". A small waiting indicator conveys asynchronous startup; this panel has no Preview yet.
PANEL3 heading "3 開いて試す". Same app "デモA", green "Ready", purple button "アプリを開く", then a DOWNWARD arrow into a distinct BLUE SAMPLE browser window (blue #285ed0, pale-blue #eef4fc). It has exact title "Hello ProtoHub". Its large counter button shows "Clicked 0 times" transitioning by a click/cursor arrow to "Clicked 1 times". This is the actual sample behavior; the value is an example, not recorded telemetry. The browser app is a working counter, NOT a generic marketing page. Add short text "ボタンを押すと反応" near the click to make the payoff obvious.
FOOTER, clearly separated and introduced by "使ったあとは、アプリごとに管理". Show TWO compact management rows after stopping the first app:
"デモA" with status "停止中" and labeled buttons "起動" and "削除".
"デモB" with green status "Ready" and labeled buttons "停止" and "削除".
Alongside them, short outcome statements "停止後も、また起動できます" and "デモAを止めても、デモBはそのまま".
Constraints: Render all specified Japanese correctly, no placeholder gray lines instead of meaningful UI. No separate '再起動' button (actual UI restarts by 起動). Show Ready only AFTER waiting, and open only after Ready. Generic names デモA/デモB are trusted instances of the same fixed Hello Web template, not arbitrary different apps. Do not show AI chat, generation, cloud/public hosting, security locks, malicious-code isolation, tests passed, fabricated API metrics, URLs, or database removal. Keep exact sample title and counter English; actual sample uses plural "1 times". Whole composition within generous safe margins, no watermark.
```

### エンジニア向け：通信経路と配置

参照画像: v1の `protohub-architecture.png`。

```text
Use case: infographic-diagram. Full recomposition of the reference architecture illustration for engineering readers.
Preserve ONLY its off-white/purple/charcoal palette and crisp label style. Do not retain any previous node placement. Make a fresh, readable diagram with THREE SEPARATE HORIZONTAL COMMUNICATION LANES and a compact deployment inventory beneath. No shared connector buses, no crossing arrows, no ambiguous topology lines. Landscape about 1800x1400, readable text, flat technical diagram, minimal icons, no giant logo.
Title: "ProtoHub — 通信経路と配置（real-kind）".
Small legend: "青: HTTP / 灰: SQL / 紫点線: Kubernetes API".
Important: the same components are repeated by route, not duplicate running services. Say "経路ごとに同じコンポーネントを再掲".
LANE 1 title "1 管理画面の操作・状態取得".
Four large boxes aligned left-to-right:
A "Browser / React UI" and "127.0.0.1:8080";
B "Web / nginx :8080" and "NodePort 30080";
C "FastAPI :8000" and "/api/v1/*" and "202 = accepted";
D "PostgreSQL :5432" and "sandboxes / operations / audit_events".
Connections ONLY A→B and B→C in BLUE HTTP, C↔D in GRAY SQL. Label B→C "/api/* proxy"; label C↔D "intent + operation / transaction". Add small note "状態はAPIからpoll". Do not expose API/DB to host.
LANE 2 title "2 非同期ジョブ・Kubernetes制御".
Four large boxes aligned left-to-right:
A "同じPostgreSQL" and "operations = job queue";
B "Worker / RuntimeProvider" and "claim / heartbeat / reconcile / TTL";
C "Kubernetes API" and "in-cluster ServiceAccount" and "protohub-worker";
D "protohub-samples" and "Deployment / Service" and "Pod: get / list only".
Connections ONLY A↔B in GRAY SQL; B→C and C→D in DASHED PURPLE control. Label gray connection "lease_token + generation + valid lease". Label last connection "scoped RBAC". No arrow between this lane and lane3; observed HTTP is stated separately below.
LANE 3 title "3 ブラウザでサンプルを操作".
Four large boxes aligned left-to-right:
A "Browser" and "127.0.0.1:8081" and "/apps/<UUID>/";
B "Preview :8081" and "NodePort 30081" and "GET / HEAD + DB state check";
C "Service :8080" and "sandbox-<uuid.hex>";
D "Pod :8080" and "Hello ProtoHub".
EXACTLY THREE BLUE HTTP ARROWS, left-to-right: Browser→Preview→Service→Pod. There is NO Deployment in the HTTP path. This row is the most important traffic path. No HTTP arrow Pod→Service. No direct Preview→Pod. No cross-app arrows.
BOTTOM: Three compact informational panels WITHOUT connector arrows:
Panel "kind内の配置": "protohub-system: web / api / db / worker / preview"; "PVC: protohub-db / 1Gi"; "protohub-samples: UUIDごとのDeployment / Service / ReplicaSet / Pod"; "Kubernetes API: control plane（namespace外）". A small sentence "全サービスとサンプルはkind内" makes physical deployment clear; browsers remain on host.
Panel "jobと状態": "FOR UPDATE SKIP LOCKED"; "Ready = rollout + Pod Ready + Service /healthz"; "Worker checks HTTP directly via Service"; "stop: replicas=0"; "delete: Deployment + Service"; "DB records retained". No microscopic explanatory paragraphs.
Panel "別モード: mock / Compose": A TEXT LIST, no arrows: "Web / API / Worker(MockRuntime) / PostgreSQL + volume"; "migrate: separate one-shot"; "実Podなし・Preview URLなし". Do NOT draw API→migrate→DB, since migration is a separate setup task, not an API request hop.
Constraints: labels and ports exactly as specified. The rows are logical communication paths; placement is summarized in the bottom inventory, not by crossing topology boundaries. Do not add extra components. No Redis, Ingress, external cloud, AI/chat, test-pass badges, public API/DB, direct worker Pod creation, hostile-code isolation claims or DB deletion. All labels inside boxes, arrows only in each row with explicit endpoints. Keep all text sharp and usable at full-image view. No watermark.
```

### 詳細構成：注記とWorkerのServiceAccount表記を明確化

参照画像: 上記の3段の通信図。

```text
undefined
```

