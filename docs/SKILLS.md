# ProtoHubの開発スキル

ProtoHubのUI設計・React実装・レビューと、実装から実検証までの進め方を揃えるため、
外部4件と、このリポジトリ専用の1件に絞る。開発者のCodexで使うものであり、
サンプルアプリのコンテナやProtoHubの利用者向け実行機能に読み込ませるものではない。

配置はプロジェクト内の `.agents/skills/`。取得元、固定commit、導入名、ファイルhash、
ライセンスの宣言とローカル変更は [harness/skills.lock.json](../harness/skills.lock.json)
を正本とする。上流の更新を自動追従させず、変更を確認してから取り込む。
導入されたスキルをCodexが認識するのは、原則として次のターン／新しいセッションから。

## 選定したスキル

| スキル名 | 担当すること | ProtoHubでの使いどころ | 上流とライセンス |
| --- | --- | --- | --- |
| `frontend-design` | 内容に合う視覚方針、文字組み、配色、レイアウト | 新画面や大きなUI変更の設計。見た目の方針を先に決める | [Anthropicの原本](https://github.com/anthropics/skills/blob/ca45fc496a3436251f191354091d557da31c15b5/skills/frontend-design/SKILL.md)、[Apache-2.0全文](https://github.com/anthropics/skills/blob/ca45fc496a3436251f191354091d557da31c15b5/skills/frontend-design/LICENSE.txt) |
| `vercel-react-best-practices` | Reactのデータ取得、描画、再描画、bundleの改善 | React/TypeScriptの実装と性能上のレビュー | [Vercelの原本](https://github.com/vercel-labs/agent-skills/blob/1a2c79d4e6c4a2283dc2c614b6538cbe1ed5ca62/skills/react-best-practices/SKILL.md)、MIT宣言 |
| `web-design-guidelines` | UIの操作性、focus、form、アクセシビリティ等のレビュー | 実装後のUIレビュー。指摘は対象ファイルと行を付ける | [Vercelの原本](https://github.com/vercel-labs/agent-skills/blob/1a2c79d4e6c4a2283dc2c614b6538cbe1ed5ca62/skills/web-design-guidelines/SKILL.md)、[上流READMEのMIT宣言](https://github.com/vercel-labs/agent-skills/blob/1a2c79d4e6c4a2283dc2c614b6538cbe1ed5ca62/README.md#license) |
| `security-best-practices` | Python/JavaScript/TypeScript等の安全な実装とセキュリティレビュー | セキュリティレビューや安全な実装を明示的に依頼したとき | [OpenAIの原本](https://github.com/openai/skills/blob/49f948faa9258a0c61caceaf225e179651397431/skills/.curated/security-best-practices/SKILL.md)、[Apache-2.0全文](https://github.com/openai/skills/blob/49f948faa9258a0c61caceaf225e179651397431/skills/.curated/security-best-practices/LICENSE.txt) |
| `protohub-development` | 契約確認、担当分割、実装、検証、修正、引継ぎ | ProtoHubの継続開発全体。既存の仕様・make・harnessへ接続する | このリポジトリで管理するローカルスキル |

React用スキルの上流ディレクトリ名は `react-best-practices`、`SKILL.md` 内の名前は
`vercel-react-best-practices`。名前を混同しない。上流にはNext.js/RSC固有の指針もあるが、
ProtoHubはVite SPAなので適用可能なReactの項目を使う。このスキルの導入だけを理由に
Next.jsへ移行したり、SWR等の依存を追加したりしない。

## 固定した出典とローカル変更

調査日は2026-10-30 JST。上表のリンクは取得時に確認したcommitへ固定している。

| 上流リポジトリ | 固定commit | 取り込む対象 |
| --- | --- | --- |
| `anthropics/skills` | `ca45fc496a3436251f191354091d557da31c15b5` | `skills/frontend-design` |
| `vercel-labs/agent-skills` | `1a2c79d4e6c4a2283dc2c614b6538cbe1ed5ca62` | `skills/react-best-practices`、`skills/web-design-guidelines` |
| `vercel-labs/web-interface-guidelines` | `434b7f91364665f2f733b310ec54809bf8f37937` | `command.md`とMITライセンス全文 |
| `openai/skills` | `49f948faa9258a0c61caceaf225e179651397431` | `skills/.curated/security-best-practices` |

Vercelのagent-skillsは、調査したcommitのREADMEとReactスキルのfrontmatterにMITを
宣言している一方、リポジトリ直下や対象2ディレクトリに独立したLICENSEファイルはない。
実在する宣言を [third_party/agent-skills/vercel-agent-skills.README.md](../third_party/agent-skills/vercel-agent-skills.README.md)
に保持し、存在しない上流ライセンス本文や著作権表示を作らない。

`web-design-guidelines` の原本は、レビューのたびに別リポジトリの `main/command.md`
を取得する指示を持つ。このプロジェクトでは、その取得先を同スキルの
`references/command.md` へ差し替える。参照本文は上表の固定commitから取得し、
[実在するMITライセンス](https://github.com/vercel-labs/web-interface-guidelines/blob/434b7f91364665f2f733b310ec54809bf8f37937/LICENSE)
を `LICENSE.txt` として一緒に保持する。変更した指示と参照元はlockに記録する。
これにより、レビュー基準がネットワークや上流mainの更新で変わらない。

第三者スキルのライセンスはその同梱物に適用される。ProtoHub自身のルートLICENSEの
選定とは別であり、スキル導入によってプロジェクト全体のライセンスを決めない。

## 開発時の使い分け

通常の変更では、`protohub-development` で仕様と受入条件を確認し、変更に関係する
スキルだけを読む。UIを作るなら `frontend-design` で対象利用者・画面の目的・文字と
配色の方針を決め、React実装時に `vercel-react-best-practices` を参照する。
完成した画面を `web-design-guidelines` と実ブラウザで確認し、指摘を修正する。

依頼例:

```text
$protohub-development 起動失敗時の再試行体験を改善し、影響する検証まで完了して。
$frontend-design ProtoHubの状態一覧を、操作と失敗理由が読み取りやすい構成に改善して。
$vercel-react-best-practices apps/webのpollingと再描画を、既存契約を守ってレビューして。
$web-design-guidelines apps/web/srcのキーボード操作・focus・formをレビューして。
$security-best-practices APIとpreviewのOrigin/Host・固定upstream境界をレビューして。
```

スキルは作業方法の補助であり、検査結果の代用にはしない。UIの見た目やcomponent mock
が良くても、実PostgreSQL・Pod・HTTP・停止・削除の成功とは記録しない。
既存のpytest、Vitest、Node Playwrightと `make check` / `make verify` を検証入口として使う。
証跡は今回runの `worklogs/` 配下に残す。

スキルの一般的な推奨と、ProtoHubの仕様・利用者の指示が違う場合は、変更の目的と
既存の安全境界を優先して適用範囲を判断する。通常の工程移動のたびに承認を追加せず、
OS設定、権限、秘密、課金、破壊操作、外部公開などの境界では既存の承認ルールを守る。

## 今回追加しないもの

- [Anthropic webapp-testing](https://github.com/anthropics/skills/blob/ca45fc496a3436251f191354091d557da31c15b5/skills/webapp-testing/SKILL.md)
  はPython Playwrightとサーバー起動helperを中心とする。既存のNode Playwright・
  Compose/kind fixtureと重複するため、今回の標準セットには入れない。
- [OpenAI playwright](https://github.com/openai/skills/blob/49f948faa9258a0c61caceaf225e179651397431/skills/.curated/playwright/SKILL.md)
  はCLIでの対話的なブラウザ操作に向く。既存E2Eテストの置換は不要なので追加しない。
- `playwright-interactive`、クラウドdeploy・課金サービス向けスキル、AI-DLC全体の
  native runtime/hook installerは追加しない。スキルを理由にsandboxや承認設定を変えない。

AI-DLCの採用範囲と将来のプロダクト設計は [AI_DLC.md](AI_DLC.md) に分けて記録する。
