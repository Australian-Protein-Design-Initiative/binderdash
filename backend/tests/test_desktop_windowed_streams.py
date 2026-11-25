"""A windowed frozen build has no console attached.

Every Windows desktop build is windowed, and so starts with sys.stdout and
sys.stderr set to None. uvicorn's log formatter calls sys.stdout.isatty() while
configuring logging, which aborted startup before the server ever bound a port.
CI only catches this when it launches the executable the way a user does, so
keep the stream fallback covered here too.
"""

import sys

import uvicorn.logging

from desktop.main import _redirect_missing_streams


def test_logging_configures_with_no_console(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "stdout", None)
    monkeypatch.setattr(sys, "stderr", None)

    log_file = tmp_path / "not-created-yet" / "binderdash.log"
    assert _redirect_missing_streams(log_file) is True

    assert sys.stdout is not None
    assert sys.stderr is not None

    # The formatter uvicorn.Config installs, and the exact call that raised.
    uvicorn.logging.DefaultFormatter(fmt="%(message)s")

    print("output from a windowed build")
    sys.stdout.flush()
    assert "output from a windowed build" in log_file.read_text()


def test_existing_streams_are_left_alone(tmp_path, monkeypatch):
    sentinel = object()
    monkeypatch.setattr(sys, "stdout", sentinel)
    monkeypatch.setattr(sys, "stderr", sentinel)

    log_file = tmp_path / "binderdash.log"
    # False tells main() the stream handler already covers the log file, so it
    # must not add a FileHandler on top and log every record twice.
    assert _redirect_missing_streams(log_file) is False

    assert sys.stdout is sentinel
    assert sys.stderr is sentinel
    assert not log_file.exists()
