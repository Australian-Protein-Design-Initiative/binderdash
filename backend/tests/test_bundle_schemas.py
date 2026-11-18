"""The JSON Schemas shipped in a bundle must describe the JSON shipped beside them.

Schemas are generated from the Pydantic models at request time, so they cannot drift
from the models. What they *can* do is change without anyone bumping a version, which is
what the golden snapshots below catch: a failure here means you changed a model, and the
fix is to decide whether it was additive (regenerate the golden, bump the minor) or
breaking (new golden file, bump the major, keep the old one).
"""

from __future__ import annotations

import json
import zipfile
from io import BytesIO
from pathlib import Path

import jsonschema
import pytest

import backend.cache as cache_mod
from backend.bundles.json_schemas import BUNDLE_SCHEMAS, schema_document
from backend.bundles.models import BundleDesignsRequest, BundleManifest
from backend.bundles.sources import spec_from_live_request
from backend.bundles.writer import write_bundle
from backend.session_state import SessionState

GOLDEN_DIR = Path(__file__).resolve().parent / "fixtures" / "bundle_schemas"
FIXTURE_PDB = Path(__file__).resolve().parent / "fixtures" / "two_chain_minimal.pdb"
RUN_ID = "run-schema"

REGENERATE_HINT = (
    "Bundle JSON Schema changed. If the change is additive, regenerate the golden and "
    "bump the schema minor version; if it removes or retypes a field, bump the major "
    "version and add a new golden file."
)


@pytest.mark.parametrize("name", sorted(BUNDLE_SCHEMAS))
def test_schema_matches_golden(name: str) -> None:
    _model, version = BUNDLE_SCHEMAS[name]
    golden = GOLDEN_DIR / f"{name}.{version}.schema.json"
    assert golden.is_file(), f"missing golden snapshot {golden.name}. {REGENERATE_HINT}"
    generated = json.loads(json.dumps(schema_document(name), sort_keys=True))
    assert generated == json.loads(golden.read_text()), REGENERATE_HINT


@pytest.mark.parametrize("name", sorted(BUNDLE_SCHEMAS))
def test_schema_is_self_describing(name: str) -> None:
    _model, version = BUNDLE_SCHEMAS[name]
    document = schema_document(name)
    assert document["$schema"]
    assert document["$id"].endswith(f"/{name}/{version}.json")
    assert document["x-binderdash-schema-version"] == version
    jsonschema.Draft202012Validator.check_schema(document)


def _seed() -> None:
    cache_mod.run_cache.clear()
    cache_mod.designs_cache.clear()
    cache_mod.designs_by_run_id.clear()
    cache_mod.run_cache[RUN_ID] = {
        "run_id": RUN_ID,
        "method": "bindcraft",
        "pdb_files": [str(FIXTURE_PDB)],
        "metadata": {"name": "schema run"},
    }
    rows = [
        {
            "run_id": RUN_ID,
            "design_id": f"d{i}",
            "source_path": "",
            "pdb_file": FIXTURE_PDB.name,
            "Sequence": "ACDEF",
            "iptm": 0.5,
        }
        for i in range(2)
    ]
    cache_mod.designs_by_run_id[RUN_ID] = rows
    cache_mod.designs_cache.extend(rows)


def _bundle_bytes() -> bytes:
    _seed()
    spec = spec_from_live_request(
        BundleDesignsRequest(
            keys=[{"run_id": RUN_ID, "design_id": "d0"}, {"run_id": RUN_ID, "design_id": "d1"}],
            run_ids=[RUN_ID],
            session=SessionState(run_ids=[RUN_ID], visible_columns=["design_id"]),
        )
    )
    built = write_bundle(spec)
    try:
        return built.fileobj.read()
    finally:
        built.close()


def test_bundle_json_validates_against_its_own_shipped_schema(sqlite_designs_repo) -> None:
    """The point of shipping schemas: each JSON member validates against the schema in
    the same archive, with no reference to anything outside it."""
    with zipfile.ZipFile(BytesIO(_bundle_bytes())) as zf:
        root = "binderdash_designs"
        assert {name.split("/", 1)[0] for name in zf.namelist()} == {root}
        for member, schema_name in (
            ("manifest.json", "manifest"),
            ("binderdash_session.json", "binderdash_session"),
        ):
            payload = json.loads(zf.read(f"{root}/{member}"))
            schema = json.loads(zf.read(f"{root}/schemas/{schema_name}.schema.json"))
            jsonschema.validate(payload, schema)


def test_manifest_round_trips_through_its_model(sqlite_designs_repo) -> None:
    with zipfile.ZipFile(BytesIO(_bundle_bytes())) as zf:
        manifest = BundleManifest.model_validate(
            json.loads(zf.read("binderdash_designs/manifest.json"))
        )
    assert manifest.bundle_kind == "designs"
    assert manifest.coverage.designs == 2
