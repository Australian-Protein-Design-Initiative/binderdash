import gzip
import logging
import re
import warnings
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import numpy as np
from Bio.PDB.PDBParser import PDBParser
from Bio.PDB import Residue, Structure
from Bio.PDB.PDBExceptions import PDBConstructionWarning
from Bio.PDB.Polypeptide import PPBuilder, is_aa

from .util.sasa import annotate_residue_sasa
from .util.structure_io import parse_mmcif
from .util.sasa_constants import TIEN_2023_THEORETICAL

logger = logging.getLogger(__name__)

warnings.filterwarnings("ignore", category=PDBConstructionWarning)
warnings.filterwarnings("ignore", message="WARNING: Unrecognized atom type")


def parse_distant_from_string(
    distant_from_str: Optional[str],
) -> Optional[List[Tuple[str, int]]]:
    """Parses a string like 'A118,B20' into [('A', 118), ('B', 20)]."""
    if not distant_from_str:
        return None

    parsed_residues: List[Tuple[str, int]] = []
    parts = distant_from_str.split(",")
    for part in parts:
        part = part.strip()
        if not part:
            continue
        try:
            chain_id = part[0]
            res_num_str = part[1:]
            if not chain_id.isalpha() or not res_num_str.isdigit():
                raise ValueError(
                    f"Residue identifier '{part}' must be a letter followed by numbers."
                )
            res_num = int(res_num_str)
            parsed_residues.append((chain_id.upper(), res_num))
        except (IndexError, ValueError) as e:
            logger.warning(
                "Invalid format for distant-from residue '%s': %s. Skipping this entry.",
                part,
                e,
            )
            continue

    return parsed_residues if parsed_residues else None


def parse_target_chains_string(target_chains_str: Optional[str]) -> Optional[List[str]]:
    """Split comma- or whitespace-separated chain IDs (e.g. 'A B' or 'A, HL')."""
    if not target_chains_str or not str(target_chains_str).strip():
        return None
    parts = re.split(r"[\s,]+", str(target_chains_str).strip())
    out = [p.strip().upper() for p in parts if p.strip()]
    return out if out else None


def expand_target_chains_to_residue_spec(
    structure: Structure.Structure,
    chain_ids: List[str],
) -> List[Tuple[str, int]]:
    """All standard amino-acid residues on the given chains as (chain_id, resseq) pairs."""
    model = structure[0]
    pdb_id = structure.id
    specs: List[Tuple[str, int]] = []
    for raw in chain_ids:
        cid = raw.strip()
        if not cid:
            continue
        if cid not in model:
            logger.warning("Target chain '%s' not found in structure %s", cid, pdb_id)
            continue
        chain = model[cid]
        for res in chain:
            if not is_aa(res, standard=True):
                continue
            hetflag, resseq, _icode = res.get_id()
            if hetflag != " ":
                continue
            try:
                specs.append((cid, int(resseq)))
            except (TypeError, ValueError):
                continue
    return specs


def resolve_target_residue_spec(
    structure: Structure.Structure,
    distant_from: Optional[str],
    target_chains: Optional[str],
) -> Optional[List[Tuple[str, int]]]:
    """Merge explicit distant-from residues with all residues on target chain(s)."""
    seen: Set[Tuple[str, int]] = set()
    ordered: List[Tuple[str, int]] = []

    def add_pair(pair: Tuple[str, int]) -> None:
        if pair not in seen:
            seen.add(pair)
            ordered.append(pair)

    explicit = parse_distant_from_string(distant_from)
    if explicit:
        for p in explicit:
            add_pair(p)

    chain_ids = parse_target_chains_string(target_chains)
    if chain_ids:
        for p in expand_target_chains_to_residue_spec(structure, chain_ids):
            add_pair(p)

    return ordered if ordered else None


def _get_sasa_and_percent_sasa(
    residue: Residue.Residue,
    pdb_id: str,
    chain_id_str: str,
    terminal_type: str,
) -> Tuple[Optional[float], Optional[float], Optional[str]]:
    sasa: Optional[float] = None
    percent_sasa: Optional[float] = None
    aa_type: Optional[str] = residue.get_resname().upper()

    if not hasattr(residue, "sasa"):
        logger.error(
            "SASA attribute not found on %s-terminal residue for chain '%s' in PDB ID %s.",
            terminal_type,
            chain_id_str,
            pdb_id,
        )
        return None, None, aa_type

    sasa = round(float(getattr(residue, "sasa")), 2)

    try:
        if aa_type:
            standard_sasa = TIEN_2023_THEORETICAL.get(aa_type)
            if standard_sasa and standard_sasa > 0:
                percent_sasa = round((sasa / standard_sasa) * 100, 2)
            else:
                logger.debug(
                    "Standard SASA for %s-terminal residue %s not found or is zero in %s, chain %s.",
                    terminal_type,
                    aa_type,
                    pdb_id,
                    chain_id_str,
                )
        else:
            logger.warning(
                "%s-terminal residue type was None for %s, chain %s. Cannot calculate percent SASA.",
                terminal_type,
                pdb_id,
                chain_id_str,
            )
    except Exception as e:
        logger.warning(
            "Error calculating %s-terminal percent SASA for %s in %s, chain %s: %s",
            terminal_type,
            aa_type,
            pdb_id,
            chain_id_str,
            e,
        )

    return sasa, percent_sasa, aa_type


def _get_ca_coord(
    residue: Residue.Residue,
    terminal_type: str,
    chain_id_str: str,
    pdb_id: str,
) -> Optional[np.ndarray]:
    if "CA" in residue:
        return residue["CA"].get_coord()
    logger.warning(
        "CA atom not found in %s-terminal residue of chain %s in %s.",
        terminal_type,
        chain_id_str,
        pdb_id,
    )
    return None


def _calculate_distance_to_target_center(
    terminal_ca_coord: Optional[np.ndarray],
    target_ca_coords: List[np.ndarray],
    terminal_type: str,
    pdb_id: str,
) -> Optional[float]:
    if terminal_ca_coord is None or not target_ca_coords:
        return None
    try:
        geometric_center = np.mean(target_ca_coords, axis=0)
        distance = round(float(np.linalg.norm(terminal_ca_coord - geometric_center)), 2)
        return distance
    except Exception as e:
        logger.warning(
            "Error calculating %s-terminal distance to target center in %s: %s",
            terminal_type,
            pdb_id,
            e,
        )
        return None


def _check_terminal_target_contacts(
    terminal_residue: Residue.Residue,
    all_target_residues_for_contacts: List[Residue.Residue],
    terminal_type: str,
    pdb_id: str,
    contact_distance_threshold: float = 6.0,
) -> bool:
    if not all_target_residues_for_contacts:
        logger.info(
            "No target residues found for %s-terminal contact calculation in %s.",
            terminal_type,
            pdb_id,
        )
        return False

    for term_atom in terminal_residue:
        for target_res in all_target_residues_for_contacts:
            for target_atom in target_res:
                try:
                    distance = np.linalg.norm(
                        term_atom.get_coord() - target_atom.get_coord()
                    )
                    if distance < contact_distance_threshold:
                        return True
                except Exception as e:
                    logger.debug(
                        "Could not calculate distance between %s and %s in %s: %s",
                        term_atom,
                        target_atom,
                        pdb_id,
                        e,
                    )
                    continue
    return False


def compute_terminii_stats(
    structure: Structure.Structure,
    chain_id: str,
    target_residues_spec: Optional[List[Tuple[str, int]]] = None,
) -> Tuple[
    Optional[float],
    Optional[float],
    Optional[float],
    Optional[float],
    Optional[str],
    Optional[str],
    Optional[float],
    Optional[float],
    Optional[float],
    Optional[bool],
    Optional[bool],
    Optional[str],
]:
    pdb_id = structure.id

    n_sasa: Optional[float] = None
    c_sasa: Optional[float] = None
    n_percent_sasa: Optional[float] = None
    c_percent_sasa: Optional[float] = None
    n_aa_type: Optional[str] = None
    c_aa_type: Optional[str] = None
    n_c_dist: Optional[float] = None
    n_dist_target: Optional[float] = None
    c_dist_target: Optional[float] = None
    n_target_contacts: Optional[bool] = None
    c_target_contacts: Optional[bool] = None
    sequence: Optional[str] = None

    try:
        model = structure[0]
        if chain_id not in model:
            logger.warning("Chain '%s' not found in PDB ID %s.", chain_id, pdb_id)
            return None, None, None, None, None, None, None, None, None, None, None, None

        chain = model[chain_id]

        peptides = []
        try:
            ppb = PPBuilder()
            peptides = list(ppb.build_peptides(chain))
        except Exception as e:
            logger.warning("PPBuilder failed for chain '%s' in %s: %s", chain_id, pdb_id, e)

        if not peptides:
            logger.warning(
                "No polypeptides found in chain '%s' of PDB ID %s.", chain_id, pdb_id
            )
            return None, None, None, None, None, None, None, None, None, None, None, None

        sequence = "".join([str(p.get_sequence()) for p in peptides])
        if not sequence:
            sequence = None

        aa_residues: List[Residue.Residue] = [res for p in peptides for res in p]

        if not aa_residues:
            logger.warning(
                "No standard amino acid residues found in chain '%s' of PDB ID %s.",
                chain_id,
                pdb_id,
            )
            return None, None, None, None, None, None, None, None, None, None, None, sequence

        n_terminal_residue = aa_residues[0]
        c_terminal_residue = aa_residues[-1]

        n_sasa, n_percent_sasa, n_aa_type = _get_sasa_and_percent_sasa(
            n_terminal_residue, pdb_id, chain_id, "N"
        )
        c_sasa, c_percent_sasa, c_aa_type = _get_sasa_and_percent_sasa(
            c_terminal_residue, pdb_id, chain_id, "C"
        )

        ca_n_coord = _get_ca_coord(n_terminal_residue, "N", chain_id, pdb_id)
        ca_c_coord = _get_ca_coord(c_terminal_residue, "C", chain_id, pdb_id)

        if ca_n_coord is not None and ca_c_coord is not None:
            try:
                n_c_dist = round(float(np.linalg.norm(ca_n_coord - ca_c_coord)), 2)
            except Exception as e:
                logger.warning(
                    "Error calculating N-C distance for chain %s in %s: %s",
                    chain_id,
                    pdb_id,
                    e,
                )

        if target_residues_spec:
            target_ca_coords_list: List[np.ndarray] = []
            all_target_residues_for_contacts_list: List[Residue.Residue] = []

            for target_chain_id_spec, target_res_num_spec in target_residues_spec:
                try:
                    if target_chain_id_spec not in model:
                        logger.warning(
                            "Target chain '%s' not found in %s. Skipping target %s%s.",
                            target_chain_id_spec,
                            pdb_id,
                            target_chain_id_spec,
                            target_res_num_spec,
                        )
                        continue
                    target_chain_obj = model[target_chain_id_spec]
                    res_id_tuple = (" ", target_res_num_spec, " ")
                    if res_id_tuple not in target_chain_obj:
                        logger.warning(
                            "Target residue %s%s not found in %s. Skipping.",
                            target_chain_id_spec,
                            target_res_num_spec,
                            pdb_id,
                        )
                        continue

                    target_residue_obj = target_chain_obj[res_id_tuple]

                    target_ca = _get_ca_coord(
                        target_residue_obj,
                        f"target {target_chain_id_spec}{target_res_num_spec}",
                        pdb_id,
                        chain_id,
                    )
                    if target_ca is not None:
                        target_ca_coords_list.append(target_ca)

                    all_target_residues_for_contacts_list.append(target_residue_obj)
                except KeyError:
                    logger.warning(
                        "KeyError accessing target residue %s%s in %s. Skipping.",
                        target_chain_id_spec,
                        target_res_num_spec,
                        pdb_id,
                    )
                except Exception as e:
                    logger.warning(
                        "Error processing target residue %s%s in %s: %s. Skipping.",
                        target_chain_id_spec,
                        target_res_num_spec,
                        pdb_id,
                        e,
                    )

            if target_ca_coords_list:
                n_dist_target = _calculate_distance_to_target_center(
                    ca_n_coord, target_ca_coords_list, "N", pdb_id
                )
                c_dist_target = _calculate_distance_to_target_center(
                    ca_c_coord, target_ca_coords_list, "C", pdb_id
                )
            elif target_residues_spec:
                logger.info(
                    "No valid target CA atoms collected from %s for distance calculation in %s.",
                    target_residues_spec,
                    pdb_id,
                )

            if all_target_residues_for_contacts_list:
                n_target_contacts = _check_terminal_target_contacts(
                    n_terminal_residue,
                    all_target_residues_for_contacts_list,
                    "N",
                    pdb_id,
                )
                c_target_contacts = _check_terminal_target_contacts(
                    c_terminal_residue,
                    all_target_residues_for_contacts_list,
                    "C",
                    pdb_id,
                )
            elif target_residues_spec:
                logger.info(
                    "No target residues collected from %s for contact calculation in %s.",
                    target_residues_spec,
                    pdb_id,
                )

        return (
            n_sasa,
            c_sasa,
            n_percent_sasa,
            c_percent_sasa,
            n_aa_type,
            c_aa_type,
            n_c_dist,
            n_dist_target,
            c_dist_target,
            n_target_contacts,
            c_target_contacts,
            sequence,
        )

    except KeyError as e:
        logger.warning("Chain '%s' caused KeyError in PDB ID %s: %s", chain_id, pdb_id, e)
        return None, None, None, None, None, None, None, None, None, None, None, None
    except IndexError:
        logger.warning(
            "Chain '%s' caused IndexError (e.g., no residues) in PDB ID %s.",
            chain_id,
            pdb_id,
        )
        return None, None, None, None, None, None, None, None, None, None, None, None
    except Exception as e:
        logger.error(
            "Unexpected error processing chain '%s' in PDB ID %s: %s",
            chain_id,
            pdb_id,
            e,
            exc_info=True,
        )
        return None, None, None, None, None, None, None, None, None, None, None, None


def determine_his_tag_placement(
    n_sasa: Optional[float],
    c_sasa: Optional[float],
    n_percent_sasa: Optional[float],
    c_percent_sasa: Optional[float],
    n_dist_target: Optional[float],
    c_dist_target: Optional[float],
    n_target_contacts: Optional[bool],
    c_target_contacts: Optional[bool],
    sasa_threshold_percent: float,
    more_distant_threshold_angstrom: float,
) -> Optional[str]:
    n_eligible = True
    if n_target_contacts is True:
        n_eligible = False
    if n_eligible and (
        n_percent_sasa is None or n_percent_sasa < sasa_threshold_percent
    ):
        n_eligible = False

    c_eligible = True
    if c_target_contacts is True:
        c_eligible = False
    if c_eligible and (
        c_percent_sasa is None or c_percent_sasa < sasa_threshold_percent
    ):
        c_eligible = False

    if n_eligible and c_eligible:
        current_n_sasa: float = n_sasa  # type: ignore[assignment]
        current_c_sasa: float = c_sasa  # type: ignore[assignment]

        can_compare_distances = n_dist_target is not None and c_dist_target is not None

        if can_compare_distances:
            current_n_dist_target: float = n_dist_target  # type: ignore[assignment]
            current_c_dist_target: float = c_dist_target  # type: ignore[assignment]
            dist_diff = abs(current_n_dist_target - current_c_dist_target)

            if dist_diff > more_distant_threshold_angstrom:
                return "N" if current_n_dist_target > current_c_dist_target else "C"
            if current_n_sasa > current_c_sasa:
                return "N"
            if current_c_sasa > current_n_sasa:
                return "C"
            return None
        if current_n_sasa > current_c_sasa:
            return "N"
        if current_c_sasa > current_n_sasa:
            return "C"
        return None

    if n_eligible:
        return "N"
    if c_eligible:
        return "C"
    return None


def _structure_id_for_path(path: Path) -> str:
    name = path.name
    if name.lower().endswith(".gz"):
        name = Path(name[:-3]).stem
    else:
        name = Path(name).stem
    return name.replace(" ", "_")


def load_structure(path: Path) -> Structure.Structure:
    sid = _structure_id_for_path(path)
    lower = str(path).lower()
    if lower.endswith(".cif.gz"):
        with gzip.open(path, "rt") as fh:
            return parse_mmcif(fh, sid)
    if lower.endswith(".cif"):
        return parse_mmcif(str(path), sid)
    parser = PDBParser(QUIET=True)
    if lower.endswith(".pdb.gz") or lower.endswith(".ent.gz"):
        with gzip.open(path, "rt") as fh:
            return parser.get_structure(sid, fh)
    return parser.get_structure(sid, str(path))


def _percent_buried(percent_sasa: Optional[float]) -> Optional[float]:
    if percent_sasa is None:
        return None
    return round(100.0 - float(percent_sasa), 2)


def compute_tag_metrics_for_structure_file(
    path: Path,
    *,
    binder_chain: str,
    distant_from: Optional[str] = None,
    target_chains: Optional[str] = None,
    sasa_probe_radius: float = 1.4,
    sasa_n_points: int = 100,
    sasa_threshold: float = 30.0,
    more_distant_threshold: float = 5.0,
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """
    Returns (metrics dict, error). Dict matches prototype TSV columns plus predicted_tag and
    n_percent_buried / c_percent_buried (100 − terminal % SASA vs standard).
    """
    if not path.is_file():
        return None, "Structure file not found"

    try:
        structure = load_structure(path)
    except Exception as e:
        logger.warning("Failed to parse structure %s: %s", path, e)
        return None, f"Failed to parse structure: {e}"

    if not hasattr(structure, "xtra") or structure.xtra is None:
        structure.xtra = {}
    structure.xtra["pdb_path"] = str(path)

    target_residues = resolve_target_residue_spec(structure, distant_from, target_chains)
    if (distant_from or target_chains) and not target_residues:
        logger.warning(
            "distant_from %r and target_chains %r produced no valid target residues; "
            "continuing without target distances",
            distant_from,
            target_chains,
        )

    try:
        # Sets `.sasa` per residue, as Bio.PDB.SASA used to; see util.sasa for why the
        # kernel and the radii convention changed.
        annotate_residue_sasa(
            structure, probe_radius=sasa_probe_radius, n_points=sasa_n_points
        )
    except Exception as e:
        logger.warning("SASA computation failed for %s: %s", path, e)
        return None, f"SASA computation failed: {e}"

    (
        n_sasa,
        c_sasa,
        n_percent_sasa,
        c_percent_sasa,
        n_aa_type,
        c_aa_type,
        n_c_dist,
        n_dist_target,
        c_dist_target,
        n_target_contacts,
        c_target_contacts,
        sequence,
    ) = compute_terminii_stats(structure, binder_chain, target_residues)

    if n_sasa is None or c_sasa is None:
        return None, "Could not compute terminal SASA for binder chain"

    tag = determine_his_tag_placement(
        n_sasa,
        c_sasa,
        n_percent_sasa,
        c_percent_sasa,
        n_dist_target,
        c_dist_target,
        n_target_contacts,
        c_target_contacts,
        sasa_threshold,
        more_distant_threshold,
    )

    metrics: Dict[str, Any] = {
        "n_sasa": round(float(n_sasa), 2),
        "c_sasa": round(float(c_sasa), 2),
        "n_percent_sasa": n_percent_sasa,
        "c_percent_sasa": c_percent_sasa,
        "n_percent_buried": _percent_buried(n_percent_sasa),
        "c_percent_buried": _percent_buried(c_percent_sasa),
        "n_aa_type": n_aa_type,
        "c_aa_type": c_aa_type,
        "n_c_dist": n_c_dist,
        "n_dist_target": n_dist_target,
        "c_dist_target": c_dist_target,
        "n_target_contacts": n_target_contacts,
        "c_target_contacts": c_target_contacts,
        "sequence": sequence,
        "predicted_tag": tag,
    }
    return metrics, None


def compute_tag_for_structure_file(
    path: Path,
    *,
    binder_chain: str,
    distant_from: Optional[str] = None,
    target_chains: Optional[str] = None,
    sasa_probe_radius: float = 1.4,
    sasa_n_points: int = 100,
    sasa_threshold: float = 30.0,
    more_distant_threshold: float = 5.0,
) -> Tuple[Optional[str], Optional[str]]:
    """
    Returns (tag, error). tag is 'N', 'C', or None when ambiguous or ineligible.
    error is set when the structure cannot be processed.
    """
    metrics, err = compute_tag_metrics_for_structure_file(
        path,
        binder_chain=binder_chain,
        distant_from=distant_from,
        target_chains=target_chains,
        sasa_probe_radius=sasa_probe_radius,
        sasa_n_points=sasa_n_points,
        sasa_threshold=sasa_threshold,
        more_distant_threshold=more_distant_threshold,
    )
    if err or not metrics:
        return None, err or "Unknown error"
    return metrics.get("predicted_tag"), None
