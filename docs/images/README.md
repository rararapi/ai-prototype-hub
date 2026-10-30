# READMEの生成イラスト

GitHubのREADMEで、ProtoHub v0のコンセプトと論理構成を説明するための画像です。
実画面・動作証跡ではありません。仕様の正本は [MVP_SPEC.md](../MVP_SPEC.md)、
実検証の到達点は [VALIDATION.md](../VALIDATION.md) を参照してください。

| ファイル | 目的 |
| --- | --- |
| [protohub-concept.png](protohub-concept.png) | 信頼済みサンプルの登録・起動・URL操作・停止・削除 |
| [protohub-architecture.png](protohub-architecture.png) | 管理画面・API・PostgreSQL・Worker・RuntimeProviderと、mock/real-kindの違い |

2026-10-30に内蔵の `image_gen` ツールで新規生成しました。外部API用CLI、実APIキー、
実画面のキャプチャは使用していません。生成されたPNGをそのままリポジトリに保存しています。
画像内のReadyは概念上の状態で、テスト合格の宣言ではありません。
アプリ用AIエージェント、任意コード実行、クラウド公開、悪性コード隔離を表しません。

## 再生成用プロンプト

以下は採用画像の生成時に使用したプロンプトです。同じプロンプトでも再生成結果は変わり得ます。

### コンセプト図

```text
Use case: infographic-diagram.
Asset type: GitHub README concept illustration for the existing ProtoHub repository. Produce one finished landscape image, ideally 1536x864, opaque background.
Primary request: Explain a localhost-only MVP that lets a developer register a trusted sample web app, start it, open its URL when Ready, then stop or delete that app. This is a concept illustration, not an actual screenshot.
Style: precise editorial product illustration; crisp, sophisticated, mostly flat illustrated objects with very subtle volume and restrained linework. Use the existing product palette: cool off-white #f5f6f8, white cards, charcoal #242736, purple #6750b6, muted green for Ready. Generous whitespace, strong hierarchy, readable Japanese sans-serif text. No stock-photo look, no neon gradients, no robot or AI chat imagery.
Composition: wide, balanced README cover. At top a large exact wordmark "ProtoHub" and a clear short Japanese headline. Center: one stylized local laptop showing two separate simple sample-app cards, with a small browser-window illustration connected to a Ready card to express opening a URL. Use an illustrative rather than pixel-perfect screenshot treatment. The cards are generic symbols, not fabricated live telemetry. At bottom, four clearly ordered, numbered steps connected left-to-right by arrows, each with a large simple pictogram and exact Japanese label. All type must remain legible when displayed at 900px wide.
Text (verbatim only, no extra labels):
"ProtoHub"
"信頼済みサンプルを、ローカルですぐ試す。"
"LOCAL MVP"
"App A"
"App B"
"Ready"
"1 登録"
"2 起動"
"3 URLで操作"
"4 停止・削除"
Constraints: Japanese characters must be correct and clean. Use the label Ready only as a conceptual card state, never as a verified test result. Show each app as its own card without locks or claims of hostile-code isolation. No cloud, deployment-to-internet, auth, arbitrary-code upload, AI agent, chat bubble, LLM, model name, Kubernetes logo, extra marketing claims, fabricated metrics, or URLs. Do not imply deletion removes the database. No watermark. Keep the full composition inside safe margins.
```

### 論理構成図

```text
Use case: infographic-diagram.
Asset type: explanatory architecture illustration for a GitHub README, second image in a coordinated pair for ProtoHub. One finished landscape image, approximately 1536x864, opaque cool off-white background.
Primary request: Explain the logical flow of the existing localhost-only trusted-template MVP: management UI → API → PostgreSQL operation queue → separate worker → RuntimeProvider. RuntimeProvider has two explicit adapters: mock simulates state and launches no app; real-kind manages actual trusted sample Pods and a Preview route. This is a logical architecture illustration, not a deployment topology map and not a screenshot or test result.
Style/medium: precise editorial technical illustration; crisp clean cards, purposeful thin connector lines and arrowheads, simple database/worker/browser/container pictograms. Match existing brand: off-white #f5f6f8, white cards, charcoal #242736, purple #6750b6, restrained muted green. Generous whitespace, no neon or cloud imagery. Large legible Japanese/English sans-serif labels, readable at 900px display width.
Composition: top title "ProtoHub のしくみ". Upper-middle row has EXACTLY FIVE distinct equally prominent cards connected LEFT TO RIGHT in the order below. These cards represent responsibilities, not separate hosts:
1. browser icon and "管理画面";
2. API icon and "API";
3. database cylinder, "PostgreSQL", sublabel "操作キュー";
4. gear icon, "Worker", sublabel "leaseで取得";
5. adapter icon and "RuntimeProvider".
From ONLY the RuntimeProvider card draw a clear fork to TWO large alternative cards below. Left alternative: "mock" heading, "状態を模擬" and "実アプリなし", a quiet outlined placeholder rather than a running browser or Pod. Right alternative: "real-kind" heading, "実Pod + Preview" and "信頼済みサンプル", two simple app-container icons with a small browser icon to represent real sample interaction. Make both mode labels equally clear. Add a small top subtitle "起動要求の流れ". All arrows must have obvious endpoints and no crossing through text.
Text (verbatim, no other labels):
"ProtoHub のしくみ"
"起動要求の流れ"
"管理画面"
"API"
"PostgreSQL"
"操作キュー"
"Worker"
"leaseで取得"
"RuntimeProvider"
"mock"
"状態を模擬"
"実アプリなし"
"real-kind"
"実Pod + Preview"
"信頼済みサンプル"
Constraints: Japanese and uncommon identifiers spelled exactly. The database is PostgreSQL, never Redis. API and worker are distinct. The mock branch must NOT show a running app, URL or Preview. Do not draw cloud services, Redis, Docker socket, arbitrary uploaded code, authentication, AI chat/robot/LLM, model names, internet publication, a security isolation guarantee, verification pass badges, or fabricated metrics. Do not depict deletion of the database. Do not enclose only the sample in a boundary labeled kind: the figure is logical; real-kind actually also hosts control services. Keep full image within generous safe margins. No watermark.
```

