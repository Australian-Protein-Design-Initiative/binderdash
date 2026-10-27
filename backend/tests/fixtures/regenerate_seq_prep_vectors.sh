#!/usr/bin/env bash
# Regenerate seq_prep_vectors.json from the original TypeScript implementation.
#
# Only needed if the TS in frontend/src/utils/protParam.ts or
# frontend/src/stores/shortName.ts changes. The vectors exist to prove the Python
# port in backend/seq_prep/ still agrees with the TS that produced real orders.
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
frontend="$here/../../../frontend"
# esbuild comes in transitively with vite, so there is no node_modules/.bin link
# and the .pnpm path carries the version. Take whichever one is installed.
esbuild="$(find "$frontend/node_modules/.pnpm" -maxdepth 5 -path '*/esbuild/bin/esbuild' -type f -print -quit 2>/dev/null || true)"
[ -n "$esbuild" ] && [ -x "$esbuild" ] || { echo "esbuild not found; run pnpm install in frontend/" >&2; exit 1; }
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
"$esbuild" "$frontend/scripts/genSeqPrepVectors.ts" \
    --bundle --platform=node --format=esm --outfile="$tmp/gen.mjs" --log-level=warning
node "$tmp/gen.mjs" > "$here/seq_prep_vectors.json"
echo "wrote $here/seq_prep_vectors.json"
