import csv
import io
import json
import logging
import os
import re
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

import numpy as np
import pandas as pd

from .util.pdb_to_fasta import get_chain_sequences
from .util.profiling import Timer
from .config.method_paths import (
    is_disallowed_project_id_segment,
    is_disallowed_run_name_segment,
    should_prune_walk_bindcraft_batches,
)
from .config.run_signatures import run_folder_signatures

# Import will be done inside the function to avoid linting issues


logger = logging.getLogger(__name__)


def get_target_sequence(
    pdb_file: str, method: str, binder_sequence: Optional[str] = None
) -> Optional[str]:
    """Extract the target sequence from a PDB file based on the method.

    Args:
        pdb_file: Path to the PDB file
        method: The method type ("bindcraft", "rfd", or other)
        binder_sequence: The binder sequence (used for methods other than bindcraft/rfd)

    Returns:
        The target sequence as a string, or None if not found
    """

    if not pdb_file or not os.path.exists(pdb_file):
        return None

    try:
        # Get sequences for all chains
        chain_sequences = get_chain_sequences(pdb_file)

        if not chain_sequences:
            logger.warning(f"No sequences found in PDB file: {pdb_file}")
            return None

        if method == "bindcraft":
            # Target sequence is from chain A
            return chain_sequences.get("A")

        elif method == "rfd":
            # Target sequence is from chain B
            return chain_sequences.get("B")

        else:
            # For other methods, find the target by excluding the binder sequence
            if not binder_sequence:
                logger.warning(f"No binder sequence provided for method {method}")
                return None

            # Remove any non-amino acid characters and convert to uppercase for comparison
            clean_binder = "".join(c.upper() for c in binder_sequence if c.isalpha())

            # Find the chain that doesn't match the binder sequence
            for chain_id, sequence in chain_sequences.items():
                clean_chain_seq = "".join(c.upper() for c in sequence if c.isalpha())
                if clean_chain_seq != clean_binder:
                    return sequence

            logger.warning(
                f"Could not find target sequence in {pdb_file} - all chains match binder"
            )
            return None

    except Exception as e:
        logger.error(f"Error extracting target sequence from {pdb_file}: {str(e)}")
        return None


def extract_backbone_id(design_id: str, method: str) -> str:
    """Extract backbone_id from design_id by removing MPNN variant suffixes.

    For bindcraft: removes _mpnn{n} suffix
    For rfd: removes _mpnn{n} suffix and _af2pred suffix
    For bindcraft2: removes the _candidate{n} (refolded.csv) or _seq{n} (ranked.csv)
    suffix, so the ProteinMPNN candidates
    of one gradient trajectory group together (they share BindCraft2's recipe hash)

    Args:
        design_id: The design identifier
        method: The method type ("bindcraft" or "rfd")

    Returns:
        The backbone_id with MPNN variant suffixes removed
    """
    if not design_id:
        return design_id

    # bindcraft_design_111_l93_s308700_mpnn10 -> bindcraft_design_111_l93_s308700
    # design_ppi_1Ty4GSo_6_dldesign_0_cycle1_mpnn1_af2pred -> design_ppi_1Ty4GSo_6_dldesign_0_cycle1
    # cxcr2_denovo_l117_2637c435ac2716c4_candidate3 -> cxcr2_denovo_l117_2637c435ac2716c4

    # Remove _mpnn{n} pattern, optionally followed by _af2pred
    # This handles both bindcraft (_mpnn{n}) and RFD (_mpnn{n}_af2pred) patterns
    backbone_id = re.sub(
        r"_(?:mpnn\d+(?:_af2pred)?|candidate\d+|seq\d+)$", "", design_id
    )

    return backbone_id


def _read_csv_text(file_path: Path) -> Optional[str]:
    """Load CSV text, normalising rare CR-only BindCraft merges for ``csv.reader``."""
    try:
        data = file_path.read_bytes()
    except OSError:
        return None
    if not data.strip():
        return ""
    # Some merged BindCraft CSVs use classic Mac ``\\r`` separators only.
    if b"\n" not in data and b"\r" in data:
        data = data.replace(b"\r", b"\n")
    return data.decode("utf-8", errors="replace")


def count_csv_data_rows(file_path: Path) -> Optional[int]:
    """Count non-empty CSV data records (skips header). Handles CR/LF and quoted newlines."""
    if not file_path.is_file():
        return None
    text = _read_csv_text(file_path)
    if text is None:
        return None
    if not text.strip():
        return 0
    try:
        reader = csv.reader(io.StringIO(text))
        next(reader, None)  # header
        return sum(1 for row in reader if any(cell.strip() for cell in row))
    except csv.Error:
        return None


def _unique_csv_column_values(file_path: Path, column: str) -> Optional[Set[str]]:
    """Return distinct non-empty values of ``column``, or None if unreadable / missing."""
    if not file_path.is_file():
        return None
    try:
        df = pd.read_csv(file_path)
    except Exception:
        text = _read_csv_text(file_path)
        if text is None or not text.strip():
            return None
        try:
            reader = csv.DictReader(io.StringIO(text))
            if reader.fieldnames is None or column not in reader.fieldnames:
                return None
            values = {
                str(row[column]).strip()
                for row in reader
                if (row.get(column) or "").strip()
            }
            return values if values else None
        except csv.Error:
            return None
    if column not in df.columns:
        return None
    values = {str(v).strip() for v in df[column].dropna() if str(v).strip()}
    return values if values else None


def _count_input_pdb_paths(run_path: Path, input_pdb: str) -> Optional[int]:
    """Count target PDBs from an nf-binder-design ``input_pdb`` (file, dir, or glob)."""
    pattern = input_pdb.strip()
    if not pattern:
        return None
    bases = (run_path, run_path.parent)
    has_glob = any(ch in pattern for ch in "*?[")
    for base in bases:
        if has_glob:
            matches = [
                p
                for p in base.glob(pattern)
                if p.is_file() and p.suffix.lower() == ".pdb"
            ]
            if matches:
                return len(matches)
            continue
        path = Path(pattern) if Path(pattern).is_absolute() else base / pattern
        if path.is_file() and path.suffix.lower() == ".pdb":
            return 1
        if path.is_dir():
            n = len([p for p in path.glob("*.pdb") if p.is_file()])
            if n:
                return n
    return None


_BINDCRAFT_TRAJECTORY_STATS = "results/bindcraft/trajectory_stats.csv"
_BINDCRAFT_DESIGN_STATS = "results/bindcraft/final_design_stats.csv"


def _bindcraft_target_count_from_trajectory_stats(run_path: Path) -> Optional[int]:
    """Distinct ``Target`` values in ``trajectory_stats.csv``."""
    values = _unique_csv_column_values(run_path / _BINDCRAFT_TRAJECTORY_STATS, "Target")
    if values:
        return len(values)
    return None


def _bindcraft_target_count_from_csv(run_path: Path) -> Optional[int]:
    """Distinct ``Target`` values from BindCraft results tables (for trajectory totals)."""
    n = _bindcraft_target_count_from_trajectory_stats(run_path)
    if n is not None:
        return n
    values = _unique_csv_column_values(run_path / _BINDCRAFT_DESIGN_STATS, "Target")
    if values:
        return len(values)
    return None


def _bindcraft_target_count_from_input(run_path: Path, params_data: Any) -> Optional[int]:
    """Count target PDBs from an nf-binder-design ``input_pdb`` param (file, dir, or glob)."""
    input_pdb = _params_value_from_run_params_json(params_data, "input_pdb")
    if isinstance(input_pdb, str):
        n = _count_input_pdb_paths(run_path, input_pdb)
        if n is not None and n >= 1:
            return n
    return None


def _bindcraft_target_count(run_path: Path, params_data: Any) -> int:
    """Number of input PDBs / targets for per-target trajectory totals (at least 1)."""
    n = _bindcraft_target_count_from_input(run_path, params_data)
    if n is not None:
        return n
    n = _bindcraft_target_count_from_csv(run_path)
    if n is not None:
        return n
    return 1


def _params_value_from_run_params_json(
    data: Any, key_dotted: str
) -> Optional[Any]:
    """Look up a value under the top-level ``params`` object (supports dotted keys)."""
    if not isinstance(data, dict) or not key_dotted:
        return None
    params_obj = data.get("params")
    if not isinstance(params_obj, dict):
        return None
    cur: Any = params_obj
    for part in key_dotted.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


def resolve_target_count(run_path: Path, signature: Dict[str, Any]) -> Optional[int]:
    """Number of targets from ``trajectory_stats.csv`` (else input folder before trajectories exist)."""
    if not signature.get("trajectory_count_per_target"):
        return None
    n = _bindcraft_target_count_from_trajectory_stats(run_path)
    if n is not None:
        return n
    stub: Dict[str, Any] = {"path": str(run_path), "signature": signature}
    raw = parse_run_params(stub)
    n = _bindcraft_target_count_from_input(run_path, raw)
    if n is not None:
        return n
    return 1


def resolve_trajectory_count(run_path: Path, signature: Dict[str, Any]) -> Optional[int]:
    """Pre-filter trajectory/design count: params.json key first, else CSV record count.

    For BindCraft (``trajectory_count_per_target``), ``bindcraft_n_traj`` is per input
    PDB, so the params value is multiplied by the number of targets.
    """
    key = signature.get("trajectory_count_params_key")
    if key:
        stub: Dict[str, Any] = {"path": str(run_path), "signature": signature}
        raw = parse_run_params(stub)
        if raw is not None:
            val = _params_value_from_run_params_json(raw, key)
            if val is not None:
                try:
                    per = int(val)
                except (TypeError, ValueError):
                    per = None
                if per is not None:
                    if signature.get("trajectory_count_per_target"):
                        return per * _bindcraft_target_count(run_path, raw)
                    return per
    rel = signature.get("trajectory_count_file")
    if rel:
        n = count_csv_data_rows(run_path / rel)
        if n is not None:
            return n
    return None


def compute_primary_score_stats(
    df: Optional[pd.DataFrame], signature: Dict[str, Any]
) -> Optional[Dict[str, Any]]:
    if df is None or df.empty:
        return None
    primary_cols = signature.get("primary_score_columns", [])
    col: Optional[str] = None
    for c in primary_cols:
        if c in df.columns:
            col = c
            break
    if col is None:
        # The first numeric column is a guess, and a wrong one for a method whose
        # table starts with bookkeeping columns, so a signature can opt out and
        # report no primary score at all rather than a nonsense one.
        if not signature.get("primary_score_fallback", True):
            return None
        numeric_cols = df.select_dtypes(include=["number"]).columns.tolist()
        if not numeric_cols:
            return None
        col = numeric_cols[0]
    series = pd.to_numeric(df[col], errors="coerce").dropna()
    if series.empty:
        return None
    arr = series.to_numpy(dtype=float)
    return {
        "column": col,
        "count": int(len(arr)),
        "min": float(np.min(arr)),
        "max": float(np.max(arr)),
        "mean": float(np.mean(arr)),
        "median": float(np.median(arr)),
        "stddev": float(np.std(arr, ddof=0)),
    }


def guess_project_id(path: Path) -> str:
    run_name = guess_run_name(path)
    current_path = path
    found_run_name = False
    while current_path != current_path.parent:
        name = current_path.name
        if name == run_name:
            found_run_name = True
            current_path = current_path.parent
            continue
        if found_run_name:
            if not is_disallowed_project_id_segment(name):
                return name
        current_path = current_path.parent
    return ""


def guess_run_name(path: Path) -> str:
    current_path = path
    while current_path != current_path.parent:
        name = current_path.name
        if not is_disallowed_run_name_segment(name):
            return name
        current_path = current_path.parent
    return path.name


def _check_required_files(path: Path, required_files: List[str]) -> bool:
    """Check if all required files exist for the given run signature."""
    for file_path_str in required_files:
        file_path = path / file_path_str
        if not file_path.is_file():
            return False
    return True


def _check_required_dirs(path: Path, required_dirs: List[str]) -> bool:
    """Check if all required directories exist for the given run signature."""
    for dir_path_str in required_dirs:
        dir_path = path / dir_path_str
        if not dir_path.is_dir():
            return False
    return True


def _pick_latest_numeric_suffix_match(matches: List[Path]) -> Path:
    """Prefer the file with the largest trailing _{digits} in the stem (e.g. metrics_10 over metrics_2)."""

    def sort_key(p: Path) -> tuple:
        m = re.search(r"_(\d+)$", p.stem)
        if m:
            return (0, int(m.group(1)))
        return (1, p.name)

    return max(matches, key=sort_key)


def _check_required_patterns(path: Path, required_patterns: List[str]) -> bool:
    """Check if any files match the required patterns for the given run signature."""
    for pattern in required_patterns:
        matches = list(path.glob(pattern))
        if matches:
            return True
    return False


def _find_structure_file_for_design(
    run_path: Path,
    search_value: str,
    search_patterns: List[str],
    structure_base_dir: str,
    design_id: Optional[str] = None,
) -> Optional[str]:
    """Find the structure file for a design using the search patterns."""
    resolved_base = structure_base_dir
    if structure_base_dir and ("{design_id}" in structure_base_dir or "{file_name}" in structure_base_dir):
        did = design_id if design_id is not None else search_value
        try:
            resolved_base = structure_base_dir.format(
                design_id=did, file_name=search_value
            )
        except KeyError:
            resolved_base = structure_base_dir

    search_dirs: List[Path] = []
    if "*" in resolved_base:
        for d in run_path.glob(resolved_base):
            if d.is_dir():
                search_dirs.append(d)
    elif resolved_base:
        base_dir = run_path / resolved_base
        if base_dir.is_dir():
            search_dirs.append(base_dir)

    for base_dir in search_dirs:
        for pattern in search_patterns:
            try:
                search_pattern = pattern.format(design_id=search_value, file_name=search_value)
            except KeyError:
                search_pattern = pattern.format(design_id=search_value)
            matches = list(base_dir.glob(search_pattern))
            if matches:
                return str(matches[0])
    return None


def detect_run_type(path: Path) -> Optional[Dict[str, Any]]:
    """Detect the run type using declarative signatures.

    Returns the matching signature with run_name extracted, or None if no match.
    """
    if not path.is_dir():
        return None

    # Sort signatures by priority (lower number = checked first)
    sorted_signatures = sorted(run_folder_signatures, key=lambda x: x["priority"])

    for signature in sorted_signatures:
        # The current directory is the run_name
        run_name = path.name

        # Check required files
        if "required_files" in signature:
            if not _check_required_files(path, signature["required_files"]):
                continue

        # Check required directories
        if "required_dirs" in signature:
            if not _check_required_dirs(path, signature["required_dirs"]):
                continue

        # Check required patterns (alternative to required_files for some cases)
        if "required_patterns" in signature:
            if not _check_required_patterns(path, signature["required_patterns"]):
                continue

        # Special case for regular RFD: check if combined_scores.tsv exists OR .cs files exist
        if signature["method"] == "rfd" and signature["submethod"] == "regular":
            combined_file = path / "combined_scores.tsv"
            cs_files_scores = list((path / "af2_initial_guess" / "scores").glob("*.cs"))
            cs_files_root = list((path / "af2_initial_guess").glob("*.cs"))

            if not (combined_file.is_file() or cs_files_scores or cs_files_root):
                continue

        # Resolve any dynamic patterns to concrete values for this path
        resolved_signature = dict(signature)

        # Resolve results table from pattern, if provided
        results_table_pattern = resolved_signature.get("results_table_pattern")
        if results_table_pattern and not resolved_signature.get("results_table"):
            matches = list(path.glob(results_table_pattern))
            if not matches:
                # No concrete table found for this signature
                continue
            selected = _pick_latest_numeric_suffix_match(matches)
            try:
                rel_table = selected.relative_to(path)
            except ValueError:
                rel_table = selected
            resolved_signature["results_table"] = str(rel_table)

        # Resolve structure pattern to a concrete glob pattern for this run (used for listing files)
        structure_pattern = resolved_signature.get("structure_pattern")
        if structure_pattern and not resolved_signature.get("pdb_pattern"):
            # Keep the relative glob pattern; find_runs_recursive will use it directly
            resolved_signature["pdb_pattern"] = structure_pattern

        # If we get here, this signature matches
        return {**resolved_signature, "run_name": run_name, "detected_path": str(path)}

    return None


def _run_record(current_dir: Path, detected_run: Dict[str, Any]) -> Dict[str, Any]:
    """Build the run dict for a folder that detect_run_type matched."""
    run_id = str(uuid.uuid4())
    guessed_project_id = guess_project_id(current_dir)
    run_name = detected_run["run_name"]

    results_table = detected_run["results_table"]
    pdb_pattern = detected_run["pdb_pattern"]
    extra_pats = detected_run.get("additional_pdb_patterns", [])

    _glob_t = Timer(
        logger,
        "run_glob",
        method=detected_run.get("method"),
        path=str(current_dir),
        primary_pattern=pdb_pattern,
        extra_patterns=len(extra_pats),
    ).start()
    pdb_paths = list(current_dir.glob(pdb_pattern))
    for extra_pat in extra_pats:
        pdb_paths.extend(current_dir.glob(extra_pat))
    pdb_files = sorted({str(p) for p in pdb_paths})
    _glob_t.log(pdb_files=len(pdb_files))

    is_nf_binder_design = detected_run["submethod"] == "nf-binder-design"

    trajectory_count = resolve_trajectory_count(current_dir, detected_run)
    target_count = resolve_target_count(current_dir, detected_run)
    meta: Dict[str, Any] = {
        "name": run_name,
        "original_name": current_dir.name,
        "parent_path": str(current_dir.parent),
        "pdb_count": len(pdb_files),
    }
    if trajectory_count is not None:
        meta["trajectory_count"] = trajectory_count
    if target_count is not None and target_count > 1:
        meta["target_count"] = target_count

    return {
        "run_id": run_id,
        "project_id": guessed_project_id,
        "path": str(current_dir),
        "method": detected_run["method"],
        "submethod": detected_run["submethod"],
        "results_table": results_table,
        "pdb_files": pdb_files,
        "is_nf_binder_design": is_nf_binder_design,
        "signature": detected_run,
        "metadata": meta,
    }


def discover_run_at(run_path: Path) -> Optional[Dict[str, Any]]:
    """The run whose folder is exactly ``run_path``, or None. Does not descend."""
    detected_run = detect_run_type(run_path)
    if not detected_run:
        return None
    return _run_record(run_path, detected_run)


def find_runs_recursive(root_path: Path) -> List[Dict[str, Any]]:
    # Build combined set of directories to skip from all signatures
    skip_dirs_set = set()
    for sig in run_folder_signatures:
        skip_dirs_set.update(sig.get("skip_dirs", []))

    walk_dirs = 0

    runs: List[Dict[str, Any]] = []
    _walk_t = Timer(logger, "find_runs_recursive", root=root_path).start()
    for dirpath, dirnames, filenames in os.walk(root_path, followlinks=True):
        walk_dirs += 1
        current_dir = Path(dirpath)
        if current_dir.name in skip_dirs_set:
            dirnames[:] = []
            continue

        if should_prune_walk_bindcraft_batches(current_dir.parts):
            dirnames[:] = []
            continue

        _det_t = Timer(logger, "detect_run_type", path=str(current_dir)).start()
        detected_run = detect_run_type(current_dir)
        _det_t.log(min_ms=100)

        if detected_run:
            runs.append(_run_record(current_dir, detected_run))
            dirnames[:] = []

    _walk_t.log(walk_dirs=walk_dirs, runs_found=len(runs))
    return runs


def resolve_design_id_column(df: pd.DataFrame, signature: Dict[str, Any]) -> Optional[str]:
    design_id_columns = signature.get("design_id_columns", [])
    for col_name in design_id_columns:
        if col_name in df.columns:
            return col_name
    for col in df.columns:
        if col.lower() in ["design", "description", "name", "id"]:
            return col
    return None


def update_design_good_flag(
    run_metadata: Dict[str, Any],
    design_id: str,
    good: Optional[bool],
    source_path: Optional[str] = None,
) -> None:
    """Persist ``good`` in the configured database (see ``DATABASE``)."""
    from .persistence.factory import get_designs_repository

    repo = get_designs_repository()
    if not repo.is_enabled():
        raise ValueError(
            "DATABASE is not configured or persistence is disabled; set DATABASE in .env"
        )
    rid = str(run_metadata.get("run_id", ""))
    ok = repo.update_design_good(rid, str(design_id), good, source_path=source_path)
    if not ok:
        raise ValueError(
            f"Design {design_id!r} not found for run {rid!r} in the database"
        )


def update_design_tag(
    run_metadata: Dict[str, Any],
    design_id: str,
    tag: Optional[str],
    source_path: Optional[str] = None,
) -> None:
    """Persist ``tag`` (N / C / cleared) in the configured database (see ``DATABASE``)."""
    from .persistence.factory import get_designs_repository

    repo = get_designs_repository()
    if not repo.is_enabled():
        raise ValueError(
            "DATABASE is not configured or persistence is disabled; set DATABASE in .env"
        )
    rid = str(run_metadata.get("run_id", ""))
    ok = repo.update_design_tag(rid, str(design_id), tag, source_path=source_path)
    if not ok:
        raise ValueError(
            f"Design {design_id!r} not found for run {rid!r} in the database"
        )


def update_design_sequence_and_binder_chain(
    run_metadata: Dict[str, Any],
    design_id: str,
    *,
    source_path: Optional[str] = None,
    sequence: Optional[str] = None,
    binder_chain: Optional[str] = None,
) -> None:
    """Persist binder ``Sequence`` (in extra_data) and/or ``binder_chain`` column."""
    from .persistence.factory import get_designs_repository

    repo = get_designs_repository()
    if not repo.is_enabled():
        raise ValueError(
            "DATABASE is not configured or persistence is disabled; set DATABASE in .env"
        )
    rid = str(run_metadata.get("run_id", ""))
    ok = repo.update_design_sequence_and_binder_chain(
        rid,
        str(design_id),
        source_path=source_path,
        sequence=sequence,
        binder_chain=binder_chain,
    )
    if not ok:
        raise ValueError(
            f"Design {design_id!r} not found for run {rid!r} in the database"
        )


# --- RFD4-Proteina inline oracle metrics -------------------------------------------
#
# ponytail: a stopgap. RFD4-Proteina's combined_scores.tsv currently carries identity and
# sequence but no scores; the oracle's confidence metrics sit in a sibling CSV named after
# the refolding oracle. Delete this whole block once the pipeline writes them into
# combined_scores.tsv itself, which is planned upstream.
_RFD4_INLINE_METRICS_FILES: Dict[str, str] = {
    "of3_inline_metrics.csv": "of3",  # OpenFold3
    "af3_inline_metrics.csv": "af3",  # AlphaFold3
}

# Column groups worth merging. The file's other ~40 columns are generation
# hyperparameters, checkpoint names and absolute work-directory paths: constant across
# designs, and of no use in the design table.
_RFD4_INLINE_METRIC_PREFIXES = (
    "oracle_ppi.",
    "refolded_",
    "hotspot_obedience.",
    "amino_acid_composition.",
)
_RFD4_INLINE_METRIC_COLUMNS = (
    "ppi.pass",
    "pre_oracle_pass",
    # Distinguishes "failed this metric" from "this metric was never computed".
    "ppi.all_metrics_present",
)

# Written as 0.0 / 1.0 but boolean in meaning. Stored as real booleans so the Filtering
# tab offers a yes/no choice rather than a 0-1 range slider, and the table reads
# true/false rather than 1.0/0.0.
_RFD4_INLINE_FLAG_COLUMNS = (
    "ppi.pass",
    "pre_oracle_pass",
    "ppi.all_metrics_present",
    "oracle_ppi.has_clash",
)
# Paths rather than metrics, and they point into the pipeline's work directory.
_RFD4_INLINE_METRIC_EXCLUDED = (
    "oracle_ppi.refolded_structure_path",
    "oracle_ppi.confidence_json_path",
)
# The oracle reports these three on 0-100; every other binderdash method reports pTM,
# ipTM and pLDDT on 0-1. Rescaled on merge so the canonical iptm / ptm / binder_plddt
# metrics stay comparable across methods and the frontend needs no per-method span.
_RFD4_INLINE_PERCENT_SUFFIXES = ("plddt", "ptm", "iptm")


def _rfd4_inline_metric_columns(columns: List[str]) -> List[str]:
    return [
        c
        for c in columns
        if c not in _RFD4_INLINE_METRIC_EXCLUDED
        and (
            c.startswith(_RFD4_INLINE_METRIC_PREFIXES)
            or c in _RFD4_INLINE_METRIC_COLUMNS
        )
    ]


def _rfd4_inline_is_percent(column: str) -> bool:
    """True for a 0-100 confidence column: one whose metric name contains plddt, ptm or
    iptm as a whole word (``overall_iptm``, ``plddt_coi``, ``iptm_A_1_B_1``).

    Matching whole tokens keeps the angstrom columns out: ``ipae_coi`` and
    ``min_ipae_coi`` contain no such token, and neither does ``ranking_score``.
    """
    metric_name = column.rsplit(".", 1)[-1]
    return any(
        token in _RFD4_INLINE_PERCENT_SUFFIXES for token in metric_name.split("_")
    )


def _merge_rfd4_inline_metrics(df: pd.DataFrame, run_path: Path) -> pd.DataFrame:
    """Join the oracle's per-design metrics onto RFD4-Proteina's results table.

    ``example_id`` repeats across batches (one set of examples per batch), so it is not a
    key on its own; the oracle table's ``dataset_name`` names the batch's input JSON
    (``<prefix>_b<n>.json``), and ``<prefix>_b<n>_<example_id>`` is the design ``id``.
    """
    if "id" not in df.columns:
        return df

    table_dir = run_path / "results" / "rfd4_proteina"
    for file_name, oracle in _RFD4_INLINE_METRICS_FILES.items():
        metrics_path = table_dir / file_name
        if not metrics_path.is_file():
            continue
        try:
            metrics = pd.read_csv(metrics_path)
        except Exception as e:  # a malformed sidecar must not lose the run
            logger.warning("Could not read %s: %s", metrics_path, e)
            continue
        if not {"dataset_name", "example_id"}.issubset(metrics.columns):
            logger.warning("%s has no dataset_name/example_id to join on", metrics_path)
            continue

        wanted = _rfd4_inline_metric_columns(list(metrics.columns))
        if not wanted:
            continue
        joined = metrics[["dataset_name", "example_id"] + wanted].copy()
        joined["id"] = (
            joined["dataset_name"].astype(str).str.replace(r"\.json$", "", regex=True)
            + "_"
            + joined["example_id"].astype(str)
        )
        joined = joined.drop(columns=["dataset_name", "example_id"])
        # A duplicated key would multiply the design rows on merge.
        joined = joined.drop_duplicates(subset=["id"], keep="first")

        for col in wanted:
            if col in _RFD4_INLINE_FLAG_COLUMNS:
                # Not ``astype(bool)``: that would turn a missing value into True.
                # Object dtype keeps None as None, which stays JSON-serialisable.
                joined[col] = [
                    None if pd.isna(v) else bool(v)
                    for v in pd.to_numeric(joined[col], errors="coerce")
                ]
            elif _rfd4_inline_is_percent(col):
                joined[col] = pd.to_numeric(joined[col], errors="coerce") / 100.0
        # Vega-Lite reads a dot in a field name as nested access, so flatten them.
        joined = joined.rename(columns={c: c.replace(".", "_") for c in wanted})
        # Columns the results table already provides win: this merge goes away once
        # combined_scores.tsv carries them itself.
        overlap = [c for c in joined.columns if c != "id" and c in df.columns]
        if overlap:
            joined = joined.drop(columns=overlap)

        merged = df.merge(joined, on="id", how="left")
        merged["inline_metrics_oracle"] = oracle
        matched = int(merged[joined.columns[0]].notna().sum()) if len(joined.columns) else 0
        logger.info(
            "Merged %s metrics from %s for %d/%d designs",
            oracle, file_name, matched, len(merged),
        )
        return merged
    return df


def load_run_table(run_metadata: Dict[str, Any]) -> Optional[pd.DataFrame]:
    _t = Timer(logger, "load_run_table", path=run_metadata.get("path")).start()
    try:
        merged_paths = run_metadata.get("merged_paths", [run_metadata["path"]])
        results_table = run_metadata.get("results_table")
        if not results_table:
            _t.log()
            return None
        all_dfs: List[pd.DataFrame] = []
        for run_path in merged_paths:
            path = Path(run_path)
            table_path = path / results_table
            if not table_path.exists():
                logger.warning(f"Results table not found: {table_path}")
                continue
            try:
                if table_path.suffix.lower() == ".csv":
                    df = pd.read_csv(table_path)
                elif table_path.suffix.lower() == ".tsv":
                    df = pd.read_csv(table_path, sep="\t")
                else:
                    logger.warning(f"Unsupported table format: {table_path}")
                    continue
                for col in df.columns:
                    if df[col].dtype == object:
                        df[col] = pd.to_numeric(df[col], errors="ignore")
                df = _standardise_dataframe_columns(
                    df, run_metadata.get("method", "")
                )
                if run_metadata.get("method") == "rfd4_proteina":
                    df = _merge_rfd4_inline_metrics(df, path)
                df["source_path"] = str(path)
                all_dfs.append(df)
            except Exception as e:
                logger.error(f"Error loading table from {table_path}: {str(e)}")
                continue
        if not all_dfs:
            logger.warning(
                f"No valid tables found for run: {run_metadata.get('path', 'unknown')}"
            )
            _t.log(table=results_table)
            return None
        if len(all_dfs) == 1:
            out = all_dfs[0]
        else:
            combined_df = pd.concat(all_dfs, ignore_index=True)
            logger.info(
                f"Combined {len(all_dfs)} tables for merged run, total rows: {len(combined_df)}"
            )
            out = combined_df
        _t.log(table=results_table, rows=len(out))
        return out
    except Exception as e:
        logger.error(f"Error loading run table: {str(e)}")
        _t.log()
        return None


def _standardise_dataframe_columns(df: pd.DataFrame, method: str) -> pd.DataFrame:
    if df is None or df.empty:
        return df
    canonical_groups: Dict[str, List[str]] = {
        "Sequence": [
            "Sequence",
            "sequence",
            "binder_sequence",
            # BindCraft2's stage tables name it this.
            "Binder_Sequence",
            "binder_seq",
            "seq",
        ],
        "Length": ["Length", "length", "len", "binder_length"],
        "binder_chain": ["binder_chain", "chain", "binder_chain_id", "Binder_chain"],
    }
    lower_to_original: Dict[str, str] = {col.lower(): col for col in df.columns}
    result_df = df.copy()
    for target, variants in canonical_groups.items():
        source_cols: List[str] = []
        for v in variants:
            original = lower_to_original.get(v.lower())
            if original and original not in source_cols:
                source_cols.append(original)
        if not source_cols:
            continue
        if target in result_df.columns:
            for src in source_cols:
                if src == target:
                    continue
                result_df[target] = result_df[target].fillna(result_df[src])
        else:
            series = None
            for idx, src in enumerate(source_cols):
                if idx == 0:
                    series = result_df[src]
                else:
                    series = series.where(series.notna(), result_df[src])  # type: ignore
            if series is not None:
                result_df[target] = series
        for src in source_cols:
            if src != target and src in result_df.columns:
                result_df = result_df.drop(columns=[src])
    return result_df


def parse_run_params(run_metadata: Dict[str, Any]) -> Optional[Any]:
    """Parse parameter/settings file for a run and return the raw JSON content.

    - Parse the first existing file in signature["params_files"], if provided.

    Returns the parsed JSON (dict/list/primitive) or None if not found or error.
    """
    try:
        run_path_str = run_metadata.get("path", "")
        if not run_path_str:
            return None
        run_path = Path(run_path_str)

        signature: Dict[str, Any] = run_metadata.get("signature", {})
        submethod = signature.get("submethod", run_metadata.get("submethod", ""))

        json_path: Optional[Path] = None

        params_files: List[str] = signature.get("params_files", [])
        for rel in params_files:
            candidate = run_path / rel
            if candidate.is_file():
                json_path = candidate
                break

        if not json_path:
            return None

        logger.info(f"Parsing run params from {json_path}")
        with open(json_path, "r") as f:
            data = json.load(f)
        return data
    except Exception as e:
        logger.error(f"Error parsing run params: {str(e)}")
        return None


def parse_designs_from_run(run_metadata: Dict[str, Any]) -> List[Dict[str, Any]]:
    _t = Timer(
        logger,
        "parse_designs",
        run_id=run_metadata.get("run_id"),
        method=run_metadata.get("method"),
        run_name=run_metadata.get("metadata", {}).get("name", ""),
    ).start()
    try:
        df = load_run_table(run_metadata)
        if df is None or df.empty:
            _t.log()
            return []

        designs: List[Dict[str, Any]] = []
        run_path = run_metadata["path"]
        run_name = run_metadata["metadata"]["name"]
        signature = run_metadata.get("signature", {})

        primary_score_columns = signature.get("primary_score_columns", [])
        sort_ascending = signature.get("sort_ascending", True)
        structure_search_patterns = signature.get(
            "structure_search_patterns", ["{design_id}.pdb"]
        )

        design_id_col = resolve_design_id_column(df, signature)

        primary_score_col = None
        for col_name in primary_score_columns:
            if col_name in df.columns:
                primary_score_col = col_name
                break

        if not primary_score_col:
            numeric_cols = df.select_dtypes(include=["number"]).columns.tolist()
            if numeric_cols:
                primary_score_col = numeric_cols[0]

        if primary_score_col and primary_score_col in df.columns:
            df = df.sort_values(
                primary_score_col, ascending=sort_ascending
            ).reset_index(drop=True)

        structure_base_dir = signature.get("structure_base_dir", "")
        if not structure_base_dir:
            pdb_pattern = signature.get("pdb_pattern", "")
            if "/*.pdb" in pdb_pattern:
                structure_base_dir = pdb_pattern.split("/*.pdb")[0]
            elif "/*.cif" in pdb_pattern:
                structure_base_dir = pdb_pattern.split("/*.cif")[0]

        _params_t = Timer(
            logger,
            "parse_designs.parse_run_params",
            run_id=run_metadata.get("run_id"),
        ).start()
        run_params: Optional[Any] = parse_run_params(run_metadata)
        _params_t.log()

        # Target protein is the same for every design in a run; parsing each mmCIF
        # only to extract it costs ~O(rows) full structure reads (DEBUG timing logs).
        target_sequence_cache: Dict[str, Optional[str]] = {}

        for index, row in df.iterrows():
            design_id = (
                str(row.get(design_id_col, f"design_{index}"))
                if design_id_col
                else f"design_{index}"
            )

            structure_file_column = signature.get("structure_file_column")
            search_value = design_id
            file_name_val = None
            if structure_file_column and structure_file_column in df.columns:
                file_name_val = row.get(structure_file_column)
                if file_name_val is not None and str(file_name_val).strip():
                    search_value = str(file_name_val)

            pdb_file = _find_structure_file_for_design(
                Path(run_path),
                search_value,
                structure_search_patterns,
                structure_base_dir,
                design_id=design_id,
            )
            if (
                pdb_file is None
                and run_metadata.get("method") == "boltzgen"
                and structure_file_column == "file_name"
                and file_name_val is not None
                and str(file_name_val).strip()
            ):
                pdb_file = str(file_name_val)

            backbone_id = extract_backbone_id(design_id, run_metadata["method"])

            binder_sequence = None
            for seq_col in ["Sequence", "sequence", "binder_sequence"]:
                if seq_col in df.columns:
                    try:
                        val = row[seq_col]
                        if val is not None and str(val).strip():
                            binder_sequence = str(val)
                            break
                    except (KeyError, AttributeError):
                        continue

            cache_key = (
                str(row["source_path"])
                if "source_path" in df.columns
                and row.get("source_path") is not None
                and str(row.get("source_path")).strip()
                else str(run_path)
            )
            if cache_key in target_sequence_cache:
                target_sequence = target_sequence_cache[cache_key]
            elif pdb_file:
                target_sequence = get_target_sequence(
                    pdb_file, run_metadata["method"], binder_sequence
                )
                if target_sequence is not None:
                    target_sequence_cache[cache_key] = target_sequence
            else:
                target_sequence = None

            design: Dict[str, Any] = {
                "design_id": design_id,
                "backbone_id": backbone_id,
                "run_id": run_metadata["run_id"],
                "project_id": run_metadata.get("project_id", ""),
                "run_name": run_name,
                "method": run_metadata["method"],
                "run_path": run_path,
                "pdb_file": pdb_file,
                "target_sequence": target_sequence,
                **{
                    col: row[col]
                    for col in df.columns
                    if col != design_id_col
                    and not bool(
                        (
                            pd.isna(row[col])
                            if hasattr(pd, "isna")
                            else (row[col] is None)
                        )
                    )
                },
            }
            if run_params is not None:
                design["params"] = run_params
            designs.append(design)

        _t.log(rows=len(designs))
        return designs
    except Exception as e:
        logger.error(
            f"Error parsing designs from run {run_metadata['run_id']}: {str(e)}"
        )
        _t.log()
        return []
