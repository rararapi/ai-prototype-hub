# 開発環境と依存版（2026-10-31 JST）

`apps/server/uv.lock` と `apps/web/package-lock.json`、`tests/e2e/package-lock.json` が
再現用のlockfileです。レジストリが返した安定版を解決し、下記環境で実際の検査を行いました。
Linuxコンテナと実起動の到達点は [VALIDATION](VALIDATION.md) に分けて記録します。

| 項目 | native検証で使った版 |
|---|---|
| Python | 3.11.4（アプリは3.11〜3.13） |
| uv | 0.11.19 |
| Node.js / npm | 24.18.0 / 11.16.0 |
| FastAPI / Pydantic | 0.162.0 / 2.14.2 |
| SQLAlchemy / Alembic | 2.1.6 / 1.20.1 |
| psycopg / Kubernetes Python client | 3.3.6 / 37.0.1 |
| pytest / Ruff / mypy | 9.2.0 / 0.17.3 / 2.4.1 |
| React / Vite / TypeScript | 19.3.1 / 8.3.5 / 5.9.3 |
| Vitest / openapi-typescript / Playwright | 5.0.5 / 7.13.0 / 1.64.1 |

ハーネス・doctor・ローカルlauncherはPython 3.10以上の標準ライブラリで動きます。
初回の2026-10-30検証ではUbuntu 22.04.3 LTS / kernel 5.15.146.1、Docker server 25.0.3、
Compose v2.24.6、buildx v0.12.1を確認しました。最初はDocker未接続でしたが検証中に接続可能となりました。
その初回検証ではホストOSのサービス・権限・WSL設定は変更していません。
Docker内のPython3.11.18/Node24.18.0でsource/contract/unit/buildを実行しました。
初回Docker daemonのcgroup版は1で、Kubernetes1.37は起動を拒否しました。real-kindはcgroup v2が前提です。
最初のdoctor-kindではこの条件を見落としていたため、実失敗後に事前検出を実装・検査しました。

2026-10-31、利用者の明示承認とPC側UAC許可を受け、既存WSL/Docker Desktopを更新しました。
更新前にDB archive、設定、Docker data/main VHDXを退避し、SHA256を照合しました。
更新後はWSL 3.0.3.0 / kernel 6.18.54.1-1、Docker Desktop 4.97.0.244584、
Engine 29.9.2、Compose 5.6.1、buildx 0.38.1を確認しています。実daemonはcgroup **2**、
cgroupfs、overlay2です。全5既存volumeの同一性、別用途の停止済みcontainer、mock DBの
行数とHTTP応答を確認しました。Windows全体の再起動やcgroup強制回避は行っていません。
kind/実Pod/ブラウザの最新合否は [VALIDATION](VALIDATION.md) を参照してください。
Dev Container専用の [検証記録](DEV_CONTAINER.md#この構成自体の検証状況) にあるcgroup v1と
OS未変更の記載は2026-10-30当日の履歴です。この承認済み更新とは時点を分けて扱います。

更新版は公式 [WSL 3.0.3](https://github.com/microsoft/WSL/releases/tag/3.0.3) と
[Docker Desktop 4.97.0](https://docs.docker.com/desktop/release-notes/#4970) の配布物を使用し、
公式checksumとMicrosoft/DockerのAuthenticode署名を照合しました。ここに記載する版は
今回の実測であり、全PCへの自動更新や新しい利用条件の自動承諾を意味しません。

| コンテナ/ツール | 採用した固定参照 |
|---|---|
| Python | 3.11.18-slim-bookworm（Dockerfile内digest固定） |
| Node | 24.18.0-bookworm-slim（digest固定） |
| PostgreSQL | 17.11-bookworm（digest固定） |
| nginx | 1.30.6-alpine（digest固定） |
| uv image | ghcr.io/astral-sh/uv:0.11.19 |
| kind / node | v0.33.0 / v1.37.0（node digest固定） |
| Browser image | mcr.microsoft.com/playwright:v1.64.1-noble |

Docker Hubのtag APIと公式kind releaseで選択し、image digestを設定へ記録しました。
CLIのkind binaryは公式SHA256SUMで確認します。固定値の取得と、コンテナでの動作確認は別の証拠です。

参照した一次資料:

- [uv projects/lockfile](https://docs.astral.sh/uv/concepts/projects/)
- [FastAPI versions](https://fastapi.tiangolo.com/deployment/versions/)
- [Vite guide](https://vite.dev/guide/)
- [kind quick start](https://kind.sigs.k8s.io/docs/user/quick-start/)
- [Kubernetes client](https://github.com/kubernetes-client/python)
- [Python image](https://hub.docker.com/_/python)、[Node image](https://hub.docker.com/_/node)
- [PostgreSQL image](https://hub.docker.com/_/postgres)、[nginx image](https://hub.docker.com/_/nginx)
- [Playwright Docker](https://playwright.dev/docs/docker)

依存更新はlockfileを更新し、互換性・契約・unit/buildと実runtimeの影響gateを再実行してください。
初期実装時にはLICENSEがなく未選定でしたが、2026-10-31の利用者の選択に従い、
ProtoHub本体へ [MIT License](../LICENSE) を追加しました。第三者の既存表示は維持します。
モデル名・有料API・組織固有設定は追加していません。

2026-10-31のnpm advisory照合では、webの全依存にmoderateが13件、high/criticalは0件、
`--omit=dev`のgraphには0件でした。13件は開発toolchainのminimatch advisoryに由来します。
実行用web imageはnginxとbuild済みdistだけで、Node/dev node_modulesを含みません。
これはnpm照合範囲の結果であり、Python/nginx/OSや全脆弱性を保証する検査ではありません。
詳細は [上流advisory](https://github.com/isaacs/minimatch/security/advisories/GHSA-g3hv-75wg-m249)。
開発依存の互換更新は次の限定作業に残し、今回`npm audit fix --force`でmajor変更を混入させません。

## Dev Container

`.devcontainer/Dockerfile` は検証imageと同じPython 3.11.18、Node 24.18.0のdigestとuv 0.11.19を
使います。npmはNode image付属の11.16.0です。Git/make/gosu等はimage内だけへ導入し、
実際の版を `/usr/local/share/protohub-toolchain.txt` に記録します。
Python環境とNode依存はDev Containerごとに独立したnamed volumeへ配置します。

設定・CLI実検証は [DEV_CONTAINER.md](DEV_CONTAINER.md) を参照してください。
検証用CLIは公式npm package `@devcontainers/cli@0.90.0`（Node >=20）を一時directoryで使い、
ホストへグローバル導入しません。CIも同じCLI版をrunner一時directoryへ導入し、
buildxの存在を明示的に確認します。公式 `devcontainers/ci` のv0.3をcommit SHAで固定し、
`push: never` / `inheritEnv: false` で `make check-dev` を実行します。
アプリのfull gateは別jobの従来の `make verify` を維持します。

- [Dev Containers CLI公式](https://github.com/devcontainers/cli)
- [devcontainers/ci固定参照](https://github.com/devcontainers/ci/tree/513af61f4de4f75d37e4438f184ba4358f0fc1ca)
