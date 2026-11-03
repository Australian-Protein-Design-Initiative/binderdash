# Binderdash desktop

Native desktop build using [pywebview](https://github.com/r0x0r/pywebview) and [PyInstaller](https://pyinstaller.org/).

## Prerequisites

- Python 3.11+ with [uv](https://github.com/astral-sh/uv)
- Node.js + pnpm (to build the frontend SPA)
- Platform WebView runtime:
  - **Windows:** [WebView2](https://developer.microsoft.com/en-us/microsoft-edge/webview2/)
  - **macOS:** system WebKit
  - **Linux (runtime):** `libwebkit2gtk-4.1-0`, `libgtk-3-0`, GTK/GObject libraries (PyGObject `gi` is bundled in the AppImage)
- **Linux (build):** `python3-gi`, `python3-gi-cairo`, `gir1.2-gtk-3.0`, `gir1.2-webkit2-4.1`, plus GTK/WebKit dev packages (see CI workflow)

## Development (no PyInstaller)

```bash
cd frontend && pnpm install && pnpm run build
cd ..
uv pip install -r backend/requirements.txt
uv pip install pywebview
uv run python -m desktop.main
```

The desktop launcher sets `BINDERDASH_DESKTOP=true`, disables authentication, stores SQLite under the platform user data directory, and opens a pywebview window at `http://127.0.0.1:8765/`.

### User data locations

| OS | Path |
|----|------|
| Windows | `%LOCALAPPDATA%\Binderdash` |
| macOS | `~/Library/Application Support/Binderdash` |
| Linux | `$XDG_DATA_HOME/binderdash` or `~/.local/share/binderdash` |

Files: `binderdash.sqlite`, `desktop.json`, `binderdash.log`.

## CI releases (GitHub Actions)

The [`.github/workflows/desktop-release.yml`](../.github/workflows/desktop-release.yml) workflow builds all three platforms in parallel.

| Trigger | Behaviour |
|---------|-----------|
| Push a `v*` tag (e.g. `v0.4.2`) | Builds Linux AppImage, macOS zip, and Windows zip, then publishes them to a [GitHub Release](https://docs.github.com/en/repositories/releasing-projects-on-github/managing-releases-in-a-repository) |
| Manual **workflow_dispatch** | Builds and uploads workflow artifacts only (no GitHub Release) |

To publish a desktop release:

```bash
git tag v0.4.2
git push origin v0.4.2
```

Tag the version in `backend/pyproject.toml` to match the release tag.

## Building release artifacts locally

Run from the repository root. PyInstaller must run on each target OS (no cross-compilation).

| OS | Command | Output |
|----|---------|--------|
| Linux | `bash desktop/packaging/build-linux-appimage.sh` | `dist/Binderdash-<ver>-<arch>.AppImage` |
| macOS | `bash desktop/packaging/build-macos.sh` | `dist/Binderdash-<ver>-macos-<arch>.zip` |
| Windows | `powershell -File desktop/packaging/build-windows.ps1` | `dist/Binderdash-<ver>-win64.zip` |

Low-level PyInstaller only:

```bash
bash desktop/packaging/build-common.sh
```

## First run

On first launch, open the **Ingest Runs** tab and use **Choose folder** to set the run base directory (where pipeline output folders live). This is persisted in `desktop.json`.

Unsigned builds: see `README.txt` inside each release zip for Gatekeeper / SmartScreen notes.

## Environment overrides (development)

See [`desktop/.env.desktop.example`](.env.desktop.example). Desktop mode force-sets `BINDERDASH_DESKTOP` and `DISABLE_AUTHENTICATION`; other values can be overridden via `.env` when testing.
