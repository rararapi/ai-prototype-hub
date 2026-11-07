#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/../../apps/web"
npm run lint
npm run typecheck
npm run test:unit
npm run build
# The regular build must not contain the browser-only transport.
if find dist/assets \( -name 'demo-*.js' -o -name 'DemoBuilder-*.js' -o -name 'DemoCreation-*.js' -o -name 'DemoPreview-*.js' -o -name 'DemoShareEditor-*.js' \) -print | grep -q .; then
  echo 'FAIL: demo transport present in regular build' >&2
  exit 1
fi
test ! -f dist/demo-preview.html
npm run build:demo
test -f dist/index.html
test -f dist/demo-preview.html
grep -q 'src="./assets/' dist/index.html
node scripts/verify-demo.mjs
echo 'PASS: regular build and relative-path static demo'
