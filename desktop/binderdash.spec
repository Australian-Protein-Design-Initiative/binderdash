# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for Binderdash desktop. Run from repository root."""

import importlib.util
import sys
import tempfile
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_data_files, collect_submodules

block_cipher = None
_spec_path = Path(SPECPATH).resolve()
desktop_dir = _spec_path.parent if _spec_path.suffix == ".spec" else _spec_path
repo_root = desktop_dir.parent
static_dir = repo_root / "backend" / "static"

if not static_dir.is_dir():
    raise SystemExit(
        f"Frontend bundle missing at {static_dir}. "
        "Run: cd frontend && pnpm run build"
    )

datas = [
    (str(static_dir), "backend/static"),
]

# Written by packaging/build-common.sh; backend/version.py reads it because a frozen
# build has no .git to interrogate.
_build_info = repo_root / "backend" / "_build_info.json"
if _build_info.is_file():
    datas.append((str(_build_info), "backend"))

def _add_package_datas(import_name: str, subpath: str, dest: str) -> None:
    try:
        import importlib

        mod = importlib.import_module(import_name)
        src = Path(mod.__file__).resolve().parent / subpath
        if src.is_dir():
            datas.append((str(src), dest))
    except ImportError:
        pass


_add_package_datas("python_codon_tables", ".", "python_codon_tables")
_add_package_datas("dnachisel", "biotools/data", "dnachisel/biotools/data")

hiddenimports = [
    "uvicorn",
    "uvicorn.logging",
    "uvicorn.loops",
    "uvicorn.loops.auto",
    "uvicorn.protocols",
    "uvicorn.protocols.http",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.websockets",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.lifespan",
    "uvicorn.lifespan.on",
    "multipart",
    "httptools",
    "websockets",
    "websockets.legacy",
    "websockets.legacy.server",
    "anyio",
    "anyio._backends",
    "anyio._backends._asyncio",
    "pandas",
    "dnachisel",
    "Bio",
    "Bio.PDB",
    "python_codon_tables",
    "desktop",
    "desktop.config",
    "desktop.paths",
    "desktop.env",
    "backend",
    "backend.main",
    "backend.routers.desktop",
    "backend.runtime_paths",
    "backend.version",
    "backend.bundles",
    "backend.routers.bundles",
    "backend.persistence.sqlite_repo",
    "backend.util.codon_tables",
    "jose",
    "bcrypt",
    "starlette.middleware.sessions",
    "itsdangerous",
]

binaries: list = []
pathex = [str(repo_root)]
hooksconfig: dict = {}

if sys.platform == "linux":
    # pywebview on Linux needs PyGObject (gi). Ubuntu/Debian ship it for system Python
    # under dist-packages; include it in the frozen bundle.
    # Expose only the two distro packages pywebview needs, through a directory of
    # symlinks, rather than putting all of dist-packages on the search path.
    # PyInstaller prepends pathex to the module graph's path, so dist-packages there
    # shadows the build venv for every package present in both: that is how 0.4.2
    # shipped with the distro's numpy and a cryptography whose Python half and Rust
    # half came from different installations.
    _dist_packages = Path("/usr/lib/python3/dist-packages")
    if (_dist_packages / "gi").is_dir():
        _gi_only = Path(tempfile.mkdtemp(prefix="binderdash-gi-"))
        for _pattern in ("gi", "cairo", "PyGObject*", "pycairo*"):
            for _src in _dist_packages.glob(_pattern):
                (_gi_only / _src.name).symlink_to(_src)
        sys.path.append(str(_gi_only))
        pathex.append(str(_gi_only))

    for _pkg in ("gi", "cairo"):
        try:
            _d, _b, _h = collect_all(_pkg)
            datas += _d
            binaries += _b
            hiddenimports += _h
        except Exception:
            pass

    # collect_all skips extension modules (same gap as biotite below), so gi's
    # bindings have to be listed by hand. Importing them here under the build
    # interpreter is also the ABI check: distro PyGObject built for a different
    # Python minor version than the one running PyInstaller fails right here
    # rather than producing a bundle whose window never opens.
    try:
        import gi._gi as _gi_ext

        _gi_bins = [(_gi_ext.__file__, "gi")]
        try:
            import gi._gi_cairo as _gi_cairo_ext

            _gi_bins.append((_gi_cairo_ext.__file__, "gi"))
        except ImportError:
            pass
        binaries += _gi_bins
    except ImportError as exc:
        raise SystemExit(
            f"PyGObject bindings (gi._gi) are not importable under {sys.executable}: {exc}\n"
            "pywebview has no GUI backend without them, so the packaged app would "
            "start its server and never open a window.\n"
            "Install python3-gi for a Python matching this interpreter: "
            "sudo apt-get install python3-gi python3-gi-cairo gir1.2-gtk-3.0 "
            "gir1.2-webkit2-4.1"
        )

    hiddenimports += collect_submodules("gi")
    hiddenimports += [
        "gi._gi",
        "gi.repository.Gtk",
        "gi.repository.Gdk",
        "gi.repository.GLib",
        "gi.repository.GObject",
        "gi.repository.Gio",
        "gi.repository.GModule",
        "gi.repository.WebKit2",
        "gi.repository.Soup",
        "webview.platforms.gtk",
    ]
    hooksconfig = {
        "gi": {
            "icons": ["Adwaita"],
            "themes": ["Adwaita"],
            "languages": ["en_US", "en_GB"],
            "module-versions": {"Gtk": "3.0"},
        },
    }

# The Rust bindings and the Python layer of cryptography ship as one unit; a build
# environment holding halves of two releases yields an app that cannot import
# authlib, and so cannot serve /health. Fail here instead of at the user's first launch.
try:
    import cryptography.hazmat.primitives.hashes  # noqa: F401
except Exception as exc:
    raise SystemExit(
        f"cryptography is broken in the build environment: {exc}\n"
        "Its Python files and its _rust extension are probably from different "
        "releases. Reinstall it: uv pip install --reinstall -r backend/requirements.txt"
    )

# Importing biotite.structure pulls Cython extensions (sequence align) and the
# Rust extension biotite.rust. Modulegraph misses both: rust submodules are not
# files, and the align extensions are imported from a .pyx init. A frozen app
# then dies while importing backend.main and never binds /health.
# collect_dynamic_libs skips extension modules, so list the Rust .so directly.
# ProtOr radii need the bundled Chemical Component Dictionary.
_biotite_root = Path(importlib.util.find_spec("biotite").origin).resolve().parent
_rust_bins = [
    (str(so), "biotite")
    for pattern in ("rust*.so", "rust*.pyd")
    for so in _biotite_root.glob(pattern)
]
if not _rust_bins:
    raise SystemExit(
        "biotite.rust extension was not found. "
        "The desktop app imports it at startup and cannot start without it."
    )
binaries += _rust_bins
datas += collect_data_files(
    "biotite",
    includes=["**/*.bcif", "**/*.json", "**/*.mat", "**/*.txt", "**/*.kerasify"],
)
hiddenimports += collect_submodules("biotite")

a = Analysis(
    [str(desktop_dir / "main.py")],
    pathex=pathex,
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[str(desktop_dir / "hooks")],
    hooksconfig=hooksconfig,
    runtime_hooks=[],
    # fastmcp is an optional extra. If it happens to be installed in the build
    # environment, bundling it pulls the mcp SDK, which fails at import in a
    # frozen app. Desktop builds leave the endpoint unmounted.
    # pkg_resources is referenced only from build-time helpers (pycairo's
    # get_include(), pygments' plugin lookup). Bundling it adds a runtime hook that
    # runs before main() and aborts the app when its vendored dependencies are
    # incomplete, which is what modern setuptools, having dropped pkg_resources
    # entirely, guarantees.
    excludes=[
        "tkinter",
        "matplotlib",
        "pytest",
        "fastmcp",
        "mcp",
        "pkg_resources",
        "setuptools",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

icon_arg = {}
assets = desktop_dir / "assets"
if sys.platform == "win32":
    ico = assets / "binderdash.ico"
    if ico.is_file():
        icon_arg["icon"] = str(ico)
elif sys.platform == "darwin":
    icns = assets / "binderdash.icns"
    if icns.is_file():
        icon_arg["icon"] = str(icns)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Binderdash",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=sys.platform == "linux",
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    **icon_arg,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="Binderdash",
)

if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name="Binderdash.app",
        icon=str(assets / "binderdash.icns") if (assets / "binderdash.icns").is_file() else None,
        bundle_identifier="edu.unimelb.knottlab.binderdash",
    )
