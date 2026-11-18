"""Download bundles: spec resolution, zip contents, digests, and the two sources agreeing."""

from __future__ import annotations

import hashlib
import json
import zipfile
from io import BytesIO
from pathlib import Path
from typing import Any, Dict, List

import pytest

import backend.cache as cache_mod
from backend.bundles.models import (
    BundleDesignsRequest,
    BundleProvenance,
    PrepareSequencesBundleRequest,
    PrepareSequencesPayload,
)
from backend.bundles.spec import BundleCaps, BundleCapsError, BundleSpec, StructureRef, check_caps
from backend.bundles.sources import resolve_structures, spec_from_live_request
from backend.bundles.writer import write_bundle
from backend.session_state import SessionState
from backend.util.design_list import designs_to_tsv

FIXTURE_PDB = Path(__file__).resolve().parent / "fixtures" / "two_chain_minimal.pdb"


def _design(run_id: str, i: int, **extra: Any) -> Dict[str, Any]:
    row: Dict[str, Any] = {
        "run_id": run_id,
        "design_id": f"d{i}",
        "method": "bindcraft",
        "source_path": "",
        "pdb_file": FIXTURE_PDB.name,
        "Average_i_pTM": 0.5 + i * 0.05,
        "Sequence": "ACDEFGHIKL"[: 4 + (i % 6)],
    }
    row.update(extra)
    return row


def _seed_run(run_id: str = "run-bundle-1", n: int = 5) -> List[Dict[str, Any]]:
    cache_mod.run_cache.clear()
    cache_mod.designs_cache.clear()
    cache_mod.designs_by_run_id.clear()
    cache_mod.run_cache[run_id] = {
        "run_id": run_id,
        "method": "bindcraft",
        "path": "/fake",
        "pdb_files": [str(FIXTURE_PDB)],
        "metadata": {"name": "demo run"},
    }
    rows = [_design(run_id, i) for i in range(n)]
    cache_mod.designs_by_run_id[run_id] = rows
    cache_mod.designs_cache.extend(rows)
    return rows


def _keys(run_id: str, n: int) -> List[Dict[str, str]]:
    return [{"run_id": run_id, "design_id": f"d{i}"} for i in range(n)]


def _read_zip(payload: bytes) -> zipfile.ZipFile:
    return zipfile.ZipFile(BytesIO(payload))


def _root(zf: zipfile.ZipFile) -> str:
    """The single top-level folder. A member at the archive root is a zip-bomb."""
    names = zf.namelist()
    assert names, "empty zip"
    assert all("/" in name and not name.startswith("/") for name in names), names
    roots = {name.split("/", 1)[0] for name in names}
    assert len(roots) == 1, roots
    return next(iter(roots))


def _relnames(zf: zipfile.ZipFile) -> set:
    root = _root(zf)
    return {name[len(root) + 1 :] for name in zf.namelist()}


def _read(zf: zipfile.ZipFile, relative: str) -> bytes:
    return zf.read(f"{_root(zf)}/{relative}")


def _build(spec: BundleSpec) -> bytes:
    built = write_bundle(spec)
    try:
        return built.fileobj.read()
    finally:
        built.close()


class TestSpecResolution:
    def test_duplicate_keys_are_deduped_in_order(self, sqlite_designs_repo) -> None:
        _seed_run(n=3)
        request = BundleDesignsRequest(
            keys=[
                {"run_id": "run-bundle-1", "design_id": "d2"},
                {"run_id": "run-bundle-1", "design_id": "d0"},
                {"run_id": "run-bundle-1", "design_id": "d2"},
            ],
            run_ids=["run-bundle-1"],
        )
        spec = spec_from_live_request(request)
        assert [r["design_id"] for r in spec.rows] == ["d2", "d0"]

    def test_missing_design_is_reported_not_raised(self, sqlite_designs_repo) -> None:
        _seed_run(n=2)
        spec = spec_from_live_request(
            BundleDesignsRequest(
                keys=[
                    {"run_id": "run-bundle-1", "design_id": "d0"},
                    {"run_id": "run-bundle-1", "design_id": "nope"},
                ],
                run_ids=["run-bundle-1"],
            )
        )
        assert len(spec.rows) == 1
        assert any("no longer in the design cache" in w for w in spec.warnings)

    def test_missing_structure_file_warns_and_counts(self, sqlite_designs_repo) -> None:
        _seed_run(n=1)
        cache_mod.designs_by_run_id["run-bundle-1"][0]["pdb_file"] = "absent.pdb"
        spec = spec_from_live_request(
            BundleDesignsRequest(keys=_keys("run-bundle-1", 1), run_ids=["run-bundle-1"])
        )
        assert spec.structures == []
        assert spec.structures_requested == 1
        assert spec.structures_missing == 1
        assert any("was not found on disk" in w for w in spec.warnings)
        assert spec.coverage().structures_missing == 1

    def test_same_basename_in_two_runs_gets_distinct_arcnames(self) -> None:
        cache_mod.run_cache.clear()
        for run_id in ("run-a", "run-b"):
            cache_mod.run_cache[run_id] = {
                "run_id": run_id,
                "method": "bindcraft",
                "pdb_files": [str(FIXTURE_PDB)],
                "metadata": {"name": run_id},
            }
        rows = [
            {"run_id": "run-a", "design_id": "d0", "pdb_file": FIXTURE_PDB.name},
            {"run_id": "run-b", "design_id": "d0", "pdb_file": FIXTURE_PDB.name},
        ]
        refs, requested, warnings = resolve_structures(rows)
        assert requested == 2
        assert warnings == []
        assert len({r.arcname for r in refs}) == 2, refs


class TestCaps:
    def _spec_with(self, count: int, size: int) -> BundleSpec:
        return BundleSpec(
            kind="designs",
            bundle_id="b",
            created_at="2026-01-01T00:00:00Z",
            label="l",
            provenance=BundleProvenance(source="live_selection"),
            rows=[{"design_id": "d"}],
            structures=[
                StructureRef(f"structures/{i}.pdb", Path("/x"), size, "r", "d")
                for i in range(count)
            ],
            structures_requested=count,
        )

    def test_file_count_cap(self) -> None:
        caps = BundleCaps(max_structure_files=2, max_structure_bytes=0, max_total_bytes=0)
        with pytest.raises(BundleCapsError) as excinfo:
            check_caps(self._spec_with(5, 10), caps)
        assert excinfo.value.estimate.exceeds_cap
        assert "structure files exceeds" in str(excinfo.value)

    def test_byte_cap(self) -> None:
        caps = BundleCaps(max_structure_files=0, max_structure_bytes=100, max_total_bytes=0)
        with pytest.raises(BundleCapsError):
            check_caps(self._spec_with(5, 1000), caps)

    def test_under_cap_passes(self) -> None:
        caps = BundleCaps(
            max_structure_files=10, max_structure_bytes=10**9, max_total_bytes=10**9
        )
        assert check_caps(self._spec_with(2, 10), caps).exceeds_cap is False


class TestWriter:
    def _spec(self, sqlite_designs_repo) -> BundleSpec:
        _seed_run(n=3)
        return spec_from_live_request(
            BundleDesignsRequest(
                keys=_keys("run-bundle-1", 3),
                run_ids=["run-bundle-1"],
                session=SessionState(run_ids=["run-bundle-1"], visible_columns=["design_id"]),
            )
        )

    def test_member_list(self, sqlite_designs_repo) -> None:
        spec = self._spec(sqlite_designs_repo)
        with _read_zip(_build(spec)) as zf:
            assert _root(zf) == spec.label
            names = _relnames(zf)
        assert {
            "manifest.json",
            "README.txt",
            "designs.tsv",
            "binders.fasta",
            "binderdash_session.json",
            "schemas/manifest.schema.json",
            "schemas/binderdash_session.schema.json",
        } <= names
        assert "designs.csv" not in names, "the bundle carries TSV only"
        assert any(n.startswith("structures/") for n in names)

    def test_designs_tsv_matches_shared_serialiser(self, sqlite_designs_repo) -> None:
        spec = self._spec(sqlite_designs_repo)
        with _read_zip(_build(spec)) as zf:
            assert _read(zf, "designs.tsv").decode() == designs_to_tsv(spec.rows)

    def test_every_sha256_matches_the_archived_bytes(self, sqlite_designs_repo) -> None:
        spec = self._spec(sqlite_designs_repo)
        with _read_zip(_build(spec)) as zf:
            root = _root(zf)
            manifest = json.loads(_read(zf, "manifest.json"))
            assert manifest["files"], "manifest lists no files"
            for entry in manifest["files"]:
                assert entry["path"].startswith(f"{root}/"), entry["path"]
                raw = zf.read(entry["path"])
                assert hashlib.sha256(raw).hexdigest() == entry["sha256"], entry["path"]
                assert len(raw) == entry["size_bytes"], entry["path"]
            # A structure file specifically: proves the single-pass hashing of streamed
            # file members, not just of the small in-memory ones.
            assert any(e["path"].startswith(f"{root}/structures/") for e in manifest["files"])

    def test_manifest_does_not_list_itself(self, sqlite_designs_repo) -> None:
        with _read_zip(_build(self._spec(sqlite_designs_repo))) as zf:
            manifest = json.loads(_read(zf, "manifest.json"))
        assert all(Path(e["path"]).name != "manifest.json" for e in manifest["files"])

    def test_build_info_present(self, sqlite_designs_repo) -> None:
        with _read_zip(_build(self._spec(sqlite_designs_repo))) as zf:
            manifest = json.loads(_read(zf, "manifest.json"))
        assert manifest["build"]["app_version"]
        assert manifest["build"]["build_source"] in {"env", "build_file", "git", "unknown"}

    def test_rolled_to_disk_bundle_still_opens(self, sqlite_designs_repo, monkeypatch) -> None:
        import backend.bundles.writer as writer_mod

        monkeypatch.setattr(writer_mod, "SPOOL_THRESHOLD_BYTES", 512)
        with _read_zip(_build(self._spec(sqlite_designs_repo))) as zf:
            assert zf.testzip() is None
            assert "manifest.json" in _relnames(zf)

    def test_session_state_round_trips(self, sqlite_designs_repo) -> None:
        with _read_zip(_build(self._spec(sqlite_designs_repo))) as zf:
            payload = json.loads(_read(zf, "binderdash_session.json"))
        restored = SessionState.model_validate(payload)
        assert restored.run_ids == ["run-bundle-1"]
        assert restored.captured is True


class TestPrepareSequencesBundle:
    def _spec(self) -> BundleSpec:
        _seed_run(n=2)
        from backend.bundles.sources import spec_from_prepare_request

        return spec_from_prepare_request(
            PrepareSequencesBundleRequest(
                keys=_keys("run-bundle-1", 2),
                run_ids=["run-bundle-1"],
                prepared=PrepareSequencesPayload(
                    order_name="order1",
                    codon_table_id="e_coli",
                    rows=[
                        {
                            "design_id": "d0",
                            "short_name": "AAA",
                            "prepared_aa": "MHHHHHHACDEF",
                            "prepared_dna": "ATGCATCATCAT",
                            "segments_aa": [{"css": "junk"}],
                        },
                        {"design_id": "d1", "short_name": "BBB", "prepared_aa": "MACDEF"},
                    ],
                ),
            )
        )

    def test_construct_members_present(self, sqlite_designs_repo) -> None:
        spec = self._spec()
        with _read_zip(_build(spec)) as zf:
            assert _root(zf) == spec.label
            names = _relnames(zf)
        assert {
            "constructs.tsv",
            "constructs_aa.fasta",
            "constructs_dna.fasta",
            "constructs_twist_aa.csv",
            "constructs_twist_dna.csv",
            "prepare_sequences.json",
            "schemas/prepare_sequences.schema.json",
        } <= names
        assert "constructs_twist.csv" not in names

    def test_designs_bundle_has_no_construct_members(self, sqlite_designs_repo) -> None:
        _seed_run(n=2)
        spec = spec_from_live_request(
            BundleDesignsRequest(keys=_keys("run-bundle-1", 2), run_ids=["run-bundle-1"])
        )
        with _read_zip(_build(spec)) as zf:
            names = _relnames(zf)
        assert "constructs.tsv" not in names
        assert "prepare_sequences.json" not in names

    def test_presentational_fields_are_stripped(self, sqlite_designs_repo) -> None:
        with _read_zip(_build(self._spec())) as zf:
            payload = json.loads(_read(zf, "prepare_sequences.json"))
        assert payload["rows"][0]["prepared_aa"] == "MHHHHHHACDEF"
        assert "segments_aa" not in payload["rows"][0]

    def test_dna_fasta_only_holds_optimised_rows(self, sqlite_designs_repo) -> None:
        with _read_zip(_build(self._spec())) as zf:
            dna = _read(zf, "constructs_dna.fasta").decode()
            aa = _read(zf, "constructs_aa.fasta").decode()
        assert dna.count(">") == 1
        assert aa.count(">") == 2


class TestVendorCsv:
    def test_rows_without_the_ordered_sequence_are_skipped_not_blanked(
        self, sqlite_designs_repo
    ) -> None:
        """A vendor order file with an empty sequence cell would be accepted and then
        fail downstream; a visibly short file with a manifest warning will not."""
        _seed_run(n=2)
        from backend.bundles.sources import spec_from_prepare_request

        spec = spec_from_prepare_request(
            PrepareSequencesBundleRequest(
                keys=_keys("run-bundle-1", 2),
                run_ids=["run-bundle-1"],
                prepared=PrepareSequencesPayload(
                    rows=[
                        {
                            "design_id": "d0",
                            "short_name": "AA",
                            "prepared_aa": "MACD",
                            "prepared_dna": "ATGGCC",
                        },
                        {"design_id": "d1", "short_name": "BB", "prepared_aa": "MACD"},
                    ]
                ),
            )
        )
        with _read_zip(_build(spec)) as zf:
            assert _root(zf) == spec.label
            names = _relnames(zf)
            aa_lines = _read(zf, "constructs_twist_aa.csv").decode().strip().splitlines()
            dna_lines = _read(zf, "constructs_twist_dna.csv").decode().strip().splitlines()
            manifest = json.loads(_read(zf, "manifest.json"))

        assert "constructs_twist.csv" not in names
        assert len(aa_lines) == 3, aa_lines  # header + both amino-acid rows
        assert aa_lines[1].startswith("AA,MACD,")
        assert aa_lines[2].startswith("BB,MACD,")
        assert len(dna_lines) == 2, dna_lines  # header + the one row that has DNA
        assert dna_lines[1].startswith("AA,ATGGCC,")
        assert any("constructs_twist_dna.csv" in w for w in manifest["warnings"])
