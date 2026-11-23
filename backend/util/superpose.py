"""Fetch reference structures and TM-align them onto a design structure (server-side)."""

from __future__ import annotations

import copy
import gzip
import json
import logging
import os
import re
import tempfile
from collections import OrderedDict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import requests
from Bio.PDB import PDBParser, Structure

from .structure_io import parse_mmcif
from Bio.PDB.mmcifio import MMCIFIO
from Bio.PDB.Polypeptide import is_aa
from tmtools import tm_align
from tmtools.io import get_residue_data

PDB_ID_PATTERN = re.compile(r"^[0-9][A-Za-z0-9]{3}$")
_PDBTM_ENTRY_RE = re.compile(
    r"^https?://pdbtm\.unitmp\.org/entry/([0-9][A-Za-z0-9]{3})/?$",
    re.IGNORECASE,
)
_PDBTM_JSON_RE = re.compile(
    r"^https?://pdbtm\.unitmp\.org/api/v1/entry/([0-9][A-Za-z0-9]{3})\.json/?$",
    re.IGNORECASE,
)
_MAX_FETCH_BYTES = 50 * 1024 * 1024
_REQUEST_TIMEOUT = 120
_LOGGER = logging.getLogger(__name__)

_REFERENCE_FETCH_CACHE: "OrderedDict[str, Tuple[bytes, str, Optional[dict[str, Any]]]]" = (
    OrderedDict()
)
_REFERENCE_FETCH_CACHE_MAX = 128


def _reference_fetch_cache_get(
    key: str,
) -> Optional[Tuple[bytes, str, Optional[dict[str, Any]]]]:
    if key not in _REFERENCE_FETCH_CACHE:
        return None
    val = _REFERENCE_FETCH_CACHE.pop(key)
    _REFERENCE_FETCH_CACHE[key] = val
    return val


def _reference_fetch_cache_put(
    key: str, payload: Tuple[bytes, str, Optional[dict[str, Any]]]
) -> None:
    if key in _REFERENCE_FETCH_CACHE:
        del _REFERENCE_FETCH_CACHE[key]
    _REFERENCE_FETCH_CACHE[key] = payload
    while len(_REFERENCE_FETCH_CACHE) > _REFERENCE_FETCH_CACHE_MAX:
        _REFERENCE_FETCH_CACHE.popitem(last=False)


def _reference_fetch_cache_key(source_stripped: str) -> Optional[str]:
    """Stable key for HTTP/PDB fetches; None if source is not a cacheable shape."""
    if PDB_ID_PATTERN.match(source_stripped):
        return f"pdb_id:{source_stripped.upper()}"
    if source_stripped.lower().startswith(("http://", "https://")):
        pdbtm_id = parse_pdbtm_pdb_id_from_url(source_stripped)
        if pdbtm_id:
            return f"pdbtm:{pdbtm_id}"
        return f"url:{source_stripped}"
    return None


def parse_pdbtm_pdb_id_from_url(url: str) -> Optional[str]:
    """Return upper-case PDB ID if ``url`` is a PDBTM entry or JSON API URL."""
    u = url.strip().split("?", 1)[0].split("#", 1)[0]
    m = _PDBTM_ENTRY_RE.match(u) or _PDBTM_JSON_RE.match(u)
    return m.group(1).upper() if m else None


def _pdbtm_matrix_to_Rt(membrane: dict[str, Any]) -> Tuple[np.ndarray, np.ndarray]:
    tm = membrane["transformation_matrix"]
    rx, ry, rz = tm["rowx"], tm["rowy"], tm["rowz"]
    r = np.array(
        [
            [float(rx["x"]), float(rx["y"]), float(rx["z"])],
            [float(ry["x"]), float(ry["y"]), float(ry["z"])],
            [float(rz["x"]), float(rz["y"]), float(rz["z"])],
        ],
        dtype=np.float64,
    )
    tvec = np.array([float(rx["t"]), float(ry["t"]), float(rz["t"])], dtype=np.float64)
    return r, tvec


def _extract_pdbtm_membrane(entry_json: dict[str, Any]) -> dict[str, Any]:
    ann = entry_json.get("additional_entry_annotations") or {}
    m = ann.get("membrane")
    if not isinstance(m, dict):
        raise ValueError("PDBTM entry has no membrane annotation")
    if "transformation_matrix" not in m or "radius" not in m:
        raise ValueError("PDBTM membrane data incomplete (need transformation_matrix, radius)")
    return m


def compute_membrane_in_design_space(
    pdbtm_membrane: dict[str, Any],
    u_tm: np.ndarray,
    t_tm: np.ndarray,
) -> dict[str, Any]:
    """Map PDBTM membrane geometry from deposited coordinates into design space after TM-align."""
    r, tv = _pdbtm_matrix_to_Rt(pdbtm_membrane)
    r_inv = np.linalg.inv(r)

    n_raw = pdbtm_membrane.get("normal") or {}
    nx = float(n_raw.get("x", 0.0))
    ny = float(n_raw.get("y", 0.0))
    nz = float(n_raw.get("z", 0.0))
    hz = float(np.sqrt(nx * nx + ny * ny + nz * nz))
    if hz < 1e-6:
        raise ValueError("PDBTM membrane normal magnitude is zero")

    dir_mem = np.array([nx, ny, nz], dtype=np.float64) / hz
    plane1_mem = dir_mem * hz
    plane2_mem = -dir_mem * hz
    centroid_mem = np.zeros(3, dtype=np.float64)

    def mem_to_pdb(p_mem: np.ndarray) -> np.ndarray:
        return r_inv @ (p_mem - tv)

    plane1_pdb = mem_to_pdb(plane1_mem)
    plane2_pdb = mem_to_pdb(plane2_mem)
    centroid_pdb = mem_to_pdb(centroid_mem)
    n_pdb = r_inv @ dir_mem
    n_norm = np.linalg.norm(n_pdb)
    if n_norm < 1e-9:
        raise ValueError("Invalid PDBTM membrane normal after transform")
    n_pdb_u = n_pdb / n_norm

    u = np.asarray(u_tm, dtype=np.float64)
    t = np.asarray(t_tm, dtype=np.float64).reshape(3)

    def pdb_to_design(p: np.ndarray) -> np.ndarray:
        return u @ p + t

    plane1_design = pdb_to_design(plane1_pdb)
    plane2_design = pdb_to_design(plane2_pdb)
    centroid_design = pdb_to_design(centroid_pdb)
    n_design = u @ n_pdb_u
    n_dn = np.linalg.norm(n_design)
    if n_dn < 1e-9:
        raise ValueError("Invalid membrane normal in design space")
    n_design = n_design / n_dn

    radius = float(pdbtm_membrane["radius"])
    return {
        "plane1": [float(plane1_design[i]) for i in range(3)],
        "plane2": [float(plane2_design[i]) for i in range(3)],
        "normal": [float(n_design[i]) for i in range(3)],
        "centroid": [float(centroid_design[i]) for i in range(3)],
        "radius": radius,
    }


def _load_structure_from_path(path: Path) -> Structure.Structure:
    lower = path.name.lower()
    if lower.endswith(".cif.gz"):
        with gzip.open(str(path), "rb") as gz_f:
            data = gz_f.read()
        with tempfile.NamedTemporaryFile(suffix=".cif", delete=False) as tmp:
            tmp.write(data)
            tmp_path = tmp.name
        try:
            return parse_mmcif(tmp_path, "s")
        finally:
            os.unlink(tmp_path)
    if lower.endswith(".pdb.gz"):
        with gzip.open(str(path), "rb") as gz_f:
            data = gz_f.read()
        with tempfile.NamedTemporaryFile(suffix=".pdb", delete=False) as tmp:
            tmp.write(data)
            tmp_path = tmp.name
        try:
            parser = PDBParser(QUIET=True)
            return parser.get_structure("s", tmp_path)
        finally:
            os.unlink(tmp_path)
    if lower.endswith(".cif"):
        return parse_mmcif(str(path), "s")
    parser = PDBParser(QUIET=True)
    return parser.get_structure("s", str(path))


def _load_structure_from_bytes(data: bytes, fmt: str) -> Structure.Structure:
    fmt_l = fmt.lower()
    if fmt_l == "mmcif":
        suffix = ".cif"
        parser_f = lambda p: parse_mmcif(p, "s")
    else:
        suffix = ".pdb"
        parser_f = lambda p: PDBParser(QUIET=True).get_structure("s", p)
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(data)
        tmp_path = tmp.name
    try:
        return parser_f(tmp_path)
    finally:
        os.unlink(tmp_path)


def _normalize_reference_chain_ids(chain_ids: List[str]) -> List[str]:
    seen: set[str] = set()
    out: List[str] = []
    for cid in chain_ids:
        s = cid.strip()
        if not s or s in seen:
            continue
        seen.add(s)
        out.append(s)
    return out


def parse_reference_chain_list(raw: Optional[str]) -> Optional[List[str]]:
    """Split comma/whitespace-separated chain IDs; ``None`` or blank means use default behaviour."""
    if raw is None:
        return None
    s = str(raw).strip()
    if not s:
        return None
    parts = [p for p in re.split(r"[\s,]+", s) if p]
    if not parts:
        return None
    norm = _normalize_reference_chain_ids(parts)
    return norm or None


def _longest_protein_chain(structure: Structure.Structure) -> Any:
    best_chain = None
    best_len = 0
    for model in structure:
        for chain in model:
            n = 0
            for residue in chain:
                if residue.id[0] != " ":
                    continue
                if not is_aa(residue, standard=True):
                    continue
                if "CA" in residue.child_dict:
                    n += 1
            if n > best_len:
                best_len = n
                best_chain = chain
    return best_chain


def _find_chain_in_model(model: Any, chain_id: str) -> Any:
    want = chain_id.strip()
    for ch in model:
        cid = str(ch.id).strip()
        if cid == want:
            return ch
    return None


def _reference_chains_coords_and_seq(
    ref_structure: Structure.Structure, chain_ids: List[str]
) -> Tuple[np.ndarray, str]:
    model = next(ref_structure.get_models())
    coords_parts: List[np.ndarray] = []
    seq_parts: List[str] = []
    for cid in chain_ids:
        chain = _find_chain_in_model(model, cid)
        if chain is None:
            raise ValueError(f"Reference chain {cid!r} not found")
        c, s = _chain_coords_and_seq(chain)
        if len(s) < 1:
            raise ValueError(f"Reference chain {cid!r} has no usable residues for alignment")
        coords_parts.append(np.asarray(c, dtype=np.float64))
        seq_parts.append(s)
    if not coords_parts:
        raise ValueError("No reference chains specified")
    coords = np.vstack(coords_parts)
    seq = "".join(seq_parts)
    return coords, seq


def _subset_structure_to_chains(structure: Structure.Structure, keep_ids: set[str]) -> None:
    for model in structure:
        for ch in list(model):
            cid = str(ch.id).strip()
            if cid not in keep_ids:
                model.detach_child(ch.id)


def _chain_coords_and_seq(chain: Any) -> Tuple[np.ndarray, str]:
    if chain is None:
        return np.zeros((0, 3), dtype=np.float64), ""
    return get_residue_data(chain, ignore_hetero=True)


def _apply_tm_to_structure(
    structure: Structure.Structure, u: np.ndarray, t: np.ndarray
) -> None:
    r = np.asarray(u, dtype=np.float64)
    tr = np.asarray(t, dtype=np.float64).reshape(3)
    for model in structure:
        for chain in model:
            for residue in chain:
                for atom in residue:
                    c = atom.coord
                    atom.set_coord(r @ c + tr)


def fetch_reference_structure(
    source: str,
) -> Tuple[bytes, str, Optional[dict[str, Any]]]:
    """Return structure bytes, format hint (``pdb`` / ``mmcif``), optional PDBTM membrane dict.

    RCSB / PDBTM / URL downloads are cached in-process (LRU) so repeated references do not
    re-hit the network.
    """
    s = source.strip()
    if not s:
        raise ValueError("Empty reference source")

    cache_key = _reference_fetch_cache_key(s)
    if cache_key is not None:
        hit = _reference_fetch_cache_get(cache_key)
        if hit is not None:
            b, fmt, mem = hit
            return b, fmt, copy.deepcopy(mem) if mem is not None else None

    if PDB_ID_PATTERN.match(s):
        url = f"https://files.rcsb.org/download/{s.upper()}.cif"
        r = requests.get(url, timeout=_REQUEST_TIMEOUT)
        r.raise_for_status()
        if len(r.content) > _MAX_FETCH_BYTES:
            raise ValueError("Downloaded structure exceeds size limit")
        out: Tuple[bytes, str, Optional[dict[str, Any]]] = (r.content, "mmcif", None)
        if cache_key is not None:
            _reference_fetch_cache_put(cache_key, out)
        return out[0], out[1], out[2]

    if s.lower().startswith(("http://", "https://")):
        pdbtm_id = parse_pdbtm_pdb_id_from_url(s)
        if pdbtm_id:
            json_url = f"https://pdbtm.unitmp.org/api/v1/entry/{pdbtm_id.lower()}.json"
            jr = requests.get(json_url, timeout=_REQUEST_TIMEOUT)
            jr.raise_for_status()
            if len(jr.content) > _MAX_FETCH_BYTES:
                raise ValueError("PDBTM JSON exceeds size limit")
            entry = json.loads(jr.content.decode("utf-8"))
            membrane_raw = _extract_pdbtm_membrane(entry)
            cif_url = f"https://files.rcsb.org/download/{pdbtm_id}.cif"
            cr = requests.get(cif_url, timeout=_REQUEST_TIMEOUT)
            cr.raise_for_status()
            if len(cr.content) > _MAX_FETCH_BYTES:
                raise ValueError("Downloaded structure exceeds size limit")
            mem_stored = copy.deepcopy(membrane_raw)
            if cache_key is not None:
                _reference_fetch_cache_put(cache_key, (cr.content, "mmcif", mem_stored))
            return cr.content, "mmcif", copy.deepcopy(mem_stored)

        r = requests.get(s, timeout=_REQUEST_TIMEOUT)
        r.raise_for_status()
        if len(r.content) > _MAX_FETCH_BYTES:
            raise ValueError("Downloaded structure exceeds size limit")
        data = r.content
        lower = s.lower()
        if lower.endswith(".gz"):
            data = gzip.decompress(data)
            lower = lower[:-3]
        if lower.endswith(".cif"):
            out = (data, "mmcif", None)
        else:
            out = (data, "pdb", None)
        if cache_key is not None:
            _reference_fetch_cache_put(cache_key, out)
        return out[0], out[1], out[2]

    raise ValueError(
        "Source must be a 4-character PDB ID, an http(s) URL to a structure file, "
        "or a PDBTM entry / JSON URL (pdbtm.unitmp.org)"
    )


def superpose_reference_onto_design(
    ref_bytes: bytes,
    ref_format: str,
    design_path: Path,
    pdbtm_membrane: Optional[dict[str, Any]] = None,
    reference_chain_ids: Optional[List[str]] = None,
) -> Tuple[bytes, dict[str, Any]]:
    """TM-align reference onto design; return mmCIF bytes and metrics.

    If ``reference_chain_ids`` is set, TM-align uses only those reference chains (concatenated
    in list order) and the returned structure contains only those chains. Otherwise the longest
    reference protein chain is used for alignment and the full reference structure is returned.
    """
    design_structure = _load_structure_from_path(design_path)
    ref_structure = _load_structure_from_bytes(ref_bytes, ref_format)

    d_chain = _longest_protein_chain(design_structure)
    if d_chain is None:
        raise ValueError("Could not find protein chains with Cα atoms for alignment on design")

    coords_d, seq_d = _chain_coords_and_seq(d_chain)
    if reference_chain_ids:
        ordered = _normalize_reference_chain_ids(reference_chain_ids)
        if not ordered:
            raise ValueError("No valid reference chain IDs after parsing")
        keep_set = set(ordered)
        coords_r, seq_r = _reference_chains_coords_and_seq(ref_structure, ordered)
    else:
        r_chain = _longest_protein_chain(ref_structure)
        if r_chain is None:
            raise ValueError("Could not find protein chains with Cα atoms for alignment on reference")
        coords_r, seq_r = _chain_coords_and_seq(r_chain)

    if len(seq_d) < 3 or len(seq_r) < 3:
        raise ValueError("Insufficient residues for TM-align")

    coords_d = np.asarray(coords_d, dtype=np.float64)
    coords_r = np.asarray(coords_r, dtype=np.float64)

    result = tm_align(coords_r, coords_d, seq_r, seq_d)
    u = np.array(result.u, dtype=np.float64)
    t = np.array(result.t, dtype=np.float64)

    ref_copy = ref_structure.copy()
    ref_copy.id = "ref_aligned"
    if reference_chain_ids:
        _subset_structure_to_chains(ref_copy, keep_set)
    _apply_tm_to_structure(ref_copy, u, t)

    io = MMCIFIO()
    io.set_structure(ref_copy)
    with tempfile.NamedTemporaryFile(
        suffix=".cif", delete=False, mode="w", encoding="utf-8"
    ) as tmp:
        tmp_path = tmp.name
    try:
        io.save(tmp_path)
        with open(tmp_path, "rb") as f:
            out = f.read()
    finally:
        os.unlink(tmp_path)

    metrics: Dict[str, Any] = {
        "tm_score_norm_design": float(result.tm_norm_chain2),
        "tm_score_norm_reference": float(result.tm_norm_chain1),
        "rmsd": float(result.rmsd),
        "aligned_length": sum(1 for c in result.seqM if c == ":"),
    }
    if pdbtm_membrane is not None:
        try:
            metrics["membrane"] = compute_membrane_in_design_space(
                pdbtm_membrane, u, t
            )
        except (ValueError, KeyError, TypeError) as e:
            _LOGGER.warning("PDBTM membrane transform failed: %s", e)
    return out, metrics


def superpose_reference_path_onto_design(
    ref_path: Path,
    design_path: Path,
    reference_chain_ids: Optional[List[str]] = None,
) -> Tuple[bytes, dict[str, Any]]:
    """Load reference from disk (same formats as design) and TM-align onto design."""
    lower = ref_path.name.lower()
    if lower.endswith(".gz"):
        inner = Path(ref_path.stem).suffix.lower()
        fmt = "mmcif" if inner == ".cif" else "pdb"
        with gzip.open(str(ref_path), "rb") as gz_f:
            data = gz_f.read()
    else:
        fmt = "mmcif" if lower.endswith(".cif") else "pdb"
        data = ref_path.read_bytes()
    return superpose_reference_onto_design(
        data, fmt, design_path, None, reference_chain_ids
    )
