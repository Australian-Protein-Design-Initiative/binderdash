"""Discover input / target structure files referenced by run parameter JSON."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

from ..config.method_paths import STRUCTURE_PARAM_KEYS_BY_METHOD
from ..run_discovery import parse_run_params

_STRUCTURE_EXT_RE = re.compile(
    r".+\.(?:pdb|cif)(?:\.gz)?$", re.IGNORECASE
)

# Config-mode workflows (``--rfd4_config``, ``--bc2_config``, ``--boltzgen_config``)
# name their target inside a spec file rather than in params.json, so params alone
# yields no structure. One hop into such a spec covers all of them.
_CONFIG_EXT_RE = re.compile(r".+\.(?:ya?ml|json)$", re.IGNORECASE)


@dataclass(frozen=True)
class InputTargetInfo:
    """Resolved input structure under the run directory."""

    id: str
    label: str
    path: Path
    relative_path: str


def _is_structure_like_string(s: str) -> bool:
    t = s.strip()
    if len(t) < 5 or t.startswith(("http://", "https://")):
        return False
    return bool(_STRUCTURE_EXT_RE.match(t))


def _is_config_like_string(s: str) -> bool:
    t = s.strip()
    if len(t) < 5 or t.startswith(("http://", "https://")):
        return False
    return bool(_CONFIG_EXT_RE.match(t))


def _structure_paths_in_config(config_path: Path) -> List[str]:
    """Structure paths named inside a YAML/JSON spec, resolved against the spec's own
    directory (how every config-mode workflow resolves them)."""
    try:
        text = config_path.read_text(encoding="utf-8")
    except OSError:
        return []
    try:
        import yaml  # YAML is a superset of JSON, so this covers both.

        data = yaml.safe_load(text)
    except Exception:
        return []
    strings: List[str] = []
    _walk_string_values(data, strings)
    out: List[str] = []
    for value in strings:
        if not _is_structure_like_string(value):
            continue
        candidate = Path(value.strip())
        out.append(
            str(candidate if candidate.is_absolute() else config_path.parent / candidate)
        )
    return out


def _resolve_under_run(run_path: Path, raw: str) -> Optional[Path]:
    raw = raw.strip()
    if not raw:
        return None
    candidate = Path(raw)
    if candidate.is_absolute():
        try:
            resolved = candidate.resolve()
        except OSError:
            return None
        run_resolved = run_path.resolve()
        if resolved == run_resolved or run_resolved in resolved.parents:
            return resolved if resolved.is_file() else None
        return None
    for base in (run_path, run_path.parent):
        p = (base / raw).resolve()
        try:
            p.relative_to(run_path.resolve())
        except ValueError:
            continue
        if p.is_file():
            return p
    p = (run_path / raw).resolve()
    try:
        p.relative_to(run_path.resolve())
    except ValueError:
        return None
    if p.is_file():
        return p
    return None


def _collect_keyed_strings(
    params: Any, keys: Set[str], out: List[Tuple[str, str]]
) -> None:
    if isinstance(params, dict):
        for k, v in params.items():
            if isinstance(k, str) and k in keys and isinstance(v, str):
                out.append((k, v))
            _collect_keyed_strings(v, keys, out)
    elif isinstance(params, list):
        for item in params:
            _collect_keyed_strings(item, keys, out)


def _walk_string_values(params: Any, out: List[str]) -> None:
    if isinstance(params, dict):
        for v in params.values():
            _walk_string_values(v, out)
    elif isinstance(params, list):
        for item in params:
            _walk_string_values(item, out)
    elif isinstance(params, str):
        out.append(params)


def _ordered_unique_paths(
    run_path: Path, pairs: Iterable[Tuple[str, str]]
) -> List[Tuple[str, Path]]:
    seen: Set[str] = set()
    result: List[Tuple[str, Path]] = []
    for label_hint, raw in pairs:
        p = _resolve_under_run(run_path, raw)
        if p is None:
            continue
        key = str(p.resolve())
        if key in seen:
            continue
        seen.add(key)
        result.append((label_hint, p))
    return result


def list_input_targets(run_metadata: Dict[str, Any]) -> List[InputTargetInfo]:
    """Return input/target structure files found from params and path heuristics."""
    run_path_str = run_metadata.get("path") or ""
    if not run_path_str:
        return []
    run_path = Path(run_path_str)
    if not run_path.is_dir():
        return []

    params = parse_run_params(run_metadata)
    method = (run_metadata.get("method") or "").lower()

    pairs: List[Tuple[str, str]] = []
    keys = set(STRUCTURE_PARAM_KEYS_BY_METHOD.get(method, ()))
    keyed: List[Tuple[str, str]] = []
    if params is not None and keys:
        _collect_keyed_strings(params, keys, keyed)
    for key_name, val in keyed:
        if _is_structure_like_string(val):
            pairs.append((key_name, val))

    if params is not None:
        strings: List[str] = []
        _walk_string_values(params, strings)
        for s in strings:
            if _is_structure_like_string(s):
                pairs.append(("params", s))

        for s in strings:
            if not _is_config_like_string(s):
                continue
            config_path = _resolve_under_run(run_path, s)
            if config_path is None:
                continue
            for nested in _structure_paths_in_config(config_path):
                pairs.append((config_path.name, nested))

    ordered = _ordered_unique_paths(run_path, pairs)

    out: List[InputTargetInfo] = []
    for label_hint, p in ordered:
        try:
            rel = str(p.resolve().relative_to(run_path.resolve()))
        except ValueError:
            rel = p.name
        label = f"{p.name} ({label_hint})" if label_hint else p.name
        out.append(
            InputTargetInfo(
                id=str(len(out)),
                label=label,
                path=p,
                relative_path=rel,
            )
        )

    return out


def find_input_target_by_id(
    run_metadata: Dict[str, Any], target_id: str
) -> Optional[InputTargetInfo]:
    targets = list_input_targets(run_metadata)
    for t in targets:
        if t.id == target_id:
            return t
    return None
