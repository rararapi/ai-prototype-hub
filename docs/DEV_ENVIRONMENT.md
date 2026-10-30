# 開発環境と依存版（2026-10-30 JST）

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
| React / Vite / TypeScript | 19.3.1 / 8.3.5 / package-lock参照 |
| Vitest / openapi-typescript / Playwright | 5.0.5 / 7.13.0 / 1.64.1 |

ハーネス・doctor・ローカルlauncherはPython 3.10以上の標準ライブラリで動きます。
WSLはUbuntu 22.04.3 LTS / kernel 5.15.146.1、Docker server 25.0.3、
Compose v2.24.6、buildx v0.12.1を確認しました。最初はDocker未接続でしたが検証中に接続可能となりました。
ホストOSのサービス・権限・WSL設定は変更していません。

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
LICENSEは元から存在せず、今回も未選定のままです。モデル名・有料API・組織固有設定は追加していません。
