#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

VERSION="$(grep -E '^version = ' backend/pyproject.toml | head -1 | sed 's/.*"\(.*\)".*/\1/')"

if [[ ! -f backend/static/index.html ]]; then
  echo "Building frontend..."
  (cd frontend && pnpm install && pnpm run build)
fi

# python3-gi is checked by binderdash.spec, against the interpreter that actually runs
# PyInstaller. Checking /usr/bin/python3 here passed on a machine whose distro Python
# was a different minor version from the build venv, and the bundle shipped without
# gi's bindings.

echo "Installing backend + desktop dependencies..."
uv pip install -r backend/requirements.txt
# --no-deps: without it the editable install re-resolves the backend's own unpinned
# dependencies and silently upgrades them over the versions pinned on the line above,
# so the bundle stops matching requirements.txt.
uv pip install -e backend --no-deps 2>/dev/null || uv pip install -r backend/requirements.txt
# Linux GTK/WebKit bindings come from distro python3-gi (bundled via binderdash.spec).
# pywebview[gtk] would pull pip pygobject and fail to compile in CI.
uv pip install pywebview pyinstaller

# A frozen build has no .git and no installed dist-info, so the commit has to be baked
# in here for downloaded bundles to record which build produced them.
GIT_COMMIT="$(git rev-parse --short=12 HEAD 2>/dev/null || echo '')"
GIT_DIRTY="false"
if [[ -n "$(git status --porcelain 2>/dev/null)" ]]; then GIT_DIRTY="true"; fi
cat > backend/_build_info.json <<JSON
{
  "version": "${VERSION}",
  "git_commit": "${GIT_COMMIT}",
  "git_dirty": ${GIT_DIRTY},
  "built_at": "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
}
JSON

echo "Running PyInstaller..."
pyinstaller --noconfirm desktop/binderdash.spec

echo "Build complete (version ${VERSION}). Output under dist/"
