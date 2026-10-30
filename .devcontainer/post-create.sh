#!/usr/bin/env bash
set -euo pipefail

if [[ "$(id -u)" == 0 ]]; then
  printf 'Run post-create as the non-root developer user.\n' >&2
  exit 1
fi

cd /workspaces/protohub
uv sync --project apps/server --locked --python /usr/local/bin/python
npm --prefix apps/web ci --no-audit --no-fund
npm --prefix tests/e2e ci --no-audit --no-fund
make skills-check

printf '\nProtoHub toolchain ready. Run make check-dev here; run app Docker/kind commands in the WSL host checkout.\n'
