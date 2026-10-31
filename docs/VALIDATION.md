# 実装・検証記録（2026-10-31 JST）

対象ブランチは `codex/protohub-local-mvp` です。GitHubへのpush/PR/merge、公開、
クラウド作成は行っていません。各担当のhandoffだけを合格証拠にはせず、親が統合コードを検証します。

## 実行環境

最初のWSL/Docker診断は不足環境でBLOCKED。その後Docker接続が可能になりました。
WSL2 Ubuntu22.04のLinux filesystem上に一時検証コピーを作り、make4.3/kind0.33/kubectl1.37を
その検証用binへ配置しました。kind/kubectlは公式チェックサムを照合しました。makeは既存Ubuntuと
同じ22.04の検証用コンテナで用意し、バイナリだけを一時領域へ取り出しました。
この2026-10-30の初回検証ではホストOSへのインストール・WSL設定変更・権限変更・Docker再起動は行っていません。

## 2026-10-31の承認済み環境更新と再検証

利用者の明示承認とWindows UAC許可により、WSL3.0.3.0とDocker Desktop4.97.0へ
既存インストールを更新しました。両installerは公式checksum/署名を照合し、終了codeは0。
更新前のDB archive検査とDocker data/main VHDXのオフラインcopy/hash照合はPASSです。
更新後は実daemonのcgroup **2**、Engine29.9.2、kernel6.18.54.1-1を実測しました。
全5既存volumeの属性と、別用途の停止済みcontainer ID/stateを照合し、mockの既存DB行数と
HTTP応答もPASSです。証跡は `.harness/reports/cgroup-v2-20261031/` に保持します。

初回real起動でserver imageの最終checks stageを誤って使い、API migrationが失敗しました。
`5575c23`でruntime targetを明示し、停止時のworker drain競合も回帰テストとともに修正。
既存kind/PVCを保持して再検証しました。初回full `20261031T082906Z-cade2abf`は
既知の不具合を繰り返す前に中断した記録であり、合格には数えません。
この失敗時点の結果を全体の受入完了とは扱いません。

同日の対話ブラウザでは、Windows localhostのreal-kind画面から登録→起動→Ready→
サンプルURLを開く→counterの0→1→停止→同じアプリの再起動→削除を操作しました。
Ready時の実Pod/Service、停止時のPod消失、削除完了後のPod/Service消失をkubectlで照合しました。
画面はmockではありません。
ブラウザ画像とWindows HTTP結果は同maintenance directoryの`console-real.png`、
`sample-real.png`、`windows-browser.json`です。これだけで全自動E2E合格とは扱いません。

再検証full `20261031T083523Z-ef7fa992`のE2E初回fixtureは、WSLが選んだport58867が
Windows予約58828〜58927に含まれるため、Dockerのport公開で失敗しました。
OSの予約範囲は変更せず、`dc7fc38`でfixture側のconsole/preview候補を20000〜29999から
最大128回で選ぶ修正を行いました。実占有socketを含む7回帰検査と独立レビューはPASS。
選択後の競合や全てのWindows予約範囲を完全防止する仕組みではなく、後発の公開失敗は
明示的に失敗します。kind API serverの自動portは変更していません。
失敗レポートと所有済みfixtureのcleanup記録は保持します。

この`5575c23`でのfullは11gate中、E2E以外の10gateがPASSしました。実PostgreSQLは4テスト、
live securityは独立fixtureで5項目がPASSし、各fixtureの所有を照合して回収しました。
同commitのE2Eだけは上記port予約でFAILです。`dc7fc38`は停止待ちのsubprocess自体へも
期限を渡し、実際に固まったchildを使う回帰を追加しています。launcherの28テストがPASS。

この文書を含む統合HEADで`make verify`を実行し直します。最終合否は、そのコマンドが表示する
正確な `.harness/reports/<run_id>/report.json` の全gate、complete、中断有無、実行前後の
source fingerprintで判定します。過去PASSの流用や、ブラウザの手動確認によるE2E代替はしません。

通常の`make down`の追加実検証では、sampleが0件だとkubectl scaleが失敗する不具合を検出。
`f98381d`で空一覧だけscaleを省略し、残存Podの観測は継続するよう修正しました。
同commitの実kind日常停止→全制御Pod消失→`make up-real`はPASSです。DB PodのUIDが変わり、
PVCのUID、削除済み管理レコードのID/status/generationが保持されることを検査しています。
証跡はmaintenance directoryの`kind-persistence.json`。この時点のlauncher関連38テストもPASS。
先行full `20261031T084855Z-053e5d7a`は、発見済みの停止不具合を修正するため途中で中断し、
合格には数えません。中断時にroot所有となった一部unit生出力はWindowsへcopyできず、
そのrunの元WSL directoryに保持しています。
さらに独立レビューで、先行削除が一覧取得とscaleの間に完了する競合を検査しました。
明示的な対象消失エラーだけを分類し、新しい一覧が空かつPod drainが完了した場合だけ
停止を続行します。権限・通信・timeoutエラーは無視しません。関連51テストがPASSしています。

`5a7b64f`のfull `20261031T090143Z-c5660244`は、Playwrightの削除完了poll中に
全体180秒のtest budgetを使い切りFAILになりました。個別expectの100秒は残っていたため、
通常30秒のPod終了猶予を複数回含む2アプリの一連操作に、全体420秒を割り当てます。
個別expect100秒、retry0、全assertionは維持します。設定読込と1spec収集はPASS。
同runのsecurityは既知の失敗後に中断した記録です。trace・失敗画像・全reportを保持し、
このrunを合格には数えません。初回Playwright image取得後の最終統合HEADで再実行します。
大きなimage展開後の一時的なWSL CLI timeoutで、このrunのfixture cleanupも拒否されました。
daemonの正常応答とCLI復帰を確認後、元の完全node ID・作成receipt・所有記録を照合し、
該当E2Eノード1個だけを回収しました。`e2e-recovery-cleanup.json`はPASSです。
日常用kindと既存volumeは保持し、追加のOS再起動や権限変更は行っていません。

`f3a8289`のfull `20261031T093017Z-4a52d79b`では、Playwrightの2アプリlifecycleが
1/1 PASS（約3.6分、skipなし）、securityの独立5項目もPASSしました。全体は10/11 PASSで、
E2Eの後続runtime検査だけがAPI rollout直後の公開HTTP 502でFAILです。fixture cleanupはPASS。
rolloutだけを公開経路の復旧とは扱わず、同じUUIDの保持レコードを実HTTPで最大120秒観測します。
後続leaseテストも旧worker Pod消失と唯一のReady/Running holderを確認してからenqueueし、
実UIDを再照合して終了します。部分失敗とtimeoutはServiceを含む全資源回収を検査し、
timeoutのerror codeも明示確認します。実観測を待つ変更であり、mutation再送やassertion削除はしません。
負荷注入のmissing imageは予約済み`.invalid` registryへ固定し、外部公開tagの不在には依存しません。

`515c789`のfull `20261031T100446Z-4e908c19`では、ブラウザ1/1、実runtime8項目、
live security5項目が全てPASSしました。ただし両fixtureの回収前にCLI版`docker info`が
12秒でtimeoutし、E2E/securityゲート全体はFAILです。機能検査だけを全体PASSに置き換えません。
`5d3ae05`でdoctorを確認済みUnix socketの読み取り専用metadataへ変更しました。
接続先・Linux・cgroup・所有検査を維持し、期限/サイズ/不正応答/slow-drip/非local拒否を含む
WSLハーネステスト107/107がPASSです。同commitの実`make doctor-kind`もPASSし、
元の完全node ID・作成receipt・所有を確認して残存2fixtureだけを通常guard付きで回収しました。
証跡は `.harness/reports/doctor-server-metadata-20261031/` の`live-doctor.log`、
`harness-self-final.log`、`exact-recovery.json`です。日常用kindと既存volumeは保持しています。
この修正を含む統合HEADの全11ゲートを、改めて同じ`make verify`入口で確認します。

## 2026-10-30時点の証跡（履歴）

| 対象 | 結果 | 証跡 |
|---|---|---|
| Windows portable（source/contract/unit/build/hygiene） | PASS | `.harness/reports/20261030T001936Z-d32b14e8/report.json` |
| 同run Python / Vitest | 89 / 22 PASS、skipなし | 同runの`unit/pytest.xml`, `unit/vitest.xml` |
| WSL harness自己テスト（workflow/skills含む） | 72 PASS | 今回WSLのunittest実行。最終runnerでも再検査 |
| Docker版source / contract / unit / image build / hygiene | PASS | quick `20261030T001543Z-a4f5cdf2`、full `20261030T002409Z-fe52d19a` |
| 実PostgreSQL migration/queue/concurrency/lease/TTL/persistence | 4 PASS、skipなし | fullの`integration/postgres.xml` |
| Compose mock実API/DB lifecycle・2アプリ独立 | PASS | `mock-20261030/mock-smoke.json`、source `0c331d5` |
| mock停止後のDB volume保持・再起動後レコード保持 | PASS | 同runの`retained-volumes.txt`、`mock-smoke.json` |
| Windows→localhost HTTP | PASS | 同runの`windows-http.json`。Windows対話ブラウザは未確認 |
| Playwright spec収集 | 1件収集PASS | `npm exec -- playwright test --list --reporter=list`。実行成功とは別 |
| 実kind Pod/HTTP、real Playwright、live RBAC/security | BLOCKED | Docker cgroup v1。初回fullは実際の起動FAILを保存 |
| 必須full acceptance | 未達/BLOCKED | cgroup v2化後に`make verify`を再実行する |

初回fullはclean source `94fdde0`の同一SHAで検査し、E2E/securityの実起動がFAILになった。
診断後はdoctor-kindが不足環境を先に示すため、新しいfullでは同項目をBLOCKEDにする。
旧レポートのFAILを消したり、未実行の実Pod/HTTPをPASSに変更したりしない。
最終commitでの結果とsource fingerprintは、最終runnerの`report.json`を参照する。

初期の失敗記録も残しています。CRLF、Python3.10互換、検証buildのowner/context不整合は修正済み。
独立レビューで見つかった旧PodによるReady誤判定、lease喪失後の後続mutation、kind作成失敗の
回収不能、中断時fixture cleanupは実装・回帰テストを修正し、再レビューしました。
実WSL検証で見つかったtmpfsのYAML分割、Docker時刻の9桁小数にも回帰検査を追加した。
失敗した2つのkindノードは完全なcontainer ID・所有ID・作成receiptを照合して回収し、
`20261030T002409Z-fe52d19a/recovery-cleanup.json` に記録した。

## エージェント開発ハーネスとスキル

目的・許可/禁止パス・担当・契約判断・修復予算を実CLIへ記録する。staged/unstaged/
未追跡/renameと既存dirtyファイルを検査し、検証前後と完了時のsource fingerprintを照合する。
FAIL/BLOCKED/skip・古いHEAD・変更されたdirty内容・独立レビュー欠落では完了を拒否する。

スキル5件は `.agents/skills/` に配置し、固定SHA・同梱license/宣言・参照文書・全ファイルhashを
`harness/skills.lock.json` に保存した。第三者スキルの形式検証と `make skills-check` はPASS。
独立した一時React fixtureで、実検査FAIL→証跡登録拒否→修復1回→PASS→別担当レビュー→
`finish` PASSを確認した。評価は `.harness/skill-forward/run-cc712942b8/.harness/forward-evaluation.json`。
これは開発フローの検証であり、MVPの実Pod/ブラウザの代替証拠には数えない。

## 実装された受入シナリオ

API/worker/provider単体、実PostgreSQLテスト、実kind/Playwright検証を別に持ちます。
実PostgreSQLは実行済み。実kind/Playwright部分はPASSになるまで実証済みとしません。

- 生成OpenAPIと正本の完全一致、生成フロント型の一致、統一エラー、入力/Origin/Host拒否。
- 二重要求、generation supersede、lease期限とtoken回転、旧holder拒否、最大3回retry、TTL。
- 現generationのPod/rollout/Service経路とHTTP応答を観測してReadyにする。
- UI登録/操作/実サンプルclick、2アプリ独立、stop/restart/delete、実Pod/Service回収。
- queued/running jobのworker復旧、API再起動の永続性、readiness timeout、部分作成失敗。
- worker RBACの実allow/deny、Pod設定、preview/Host/Origin、所有外資源への操作拒否。

## 残す制約

単一開発者・localhost・固定サンプルのみ。悪性コード隔離、本番認証、公開サービス、
CNIによる敵対的通信隔離、任意コード、実組織SSO、LLM接続は未対応です。
静的hygieneはbest-effortであり秘密検出の完全保証ではありません。LICENSEは未選定です。
GitHub CIの定義は実装済みですが、pushしない依頼なのでGitHub上でのCI実行は未実施です。
Docker/WSLのcgroup v2化は2026-10-31に承認を受けて実施しました。上記の新しい記録に
従ってreal-kindを再検証します。AI-DLC製品機能、OIDC、AKS等は別フェーズです。
