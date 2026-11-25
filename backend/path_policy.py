import os
from pathlib import Path
from typing import Any, Dict, List


def resolved_base_dirs(base_dirs: List[str]) -> List[Path]:
    out: List[Path] = []
    for raw in base_dirs:
        s = raw.strip()
        if not s:
            continue
        try:
            out.append(Path(s).expanduser().resolve())
        except (OSError, RuntimeError):
            continue
    return out


def is_under_any_base(candidate: Path, bases: List[Path]) -> bool:
    for base in bases:
        if candidate == base:
            return True
        try:
            candidate.relative_to(base)
            return True
        except ValueError:
            continue
    return False


def is_allowed_path(path_str: str, base_dir_strings: List[str]) -> bool:
    """True if path_str resolves to a location under one of the base dirs.

    No base dirs means nothing is allowed. (It used to mean everything was.)
    """
    try:
        candidate = Path(path_str).expanduser().resolve()
    except (OSError, RuntimeError):
        return False
    return is_under_any_base(candidate, resolved_base_dirs(base_dir_strings))


def normalised_path(path_str: str) -> str:
    """Absolute, with ``..`` collapsed, but symlinks left alone."""
    return os.path.normpath(os.path.abspath(os.path.expanduser(path_str)))


def is_within_bases(path_str: Any, base_dir_strings: List[str]) -> bool:
    """Lexical containment, for paths that discovery produced or that are stored.

    Deliberately does not resolve symlinks in ``path_str``: ``find_runs_recursive``
    follows links, so a run reached through a symlink inside a base dir is recorded
    under that base and must still count as inside it. ``..`` is collapsed, so it
    cannot be used to step out. Each base is matched both as written and resolved,
    because ``/api/tree`` hands out resolved base paths.

    Compared through ``os.path.normcase``: identity on POSIX, but on Windows the
    filesystem is case-insensitive, and a base written ``C:\\Runs`` would otherwise
    fail to contain a stored run path spelled ``c:\\runs\\...``, dropping the run at
    startup. ``is_under_any_base`` needs no equivalent - ``PurePath`` comparison is
    already case-insensitive under the Windows flavour.
    """
    if not isinstance(path_str, str) or not path_str.strip():
        return False
    candidate = os.path.normcase(normalised_path(path_str))
    for raw in base_dir_strings:
        s = raw.strip()
        if not s:
            continue
        forms = {normalised_path(s)}
        try:
            forms.add(str(Path(s).expanduser().resolve()))
        except (OSError, RuntimeError):
            pass
        for base in (os.path.normcase(f) for f in forms):
            if candidate == base or candidate.startswith(base.rstrip(os.sep) + os.sep):
                return True
    return False


def run_paths_within_bases(run: Dict[str, Any], base_dir_strings: List[str]) -> bool:
    """Every file location a stored run can make the server read is inside a base dir.

    Covers the run folder(s), each structure file the file endpoints serve, and the
    results table that ``load_run_table`` joins onto each folder.
    """
    folders = run.get("merged_paths") or [run.get("path")]
    paths: List[Any] = [run.get("path"), *folders, *(run.get("pdb_files") or [])]
    results_table = run.get("results_table")
    if results_table:
        paths.extend(
            os.path.join(f, str(results_table)) for f in folders if isinstance(f, str)
        )
    return all(is_within_bases(p, base_dir_strings) for p in paths)
