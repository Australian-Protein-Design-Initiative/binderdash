import json
import logging
from typing import Any, Dict, List, Optional, Tuple

from .config.run_signatures import run_folder_signatures
from .run_discovery import parse_designs_from_run
from .util.profiling import Timer


logger = logging.getLogger(__name__)


run_cache: Dict[str, Dict[str, Any]] = {}
designs_cache: List[Dict[str, Any]] = []
# Per-run design rows; avoids scanning the full flat cache when serving run_ids queries.
designs_by_run_id: Dict[str, List[Dict[str, Any]]] = {}


# Build a lookup of method -> (primary_score_columns, sort_ascending) from signatures.
# Uses the first signature found for each method (highest priority).
_method_score_config: Dict[str, Tuple[List[str], bool]] = {}
for sig in sorted(run_folder_signatures, key=lambda s: s.get("priority", 999)):
    method = sig.get("method")
    if method and method not in _method_score_config:
        score_cols = sig.get("primary_score_columns", [])
        sort_asc = sig.get("sort_ascending", True)
        _method_score_config[method] = (score_cols, sort_asc)


def get_run_metadata(run_id: str) -> Optional[Dict[str, Any]]:
    return run_cache.get(run_id)


def _get_design_score(design: Dict[str, Any]) -> Tuple[bool, float]:
    """Primary score for sorting, from the method's signature config.

    Returns:
        (has_score, sort_value) where sort_value is adjusted for sort direction.
    """
    method = design.get("method")
    if not method or method not in _method_score_config:
        return (False, float("inf"))

    score_cols, sort_ascending = _method_score_config[method]

    for col in score_cols:
        score = design.get(col)
        if score is not None:
            try:
                score_val = float(score)
                # Ascending: lower is better (return as-is). Descending: negate for sort key.
                sort_value = score_val if sort_ascending else -score_val
                return (True, sort_value)
            except (TypeError, ValueError):
                continue

    return (False, float("inf"))


def _sort_designs_list(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Sort designs within one run by primary score (scored first, then unscored)."""
    designs_with_score: List[Dict[str, Any]] = []
    designs_without_score: List[Dict[str, Any]] = []
    for design in rows:
        has_score, _ = _get_design_score(design)
        if has_score:
            designs_with_score.append(design)
        else:
            designs_without_score.append(design)
    designs_with_score.sort(key=lambda d: _get_design_score(d)[1])
    return designs_with_score + designs_without_score


def _rebuild_flat_cache_from_index() -> None:
    """Rebuild the legacy flat list from designs_by_run_id (for list-all / refresh)."""
    global designs_cache
    flat: List[Dict[str, Any]] = []
    for rid in sorted(designs_by_run_id.keys()):
        flat.extend(designs_by_run_id[rid])
    designs_cache.clear()
    designs_cache.extend(flat)


def _store_designs_for_run(run_id: str, rows: List[Dict[str, Any]]) -> None:
    """Replace one run's bucket in designs_by_run_id with sorted rows."""
    designs_by_run_id[str(run_id)] = _sort_designs_list(rows)


def _missing_run_ids(run_ids: List[str]) -> List[str]:
    return [rid for rid in run_ids if rid not in designs_by_run_id]


def ensure_designs_loaded_for_run_ids(run_ids: List[str]) -> None:
    """Load design rows for run_ids into designs_by_run_id without loading other runs."""
    wanted = [str(r).strip() for r in run_ids if str(r).strip()]
    if not wanted:
        return
    missing = _missing_run_ids(wanted)
    if not missing:
        return

    from .persistence.factory import get_designs_repository

    repo = get_designs_repository()
    _load_t = Timer(logger, "ensure_designs_loaded_for_run_ids", run_ids=len(missing)).start()
    if repo.is_enabled():
        rows = repo.list_design_dicts_for_run_ids(missing)
        by_run: Dict[str, List[Dict[str, Any]]] = {}
        for d in rows:
            rid = str(d.get("run_id"))
            by_run.setdefault(rid, []).append(d)
        for rid in missing:
            _store_designs_for_run(rid, by_run.get(rid, []))
    else:
        for rid in missing:
            run = run_cache.get(rid)
            if not run:
                designs_by_run_id[rid] = []
                continue
            _store_designs_for_run(rid, parse_designs_from_run(run))
    _load_t.log(missing=len(missing))


def get_designs_for_run_ids(run_ids: List[str]) -> List[Dict[str, Any]]:
    """Return designs for the given runs, loading from DB/disk only for uncached runs."""
    wanted = [str(r).strip() for r in run_ids if str(r).strip()]
    if not wanted:
        return []
    ensure_designs_loaded_for_run_ids(wanted)
    out: List[Dict[str, Any]] = []
    for rid in wanted:
        out.extend(designs_by_run_id.get(rid, []))
    return out


def hydrate_caches_from_repository() -> None:
    """Load run metadata from the DB at startup; design rows load on demand per run_id."""
    global run_cache, designs_cache, designs_by_run_id
    from .persistence.factory import get_designs_repository

    repo = get_designs_repository()
    run_cache.clear()
    designs_cache.clear()
    designs_by_run_id.clear()
    if not repo.is_enabled():
        logger.info("hydrate_caches_from_repository: persistence disabled, caches empty")
        return
    from .path_policy import run_paths_within_bases
    from .settings import settings

    skipped = 0
    for row in repo.list_run_records():
        rj = row["run_json"]
        run_dict = json.loads(rj) if isinstance(rj, str) else rj
        rid = run_dict.get("run_id") or row["run_id"]
        run_dict["run_id"] = rid
        if row.get("ingested_at"):
            run_dict["ingested_at"] = row["ingested_at"]
        # Older releases stored client-supplied run dicts verbatim, so a stored run may
        # point at files outside the base dirs. The same applies to runs from a base dir
        # that has since been removed. Not serving them is the safe default; the rows
        # stay in the database and reappear if their directory is added back.
        if not run_paths_within_bases(run_dict, settings.run_base_dirs):
            skipped += 1
            logger.warning(
                "Not loading run %s (%s): it references files outside RUN_BASE_DIRS",
                rid,
                run_dict.get("path"),
            )
            continue
        run_cache[rid] = run_dict
    if skipped:
        logger.warning(
            "%s stored run(s) skipped because they reference files outside RUN_BASE_DIRS",
            skipped,
        )
    # Designs are loaded on demand via get_designs_for_run_ids (not refresh_designs_cache here).
    logger.info(
        "Hydrated run metadata from database: %s runs (designs loaded on demand)",
        len(run_cache),
    )


def patch_design_in_cache(
    run_id: str,
    design_id: str,
    source_path: Optional[str],
    updates: Dict[str, Any],
) -> bool:
    """Update one design in memory after a DB patch (index first, then flat cache)."""
    sp = (source_path or "").strip()
    rid = str(run_id)
    bucket = designs_by_run_id.get(rid)
    if bucket is not None:
        for d in bucket:
            if str(d.get("design_id")) != str(design_id):
                continue
            dsp = str(d.get("source_path") or "").strip()
            if dsp != sp:
                continue
            for k, v in updates.items():
                if v is None and k in ("tag", "good", "binder_chain", "short_name"):
                    d.pop(k, None)
                else:
                    d[k] = v
            return True
    for d in designs_cache:
        if str(d.get("run_id")) != rid:
            continue
        if str(d.get("design_id")) != str(design_id):
            continue
        dsp = str(d.get("source_path") or "").strip()
        if dsp != sp:
            continue
        for k, v in updates.items():
            if v is None and k in ("tag", "good", "binder_chain", "short_name"):
                d.pop(k, None)
            else:
                d[k] = v
        return True
    return False


def refresh_designs_cache() -> None:
    """Reload all designs for runs in run_cache; repopulates designs_by_run_id and designs_cache."""
    global designs_cache, designs_by_run_id
    try:
        _refresh_t = Timer(logger, "refresh_designs_cache").start()
        designs_cache.clear()
        designs_by_run_id.clear()
        from .filtering.chain_roles import clear_chain_role_cache

        clear_chain_role_cache()
        _parse_t = Timer(logger, "refresh_designs_cache.parse").start()
        from .persistence.factory import get_designs_repository

        repo = get_designs_repository()
        rows: List[Dict[str, Any]] = []
        if repo.is_enabled():
            allowed = set(run_cache.keys())
            rows = [
                d
                for d in repo.list_all_design_dicts()
                if str(d.get("run_id")) in allowed
            ]
        else:
            for run in run_cache.values():
                rows.extend(parse_designs_from_run(run))
        _parse_t.log()

        by_run: Dict[str, List[Dict[str, Any]]] = {}
        for design in rows:
            rid = str(design.get("run_id"))
            by_run.setdefault(rid, []).append(design)
        # Sort per run (not one global list) so run-scoped serving stays correct.
        for rid, group in by_run.items():
            _store_designs_for_run(rid, group)
        _rebuild_flat_cache_from_index()

        logger.info(
            "Refreshed designs cache: %s designs from %s runs",
            len(designs_cache),
            len(run_cache),
        )
        _refresh_t.log(runs=len(run_cache), designs=len(designs_cache))
    except Exception as e:
        logger.error("Error refreshing designs cache: %s", e)
        designs_cache.clear()
        designs_by_run_id.clear()
