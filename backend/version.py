"""Build identity: app version plus, where discoverable, the git commit it was built from.

Resolution is deliberately layered because the three ways Binderdash ships have three
different sources of truth: a git checkout has ``.git``, a Docker image has neither
``.git`` nor a useful ``__file__`` layout but does get build args, and a PyInstaller
bundle has neither and cannot shell out to git. See ``build_identity``.
"""

from __future__ import annotations

import json
import logging
import os
import platform
import re
import subprocess
import sys
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Literal, Optional

from .runtime_paths import backend_root, is_frozen

logger = logging.getLogger(__name__)

BuildSource = Literal["env", "build_file", "git", "unknown"]

BUILD_INFO_BASENAME = "_build_info.json"
_GIT_TIMEOUT_SECONDS = 2


@dataclass(frozen=True)
class BuildIdentity:
    app_version: str
    git_commit: Optional[str] = None
    git_dirty: Optional[bool] = None
    source: BuildSource = "unknown"


def _version_from_metadata() -> Optional[str]:
    try:
        from importlib.metadata import version

        return version("binderdash-backend")
    except Exception:
        return None


def _version_from_pyproject() -> Optional[str]:
    try:
        text = (backend_root() / "pyproject.toml").read_text(encoding="utf-8")
    except OSError:
        return None
    match = re.search(r'^version\s*=\s*"([^"]+)"', text, re.MULTILINE)
    return match.group(1) if match else None


def _build_info_path() -> Path:
    if is_frozen():
        return Path(sys._MEIPASS) / "backend" / BUILD_INFO_BASENAME  # type: ignore[attr-defined]
    return backend_root() / BUILD_INFO_BASENAME


def _from_build_file() -> Optional[dict]:
    path = _build_info_path()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


def _repo_root() -> Optional[Path]:
    """The checkout root, only if this really is a git working tree."""
    root = backend_root().parent
    return root if (root / ".git").exists() else None


def _git(args: list[str], cwd: Path) -> Optional[str]:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=_GIT_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        # git absent, or a hung index lock. Build identity is never worth failing over.
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip()


@lru_cache(maxsize=1)
def build_identity() -> BuildIdentity:
    """Resolve build identity once per process.

    Called lazily (first bundle download), never at import: the git fallback shells out,
    and paying for that at startup would slow every process that never builds a bundle.
    """
    version = (
        (os.environ.get("BINDERDASH_VERSION") or "").strip()
        or _version_from_metadata()
        or _version_from_pyproject()
        or "0.0.0"
    )

    env_commit = (os.environ.get("BINDERDASH_GIT_COMMIT") or "").strip()
    if env_commit:
        return BuildIdentity(app_version=version, git_commit=env_commit, source="env")

    payload = _from_build_file()
    if payload:
        commit = str(payload.get("git_commit") or "").strip() or None
        dirty = payload.get("git_dirty")
        return BuildIdentity(
            app_version=str(payload.get("version") or version),
            git_commit=commit,
            git_dirty=bool(dirty) if isinstance(dirty, bool) else None,
            source="build_file",
        )

    repo_root = _repo_root()
    if repo_root is not None:
        commit = _git(["rev-parse", "--short=12", "HEAD"], repo_root)
        if commit:
            status = _git(["status", "--porcelain"], repo_root)
            return BuildIdentity(
                app_version=version,
                git_commit=commit,
                git_dirty=bool(status) if status is not None else None,
                source="git",
            )

    return BuildIdentity(app_version=version, source="unknown")


def build_label() -> str:
    """One-line build identity, as shown in the UI footer and generated scripts."""
    identity = build_identity()
    if not identity.git_commit:
        return identity.app_version
    suffix = ", modified" if identity.git_dirty else ""
    return f"{identity.app_version} ({identity.git_commit}{suffix})"


def build_payload() -> dict:
    """Build identity as JSON, for /health and the UI footer."""
    identity = build_identity()
    return {
        "version": identity.app_version,
        "git_commit": identity.git_commit,
        "git_dirty": identity.git_dirty,
        "label": build_label(),
    }


def app_version() -> str:
    return build_identity().app_version


def git_commit() -> Optional[str]:
    return build_identity().git_commit


def python_version() -> str:
    return platform.python_version()


def platform_label() -> str:
    return f"{platform.system()} {platform.machine()}".strip()
