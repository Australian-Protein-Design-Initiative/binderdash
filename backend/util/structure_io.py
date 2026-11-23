"""mmCIF parsing that tolerates the minimal files design tools write.

``Bio.PDB.MMCIFParser`` requires ``_atom_site.occupancy`` and fails with
``KeyError: '_atom_site.occupancy'`` without it. Several structure-prediction tools omit
the column - BindCraft2's ``2_Refolded`` and ``3_Ranked`` mmCIFs, for one - and the
failure surfaces far from the parse: no chain-role resolution, so no Target Contacts; no
target sequence; no tag metrics; no superposition.

Every Biopython mmCIF read in the backend goes through :func:`parse_mmcif` so that one
absent column cannot take those features out. PDB files are unaffected (occupancy is a
fixed-width field there) and keep using ``PDBParser`` directly.
"""

from __future__ import annotations

from typing import IO, Union, cast

from Bio.PDB import Structure
from Bio.PDB.MMCIF2Dict import MMCIF2Dict
from Bio.PDB.MMCIFParser import MMCIFParser

# Full occupancy: these are predicted models, which have no partial occupancy to record.
DEFAULT_OCCUPANCY = "1.000"

_MISSING_OCCUPANCY = "_atom_site.occupancy"


def parse_mmcif(
    source: Union[str, IO[str]], structure_id: str = "structure"
) -> Structure.Structure:
    """Parse an mmCIF into a Biopython structure, supplying occupancy if it is absent.

    ``source`` is a path or an open text handle (a gzip handle, for instance).
    """
    try:
        return cast(
            Structure.Structure,
            MMCIFParser(QUIET=True).get_structure(structure_id, source),
        )
    except KeyError as exc:
        if str(exc).strip("'\"") != _MISSING_OCCUPANCY:
            raise

    seek = getattr(source, "seek", None)
    if seek is not None:
        seek(0)
    mmcif_dict = MMCIF2Dict(source)
    # Cartn_x is present in any file that has coordinates at all, which a file reaching
    # this point does: the parse got as far as looking for occupancy.
    atom_count = len(mmcif_dict["_atom_site.Cartn_x"])
    mmcif_dict[_MISSING_OCCUPANCY] = [DEFAULT_OCCUPANCY] * atom_count

    parser = MMCIFParser(QUIET=True)
    # ponytail: MMCIFParser offers no public way to build from an already-parsed dict,
    # so this drives the two steps its own get_structure() does. Replace with the public
    # equivalent if Biopython grows one; the alternative today is writing the patched
    # dict back out through MMCIFIO and reparsing it, which costs a temp file per read.
    parser._mmcif_dict = mmcif_dict
    parser._build_structure(structure_id)
    return cast(Structure.Structure, parser._structure_builder.get_structure())
