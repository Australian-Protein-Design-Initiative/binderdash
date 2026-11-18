"""Cached target-contact export: coverage, and whose apo SASA wins."""

from __future__ import annotations

import zipfile
from io import BytesIO
from pathlib import Path
from typing import Any, Dict, List

import pytest

import backend.cache as cache_mod
from backend.bundles import contacts as contacts_mod
from backend.bundles.models import BundleDesignsRequest
from backend.bundles.sources import spec_from_live_request
from backend.bundles.writer import write_bundle
from backend.filtering.schemas import TargetResidueDto
from backend.filtering.target_contacts import ResidueContact
from backend.filtering.target_contacts_service import ContactData, RunContext

FIXTURE_PDB = Path(__file__).resolve().parent / "fixtures" / "two_chain_minimal.pdb"
RUN_ID = "run-contacts"

APO_SASA = 100.0
BOUND_SASA = 30.0
PER_DESIGN_APO = 80.0


def _seed_designs(n: int = 2) -> List[Dict[str, Any]]:
    cache_mod.run_cache.clear()
    cache_mod.designs_cache.clear()
    cache_mod.designs_by_run_id.clear()
    cache_mod.run_cache[RUN_ID] = {
        "run_id": RUN_ID,
        "method": "bindcraft",
        "pdb_files": [str(FIXTURE_PDB)],
        "metadata": {"name": "contacts run"},
    }
    rows = [
        {
            "run_id": RUN_ID,
            "design_id": f"d{i}",
            "source_path": "",
            "pdb_file": FIXTURE_PDB.name,
            "Sequence": "ACDEF",
        }
        for i in range(n)
    ]
    cache_mod.designs_by_run_id[RUN_ID] = rows
    cache_mod.designs_cache.extend(rows)
    return rows


def _context(target_moves: bool) -> RunContext:
    return RunContext(
        run_id=RUN_ID,
        run_name="contacts run",
        method="bindcraft",
        binder_chain_ids=["B"],
        target_chain_ids=["A"],
        target_key="tk",
        residues=[
            TargetResidueDto(
                label="A166", chain="A", resseq=166, icode=" ", resname="LEU",
                aa1="L", sasa_apo=APO_SASA,
            )
        ],
        target_moves=target_moves,
    )


def _install_fake_contacts(monkeypatch, *, target_moves: bool, covered: int) -> None:
    """Only ``covered`` of the seeded designs have a cached record."""
    records = {}
    for i in range(covered):
        records[f"{RUN_ID}\x1fd{i}\x1f"] = {
            "A166": ResidueContact(
                d_ca=8.1,
                d_cb=6.4,
                d_heavy=3.2,
                sasa_bound=BOUND_SASA,
                sasa_apo=PER_DESIGN_APO if target_moves else None,
            )
        }
    data = ContactData(records=records, contexts={RUN_ID: _context(target_moves)})
    monkeypatch.setattr(contacts_mod, "load_contact_data", lambda run_ids: data)


def _rows(monkeypatch, *, target_moves: bool, covered: int = 2, total: int = 2):
    designs = _seed_designs(total)
    _install_fake_contacts(monkeypatch, target_moves=target_moves, covered=covered)
    return contacts_mod.build_contact_export([RUN_ID], designs)


def test_fixed_target_uses_the_run_reference_apo(monkeypatch) -> None:
    export = _rows(monkeypatch, target_moves=False)
    row = export.rows[0]
    assert row["sasa_apo"] == APO_SASA
    assert row["delta_sasa"] == pytest.approx(APO_SASA - BOUND_SASA)


def test_moving_target_prefers_the_per_design_apo(monkeypatch) -> None:
    """For a run whose target moves, the shared reference map is wrong for that design;
    the record carries its own apo value and it has to win."""
    export = _rows(monkeypatch, target_moves=True)
    row = export.rows[0]
    assert row["sasa_apo"] == PER_DESIGN_APO
    assert row["delta_sasa"] == pytest.approx(PER_DESIGN_APO - BOUND_SASA)


def test_coverage_counts_uncached_designs(monkeypatch) -> None:
    export = _rows(monkeypatch, target_moves=False, covered=1, total=3)
    assert export.designs_with_contacts == 1
    assert export.designs_without_contacts == 2
    assert {r["design_id"] for r in export.rows} == {"d0"}


def test_reference_records_params_and_cutoff(monkeypatch) -> None:
    export = _rows(monkeypatch, target_moves=False)
    assert export.reference.params_key
    assert export.reference.record_cutoff_angstrom == 12.0
    assert export.reference.runs[0].residues[0].label == "A166"


def test_no_cached_records_means_no_contacts_member(monkeypatch, sqlite_designs_repo) -> None:
    """A download must never trigger a SASA computation, so an uncomputed run simply
    omits the file rather than emitting a header-only one."""
    _seed_designs(2)
    monkeypatch.setattr(
        contacts_mod, "load_contact_data", lambda run_ids: ContactData(records={}, contexts={})
    )
    spec = spec_from_live_request(
        BundleDesignsRequest(
            keys=[{"run_id": RUN_ID, "design_id": "d0"}], run_ids=[RUN_ID]
        )
    )
    built = write_bundle(spec)
    try:
        payload = built.fileobj.read()
    finally:
        built.close()
    with zipfile.ZipFile(BytesIO(payload)) as zf:
        names = {name.split("/", 1)[-1] for name in zf.namelist()}
        assert {name.split("/", 1)[0] for name in zf.namelist()} == {"binderdash_designs"}
    assert "target_contacts.tsv" not in names
    assert "target_contacts_reference.json" not in names


def test_contacts_member_written_when_cached(monkeypatch, sqlite_designs_repo) -> None:
    _seed_designs(2)
    _install_fake_contacts(monkeypatch, target_moves=False, covered=2)
    spec = spec_from_live_request(
        BundleDesignsRequest(
            keys=[
                {"run_id": RUN_ID, "design_id": "d0"},
                {"run_id": RUN_ID, "design_id": "d1"},
            ],
            run_ids=[RUN_ID],
        )
    )
    built = write_bundle(spec)
    try:
        payload = built.fileobj.read()
    finally:
        built.close()
    with zipfile.ZipFile(BytesIO(payload)) as zf:
        tsv = zf.read("binderdash_designs/target_contacts.tsv").decode().splitlines()
        assert "binderdash_designs/target_contacts_reference.json" in zf.namelist()
    assert tsv[0].split("\t")[:4] == ["run_id", "design_id", "source_path", "residue_label"]
    assert len(tsv) == 3
