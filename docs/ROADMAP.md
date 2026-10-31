# 次の開発課題

2026-10-31時点。固定テンプレートのローカルMVPは、実Pod・HTTP・ブラウザを含む
全11ゲートで受入済みです。GitHub CIのDevContainer/verifyも成功しました。
ここでは、観測した不具合、未検証の環境、将来機能を区別して次の作業を定義します。
詳細な受入ソースと履歴は [VALIDATION](VALIDATION.md)、製品内AIの案は [AI_DLC](AI_DLC.md) を参照してください。

| 課題 | 現在の影響 | 推奨する着手時点 |
|---|---|---|
| R1 開発依存のadvisory | 開発/CI toolchainのCPU・メモリ消費リスク。現在のサンプルHTTP経路から到達する証拠はない | 次の保守作業。外部入力をtoolchainへ渡す前 |
| R2 kind初期化失敗の診断 | 新しい検証clusterの作成が一時失敗・遅延することがある | 再発時の証拠採取を先に整備 |
| R3 他PC/OS/ARMの検証 | 環境差をまだ保証できない | 対応環境を広げる前 |
| R4 製品内の対話型開発 | 現在は固定サンプルの管理まで。アプリをAIで作る機能はない | 次の製品フェーズとして仕様を決める |
| R5 任意コード/多人数/公開運用 | v0の対象外。現在のkindをその安全境界には使えない | これらを有効にする前に設計・実検証 |

## R1: 開発依存のadvisory

**観測したこと。** 2026-10-31のweb依存監査でmoderateが13 package entries、high/criticalは0。
13個の別々の脆弱性という意味ではなく、1件のminimatch advisoryが親toolへ波及した集計です。
対象はESLint、TypeScript-ESLint、OpenAPI型生成などの開発依存です。
minimatch10.2.6と推移依存5.1.9がlockにあり、registryは後者も範囲判定していますが、
上流の具体的な説明は10.2.6なので、5.xでの攻撃成功まで実証したとは扱いません。
[上流advisory](https://github.com/isaacs/minimatch/security/advisories/GHSA-g3hv-75wg-m249)。

**現在の影響。** 攻撃者のglobが高い最適化設定へ入った場合、開発/CIのCPU・メモリを
過剰消費する懸念です。確認した呼出しは既定設定とリポジトリ管理のglobを使い、
MVPのHTTP入力をglobへ渡す経路はありません。npmのproduction-only監査は0件で、
実行用web imageはnginxとdistのみです。これはPython/OS/nginxを含む全体の無脆弱性保証ではありません。

**次の作業。** 修復時点の公式release/制約を確認し、影響する親toolを互換性のある修正版へ更新します。
既存制約を無視したminimatch11への一律override、`audit fix --force`、dev依存の監査除外で
数字だけを0にする対応はしません。上流の制約次第ではbackportまたは未解決の経路を記録します。

**完了条件。** npm ciでlockを再現でき、全依存とproduction-onlyの監査結果を保存すること。
lint/type/contract/unit/buildが通り、実行依存・生成物が意図どおりであること。
影響する依存を更新した最終sourceでfullと独立レビューも確認します。この更新はまだ行っていません。

## R2: kind初期化失敗の診断

**観測したこと。** 同じe904814のローカルfull2回に含まれる4cluster作成で、1回だけ
kubeadmのadmin ClusterRoleBinding初期化が失敗しました。この少数の観測から一般的な失敗率は推定しません。
内部APIへ約60秒応答がなく、期限切れで終了しました。HTTP429、認証失敗、host port衝突、OOMの
いずれかが原因だという証拠はありません。根本原因は未特定です。
同じsourceの一度の再実行は全11ゲートPASS。失敗時も対象限定cleanupは成功しました。

**現在の影響。** 新規clusterのセットアップが失敗・遅延する可能性です。
アプリ配置前の失敗であり、管理DBの消失やアプリの状態遷移不良は観測していません。
日常用の既存clusterと他用途の資源は保持しています。

**次の作業。** 再発時、cleanupの前に対象nodeのkubelet journal、apiserver/etcdの短いログ、
実行containerの状態、OOM/exit/restart、CPU/メモリ/disk状況を同runへ保存します。
node完全ID・作成receipt・所有labelを照合し、秘密やkubeconfig/env全体を出力しません。
証拠を採取してから通常の所有guard付きcleanupを行います。

**完了条件。** 診断採取を有界に実装し、成功/失敗/採取失敗でcleanupと終了コードを壊さない検査があること。
根拠なくport・OS設定・全体retryやtimeoutを変えず、原因が確認できた時点で限定修復します。
自動retryで最初の失敗を隠さないことも維持します。

## R3: 他のローカルPCとARM

**現状。** Windows+WSL2/Linux amd64でDevContainerのup/exec/recreate、mock、real-kindを確認。
GitHubのUbuntu amd64でもDevContainerとfullが成功しました。macOS、別のLinuxホスト、
他のWindows PC、ARMは未実測です。DevContainerで依存は揃いますが、Docker/cgroup、
ホストのport予約、CPU architecture、filesystemの権限・性能差は残ります。

**次の作業と完了条件。** 対応したいPC/OS/architectureのmatrixを先に決め、同一commitで
fresh clone→Reopen/recreate→check-dev→mock→full→ブラウザ操作を行います。
固定image digestとネイティブ依存、kind/kubectlのarchitecture、localhostへの到達と
停止/データ保持を確認し、PASS/BLOCKEDを環境別に残します。未測定の環境まで対応済みとは書きません。

## R4: 製品内の対話型AI-DLC

**現在の不足。** 開発者向けworkflow/skillsはありますが、利用者が画面でAIへ依頼し、
アプリを生成・修正する機能はありません。現在のHello Webは事前に用意した固定テンプレートです。

**最初に作る候補。** 対話から目的・対象ユーザー・対象外・受入条件を整理して保存し、
人が確認・修正でき、後から再開できる体験です。これはまだ実装の依頼ではなく次段階の提案です。
次に実装計画、コード差分、検証結果、起動状態を結び付ける範囲を決めます。

**先に決めること。** 最初の利用者と作りたいアプリの種類、モデル接続先・費用上限・鍵の扱い、
生成物の保存と修正履歴、人に戻す判断、失敗時の再開方法。
モデル名・有料APIをこの文書だけで選定せず、文章上の成功を検証PASSやReadyへ置き換えません。

## R5: 任意コード・多人数・外部公開

v0は単一開発者・localhost・信頼済み固定テンプレート専用です。
kindの通常コンテナ、namespace、現行のlocal-dev principalを、敵対的コードの隔離や本番認証としては扱いません。
実装前に認証/認可、ユーザー・アプリごとのデータとOrigin/Cookie境界、実行隔離・通信制御、
秘密の保管、quota/TTL、監査・停止/復旧を設計し、対象基盤で実検証する必要があります。
AKS/Kata/OIDC等は候補であり、今回その導入・課金資源作成は始めていません。

## 推奨する順序

MITとmain反映の確認後、R1とR2を小さな保守作業として進める。
並行してR4の最初の体験と対象者を決め、対応PCを広げる時点でR3を実施する。
R5は機能の安全境界が変わる前に扱います。これらの作業を文書作成だけで着手済み・完了とはしません。
