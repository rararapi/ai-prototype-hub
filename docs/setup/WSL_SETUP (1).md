# 並行実行と統合ルール

## 基本形

契約を固定する短い直列Phase 0の後、A/B/C/Dを並行実装し、親が統合する。完全に依存する工程まで無理に同時実行しない。親は各担当に入力、所有パス、禁止パス、期待成果、検証コマンドを渡す。

| 役割 | 主な所有パス | 完了時の成果 |
|---|---|---|
| Coordinator | `AGENTS.md`, `CODEX_TASK.md`, `contracts/**`, `apps/server/src/protohub/domain/**`, Python manifest/lock, `harness/PLAN.md`, 共通仕様 | 型/APIを固定、最終統合、報告 |
| A Backend | `apps/server/src/protohub/api/**`, `persistence/**`, `migrations/**`, `tests/api/**` | 永続API・job store・API/DBテスト |
| B Frontend | `apps/web/**` とそのpackage-lock | UI・生成クライアント・component tests |
| C Runtime/Infra | `apps/server/src/protohub/worker/**`, `runtime/**`, `preview/**`, `tests/worker/**`, `tests/runtime/**`, `infra/**`, `examples/**`, `scripts/local/**`, `compose.yaml` | 実行adapter・Compose・kind・起動停止 |
| D QA/Harness | `harness/run.py`, `harness/doctor.py`, `harness/gates.json`, `harness/Makefile`, `harness/tests/**`, `scripts/checks/**`, `tests/integration/**`, `tests/e2e/**`, root `Makefile`, `.github/workflows/**` | fail-closed検証・E2E・CI |

所有パスはPhase 0に正規化し、曖昧な共有ファイルは担当を1名に決める。Python共有依存やDTOの変更は親へ依頼する。root MakefileはD、composeはC。DがCのscriptsを呼び出す契約を先に固定する。

各担当は `harness/handoffs/backend.md` 等、自分の引継ぎファイルだけを編集する。共通 `harness/PLAN.md` は親だけが更新する。

## worktree方式（推奨）

1. 親が基礎ファイルと契約を1つのローカルcommitに固定する。
2. 未commitのユーザー変更を避けて、同じベースSHAから各worktree/branchを作る。
3. 各エージェントへ絶対パスを渡し、すべてのコマンドのcwdをそこに限定する。
4. 各担当がテストしてローカルcommitを作り、SHAと引継ぎを親へ返す。
5. 親が統合用branchでA→C→B→Dの順に取り込む。競合は契約と意図を確認して解決する。

例（branch/pathは例示。既存の同名branch/pathがないことを先に確認し、必要なら今回専用名にする）:

```bash
# 基礎commitが完成し、作業内容を確認した後だけ実行する例
git worktree add -b codex/protohub-api ../protohub-api HEAD
git worktree add -b codex/protohub-web ../protohub-web HEAD
git worktree add -b codex/protohub-runtime ../protohub-runtime HEAD
git worktree add -b codex/protohub-qa ../protohub-qa HEAD
```

同一branchを複数worktreeへcheckoutしない。既存worktreeを削除して再利用しない。worktree間で未追跡ファイルや `.env` が自動同期すると思わない。秘密を複製する設定も追加しない。

## 共有worktreeしか使えない場合

親はこの方式を選んだことを最初に明記する。A/B/C/Dは所有パスだけ編集する。**git操作、commit、依存インストール/lock更新、共通設定変更は親に一本化**。担当が他者の変更をrevertしない。`git add .` で他者作業を巻き取らない。

共有型サブエージェントへ別worktreeで動く能力がない場合に、worktreeを作っただけで分離できたと見なさない。実際のcwdを確認する。

## 実行資源の分離

コードを分けてもDocker daemonやportsは共通。各担当のDBテストは独立したCompose project名・network・volume・DB名・portを使う。

- `COMPOSE_PROJECT_NAME=protohub-<role>-<run_id>`
- 固定 `container_name` を使わない。
- 起動前にport競合を確認する。勝手にプロセスをkillしない。
- 親の統合テスト用kindは1つ。apply/delete/build/loadは統合担当が直列実行する。
- agentごとのunit testではkindを起動しない。Runtime担当が必要なspikeをするなら、統合kindと異なる名前を使用し、所有記録を残す。
- cleanupは対象の完全一致名とlabelsを確認し、自分が作成したものだけ。

## 各担当の引継ぎ形式

```markdown
# <role> handoff
## Changed files / commit
## Implemented behavior
## Tests actually run
| command | result | evidence |
## Contract/dependency changes requested
## Known issues and BLOCKED checks
## Integration notes
```

「全部完了」だけの報告は禁止。mock testと実起動testを分ける。不要な長いログや秘密をhandoffに貼らない。

## 統合時の終点

1. 契約差分とファイル所有違反を確認。
2. 全体build・quick gate。
3. real PostgreSQL integration。
4. kindのサンプル実起動・HTTP・stop/delete、Playwright。
5. Reviewerが状態競合、権限、虚偽成功、cleanupを独立レビュー。
6. 修正して必要ゲート再実行。
7. READMEと `harness/PLAN.md` に実際の到達状態を記録して停止。

Codexでサブエージェントが利用できない場合は、分担promptを別セッションへ渡せる形で残す。存在しない設定やCLIフラグを捏造しない。利用可能な範囲では親が継続してよいが、並行実行できたと誤報告しない。
