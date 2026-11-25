#!/usr/bin/env python3
"""Binderdash desktop entry: embedded uvicorn + pywebview window."""

from __future__ import annotations

import html
import importlib
import logging
import socket
import sys
import threading
import time
import traceback
import urllib.error
import urllib.request
from pathlib import Path

# Ensure repo root is on sys.path before local imports when run as script.
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from desktop.config import DesktopConfig, load_config, save_config
from desktop.env import apply_desktop_env
from desktop.paths import is_frozen, repo_root, user_data_dir

logger = logging.getLogger(__name__)

DEFAULT_PORT = 8765
# A cold start of the frozen bundle on Windows spends ~30s importing before
# uvicorn binds: the extracted files are not in the page cache and Defender
# scans each one. Measured at 47s to a healthy /health on a clean Windows 11
# VM, against the 10s this used to allow - so the app reported a startup
# failure while its own backend was still coming up behind the error window.
# Waiting longer is free: _wait_for_health returns as soon as the server
# thread dies, so a backend that genuinely cannot start still fails fast.
HEALTH_TIMEOUT_S = 180.0
HEALTH_POLL_INTERVAL_S = 0.2


def _pick_port(preferred: int = DEFAULT_PORT) -> int:
    for port in (preferred, 0):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.bind(("127.0.0.1", port))
                return sock.getsockname()[1]
        except OSError:
            continue
    raise RuntimeError("Could not bind a localhost port for Binderdash")


_server_errors: list[BaseException] = []


def _wait_for_health(
    port: int, thread: threading.Thread, timeout: float = HEALTH_TIMEOUT_S
) -> bool:
    url = f"http://127.0.0.1:{port}/health"
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not thread.is_alive():
            return False
        try:
            with urllib.request.urlopen(url, timeout=1) as resp:
                if resp.status == 200:
                    return True
        except (urllib.error.URLError, TimeoutError, OSError):
            time.sleep(HEALTH_POLL_INTERVAL_S)
    return False


def _start_uvicorn(port: int) -> threading.Thread:
    import uvicorn

    config = uvicorn.Config(
        "backend.main:app",
        host="127.0.0.1",
        port=port,
        log_level="info",
        access_log=False,
    )
    server = uvicorn.Server(config)

    def run() -> None:
        try:
            server.run()
        except Exception as exc:
            _server_errors.append(exc)
            logger.exception("Binderdash backend failed to start")

    thread = threading.Thread(target=run, name="binderdash-uvicorn", daemon=True)
    thread.start()
    return thread


def _startup_failure_message(port: int, log_file: Path) -> str:
    url = f"http://127.0.0.1:{port}/health"
    if _server_errors:
        detail = "".join(traceback.format_exception(_server_errors[-1])).rstrip()
        return f"Binderdash backend failed to start on {url}\nSee log: {log_file}\n\n{detail}"
    return (
        f"Binderdash backend did not start within {HEALTH_TIMEOUT_S}s on {url}\n"
        f"See log: {log_file}"
    )


def _show_startup_error(message: str) -> None:
    try:
        import webview

        escaped = html.escape(message)
        webview.create_window("Binderdash — startup error", html=f"<pre>{escaped}</pre>")
        webview.start()
    except Exception:
        print(message, file=sys.stderr)


def _selftest(port: int, log_file: Path) -> int:
    """Start the backend and resolve a GUI toolkit, then exit.

    A frozen bundle missing a compiled extension module still builds, still
    launches, and only fails when the import that needs it runs. Packaging CI
    runs the built artifact with --selftest so that failure happens on the
    release build rather than on a user's machine.
    """
    server_thread = _start_uvicorn(port)
    if not _wait_for_health(port, server_thread):
        print(_startup_failure_message(port, log_file), file=sys.stderr)
        return 1

    # Imported this way deliberately: webview/__init__.py keeps a module-level
    # `guilib = None` that shadows the submodule until a window is created.
    guilib = importlib.import_module("webview.guilib")

    try:
        guilib.initialize()
    except Exception:
        traceback.print_exc()
        print(
            "selftest FAILED: backend serves /health but pywebview found no GUI "
            "toolkit, so the app would start without a window.",
            file=sys.stderr,
        )
        return 1

    print(f"selftest OK: backend healthy on port {port}, GUI toolkit available")
    return 0


class DesktopApi:
    """JS bridge exposed to the SPA via pywebview."""

    def select_run_base_dir(self) -> str | None:
        import webview

        if not webview.windows:
            return None
        result = webview.windows[0].create_file_dialog(webview.FOLDER_DIALOG)
        if not result:
            return None
        if isinstance(result, (list, tuple)):
            return str(result[0]) if result else None
        return str(result)


def _persist_window_geometry(config: DesktopConfig) -> None:
    try:
        import webview

        if not webview.windows:
            return
        win = webview.windows[0]
        config.window.width = int(win.width or config.window.width)
        config.window.height = int(win.height or config.window.height)
        save_config(config)
    except Exception as e:
        logger.debug("Could not persist window geometry: %s", e)


def _redirect_missing_streams(log_file: Path) -> bool:
    """Give a windowed build somewhere to write.

    A frozen windowed app - every Windows build, and a macOS .app opened from
    Finder - starts with no console attached, so sys.stdout and sys.stderr are
    None. Anything that inspects them then fails before the app can start:
    uvicorn's log formatter calls sys.stdout.isatty() and brings down logging
    configuration with it. Point them at the log file rather than discarding
    them, so uvicorn's own output still reaches a user's bug report.

    Returns whether it redirected, so the caller can skip adding a second
    handler on the same file - basicConfig's stream handler already writes
    there, and two handlers logged every record twice.
    """
    if sys.stdout is not None and sys.stderr is not None:
        return False

    log_file.parent.mkdir(parents=True, exist_ok=True)
    stream = open(log_file, "a", encoding="utf-8", buffering=1)
    if sys.stdout is None:
        sys.stdout = stream
    if sys.stderr is None:
        sys.stderr = stream
    return True


def main() -> int:
    log_file = user_data_dir() / "binderdash.log"
    streams_redirected = _redirect_missing_streams(log_file)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    port = _pick_port()
    config = apply_desktop_env(port)

    if not streams_redirected:
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setFormatter(
            logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
        )
        logging.getLogger().addHandler(file_handler)

    logger.info(
        "Starting Binderdash desktop (frozen=%s, port=%s, data_dir=%s)",
        is_frozen(),
        port,
        user_data_dir(),
    )

    if "--selftest" in sys.argv[1:]:
        return _selftest(port, log_file)

    server_thread = _start_uvicorn(port)

    if not _wait_for_health(port, server_thread):
        msg = _startup_failure_message(port, log_file)
        logger.error(msg)
        _show_startup_error(msg)
        return 1

    import webview

    url = f"http://127.0.0.1:{port}/"
    window = webview.create_window(
        "Binderdash",
        url,
        width=config.window.width,
        height=config.window.height,
        min_size=(900, 600),
        js_api=DesktopApi(),
    )

    def on_closed() -> None:
        _persist_window_geometry(config)

    window.events.closed += on_closed
    webview.start()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
