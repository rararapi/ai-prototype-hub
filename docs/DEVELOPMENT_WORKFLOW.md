# エージェントが継続開発するためのハーネス

このリポジトリのハーネスは、テストランナーと、エージェントの開発手順を組み合わせる。
`harness/workflow.py` は目的・作業範囲・担当・契約判断・修復・検証・独立レビューを
一つのローカル作業記録へ結び付ける。`harness/run.py` は実際の検証を実行する。

## 通常の進め方

1. 人間の依頼、AGENTS.md、必要な仕様、現在の差分を読む。
2. 一つの作業項目を登録し、触るファイル、触らないファイル、担当、必要な検証を固定する。
3. 実装する。独立した部分は担当を分け、APIや共有型の変更判断を記録する。
4. 意味のある変更単位で差分の範囲を確認し、必要なゲートを実行する。
5. 失敗は観測した原因、次の修正、次に確かめるコマンドを記録して修復する。
6. 同じコードの独立レビューを受け、重大な指摘を修正して影響する検証を再実行する。
7. 現在のコードと一致する証跡を添付し、完了判定を行う。

通常の次工程ごとに人間へ確認しない。会話で得た権限は継続する。
命名、余白、関数分割、テスト細分化は担当が決める。目的の実質的な変更や安全境界の変更、
OS設定、権限追加、課金、秘密情報、破壊操作、外部公開には、既存の承認ルールを適用する。
`note --kind authorization` は既に得た権限の出典を記録するもので、権限を新しく与えない。

## 作業を始める

WSL/Linuxのリポジトリrootで実行する。Python標準ライブラリとGitだけを使う。
作業記録はignoredな `.harness/workflows/<id>/workflow.json` に保存される。
同じIDを上書きしない。Gitのpush、commit、checkout、依存installはこのCLIから行わない。

```bash
python3 harness/workflow.py start \
  --id preview-status-fix \
  --objective 'プレビューの失敗表示を修正し、既存の起動操作を維持する' \
  --allow apps/web/ \
  --allow apps/server/tests/runtime/ \
  --forbid infra/ \
  --owner apps/web/=frontend \
  --owner apps/server/tests/runtime/=runtime-tests \
  --contract contracts/openapi.yaml \
  --required-gate source --required-gate contracts --required-gate unit \
  --required-gate build --required-gate public-hygiene \
  --max-repairs 3
```

末尾が `/` のscopeはディレクトリ配下、それ以外はファイルとの完全一致。globは使わない。
各allowed scopeには一人のownerを割り当てる。owner指定を省略するとcoordinatorになる。
重複するallowed scope、絶対path、`..`、symlinkによるroot外への逸脱を拒否する。
`.git/` と `.harness/` はソース変更の対象外として常に扱う。

`--required-gate` を省略するとMVPの全必須ゲートになる。UIの表示修正とruntime変更では
必要な検査が異なるため、作業開始時に目的と影響範囲に合わせて選ぶ。
必須に指定した検査が実行不能なら完了にはしない。BLOCKEDの原因と残作業を報告する。

## 差分、契約、失敗の扱い

```bash
python3 harness/workflow.py check --id preview-status-fix
python3 harness/workflow.py note --id preview-status-fix \
  --kind implementation --summary '状態表示はAPIの観測値だけから決定する'
python3 harness/workflow.py repair --id preview-status-fix \
  --cause '失敗状態でも古いURLが残るcomponent testが失敗した' \
  --action '失敗状態でリンクを消し、再読込後の回帰テストを追加する' \
  --next-check 'make check'
```

checkは本物のGit差分を読む。staged/unstaged、未追跡ファイル、renameの移動元と移動先、
作業開始後のcommitも対象にする。開始時から存在する所有外のdirty差分は、内容・indexを
保ったままなら保存対象として扱い、消去や書き換えを検出する。所有外の変更を自動で戻さない。

登録した契約ファイルを変更した場合は、親が変更理由と影響を記録して担当へ伝える。
scope外のファイル変更が、この記録だけで許可されることはない。

```bash
python3 harness/workflow.py note --id contract-change \
  --kind contract --path contracts/openapi.yaml \
  --summary '合意済みの新しいエラー項目を契約へ追加し、UIとAPIの担当へ通知した'
```

contract判断はその時点の内容hashへ結び付く。後から追加で契約を変えれば、再び記録が必要。
repairの回数はこの作業項目の明示的な修復予算。尽きたら同じ失敗を無制限に再試行せず、
原因と実施済み修正を読み直し、作業を分解するか計画を立て直す。通常の工程ごとの承認要求には
使わない。目的・安全境界の変更がある場合だけ、必要な人間の判断を求める。

## 検証とレビューを結び付ける

必要なmake targetを実行し、今回のrunnerが表示した正確なreport pathを添付する。
「一番新しいdirectory」を探索して別runの証跡を流用しない。

```bash
make check
python3 harness/workflow.py record-gates --id preview-status-fix \
  --file .harness/reports/<今回のrun_id>/report.json
python3 harness/workflow.py record-review --id preview-status-fix \
  --file .harness/reviews/<今回のreview_id>.json
python3 harness/workflow.py finish --id preview-status-fix
```

gate reportには、runnerの `git_sha`、`git_dirty`、`git_snapshot`、`git_snapshot_after` が必要。
snapshotはHEADと、index・作業ファイル・未追跡ファイルの内容を含むfingerprintを持つ。
テスト前、テスト後、finish時点が一致しない証跡を拒否する。dirtyが両方trueというだけでは
同じコードを検証したことにならない。ignoredなレポートやビルド成果物はfingerprintに含めない。

レビューは別担当が行い、`harness/templates/review.example.json` の形式でignoredなJSONに残す。
レビュー対象のsnapshotは `python3 harness/workflow.py snapshot` で取得できる。
`reviewer`、`independent: true`、実際のUTC完了時刻、具体的な `summary`、未解決の重大指摘が
ゼロであること、レビュー時の `git_snapshot` を記録する。ひな形のままでは受理しない。

finishは、範囲逸脱、未記録の契約変更、必要ゲートの欠落・FAIL・BLOCKED・skip、古いHEAD、
同じdirty状態の別内容、検証中の変更、古いレビュー、添付後の証跡改変を拒否する。
完了後の記録は変更しない。次の依頼は新しいIDで作成する。

## この仕組みの境界

このCLIは、エージェントが約束した作業範囲と実際の差分を照合する開発支援である。
エディタやshellからの全書き込みを強制的に遮断するOS sandboxではない。
悪意あるエージェントによる記録改ざんや、独立レビューを実施したという虚偽の宣言を
防ぐ認証・署名基盤も持たない。権限制御は実行環境のsandboxと承認ルールが担う。
submoduleを含むrepositoryは不完全なsnapshotを作らず拒否し、別作業へ分ける。

skillsは、この手順の中で必要な道具を選ぶために使う。主要な実装・レビュー・デバッグの
skillを作業の性質に応じて適用し、skillがあるという理由だけで目的や公開範囲を拡大しない。
このworkflowが特定のLLM、有料API、クラウド、プロジェクトlicenseを選ぶことはない。
