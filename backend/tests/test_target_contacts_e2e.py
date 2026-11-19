"""End-to-end target contacts against the bundled PD-L1 example run.

Covers the parts the unit tests stub out: chain-role resolution, per-design structure
path resolution, real SASA computation and caching, and a contact filter narrowing the
result set through the ordinary filtering endpoints.
"""

from pathlib import Path

import pytest

EXAMPLE_RUNS = Path(__file__).resolve().parents[2] / "example_runs" / "pdl1"

pytestmark = pytest.mark.skipif(
    not EXAMPLE_RUNS.is_dir(), reason="example_runs/pdl1 not present"
)


@pytest.fixture(scope="module")
def ingested(tmp_path_factory):
    """Scan and ingest the example runs once, then hand back a client for the module."""
    import backend.auth as auth_mod
    import backend.main as main_mod
    import backend.settings as settings_mod
    from backend.auth import get_current_user_optional
    from backend.routers.designs import _authorize_list_designs
    from fastapi.testclient import TestClient

    tmp_path = tmp_path_factory.mktemp("target_contacts_e2e")
    # Before the copy below: the runs router holds the original settings object and
    # main's lifespan reads the copy, and both must allow the example directory.
    original_base_dirs = list(settings_mod.settings.run_base_dirs)
    settings_mod.update_run_base_dirs([str(EXAMPLE_RUNS)])
    patched = main_mod.settings.model_copy(update={"auth_disabled": True})
    originals = [(mod, mod.settings) for mod in (main_mod, settings_mod, auth_mod)]
    original_default = main_mod.default_sqlite_url
    for mod, _ in originals:
        mod.settings = patched
    main_mod.default_sqlite_url = lambda: f"sqlite:///{tmp_path}/api.sqlite"

    async def _auth_bypass():
        return None

    app = main_mod.app
    app.dependency_overrides[get_current_user_optional] = _auth_bypass
    app.dependency_overrides[_authorize_list_designs] = _auth_bypass

    with TestClient(app) as client:
        # force_rescan_of_ingested: the repository is process-global, so whichever
        # database a previously-run test left behind would otherwise filter these runs
        # out as already ingested.
        scan = client.post(
            "/api/runs/scan",
            json={"folders": [str(EXAMPLE_RUNS)], "force_rescan_of_ingested": True},
        )
        assert scan.status_code == 200, scan.text
        runs = scan.json()["runs"]
        assert runs, "no runs discovered in example_runs/pdl1"
        ingest = client.post("/api/runs/ingest", json={"runs": runs})
        assert ingest.status_code == 200, ingest.text
        run_ids = [r["run_id"] for r in ingest.json()["runs"]]
        yield client, run_ids

    app.dependency_overrides.clear()
    for mod, original in originals:
        mod.settings = original
    main_mod.default_sqlite_url = original_default
    settings_mod.update_run_base_dirs(original_base_dirs)


def test_target_residues_lists_a_target_per_run_scope(ingested):
    client, run_ids = ingested
    res = client.post("/api/filtering/target-residues", json={"run_ids": run_ids})
    assert res.status_code == 200, res.text
    body = res.json()

    assert body["targets"], f"no target resolved; warnings={body['warnings']}"
    target = body["targets"][0]
    assert target["residues"], "target has no residues"
    assert target["length"] == len(target["residues"])
    # Labels are <chain><resseq>, the complex_sasa.py convention.
    first = target["residues"][0]
    assert first["label"] == f"{first['chain']}{first['resseq']}"
    assert first["sasa_apo"] >= 0

    assert body["coverage"]
    assert all(c["total_designs"] > 0 for c in body["coverage"])


def test_compute_then_filter_narrows_the_design_set(ingested):
    client, run_ids = ingested
    targets = client.post("/api/filtering/target-residues", json={"run_ids": run_ids}).json()
    target = targets["targets"][0]
    scope_run_ids = target["run_ids"]

    designs = client.post(
        "/api/filtering/apply", json={"run_ids": scope_run_ids, "filters": []}
    ).json()
    total = designs["total_designs"]
    assert total > 0

    computed = client.post(
        "/api/filtering/target-contacts/compute",
        json={"run_ids": scope_run_ids, "max_workers": 2},
    )
    assert computed.status_code == 200, computed.text
    body = computed.json()
    assert body["computed"] + body["cached"] > 0, f"nothing computed: {body['errors'][:3]}"

    # Cached on a second call rather than recomputed.
    again = client.post(
        "/api/filtering/target-contacts/compute",
        json={"run_ids": scope_run_ids, "max_workers": 2},
    ).json()
    assert again["computed"] == 0
    assert again["cached"] > 0

    # A profile over every computed design must find some residue the binders contact.
    profile = client.post(
        "/api/filtering/target-contacts/profile",
        json={"run_ids": scope_run_ids, "target_key": target["target_key"], "metric": "delta_sasa"},
    ).json()
    assert profile["n_designs"] > 0
    buried = [r for r in profile["residues"] if (r["mean"] or 0) > 1.0]
    assert buried, "no target residue is buried by any binder"

    # Filtering on the most-buried residue keeps some designs and excludes others,
    # which is the whole point of the feature.
    hotspot = max(profile["residues"], key=lambda r: r["mean"] or 0)
    group = {
        "target_key": target["target_key"],
        "run_ids": scope_run_ids,
        "filters": [
            {
                "residues": [hotspot["label"]],
                "scope": "any",
                "metric": "distance",
                "distance_type": "heavy",
                "operator": "<=",
                "value": 5.0,
            }
        ],
    }
    filtered = client.post(
        "/api/filtering/apply",
        json={"run_ids": scope_run_ids, "filters": [], "target_contact_groups": [group]},
    ).json()
    assert 0 < filtered["final_passing"] <= total

    # The opposite condition must select the complementary set.
    inverse = dict(group)
    inverse["filters"] = [{**group["filters"][0], "operator": ">", "value": 5.0}]
    inverse_result = client.post(
        "/api/filtering/apply",
        json={"run_ids": scope_run_ids, "filters": [], "target_contact_groups": [inverse]},
    ).json()
    assert filtered["final_passing"] + inverse_result["final_passing"] == total


def test_cascade_reports_contact_stages_with_a_readable_label(ingested):
    client, run_ids = ingested
    targets = client.post("/api/filtering/target-residues", json={"run_ids": run_ids}).json()
    target = targets["targets"][0]
    label = target["residues"][0]["label"]

    preview = client.post(
        "/api/filtering/preview",
        json={
            "run_ids": target["run_ids"],
            "filters": [],
            "target_contact_groups": [
                {
                    "target_key": target["target_key"],
                    "label": "PD-L1",
                    "filters": [
                        {
                            "residues": [label],
                            "scope": "any",
                            "metric": "distance",
                            "distance_type": "heavy",
                            "operator": "<=",
                            "value": 8.0,
                        }
                    ],
                }
            ],
        },
    )
    assert preview.status_code == 200, preview.text
    stages = preview.json()["per_filter_counts"]
    assert len(stages) == 1
    assert stages[0]["column"].startswith("__tc_")
    assert stages[0]["label"].startswith("PD-L1:")
    assert label in stages[0]["label"]


def test_one_target_spans_runs_that_letter_its_chain_differently(ingested):
    """The bundled PD-L1 runs carry the target on chain A (BindCraft) and chain B
    (RFdiffusion). They are the same protein, so they must group as one target, and a
    condition written in one run's numbering must constrain designs in both — otherwise
    it silently exempts half the scope."""
    client, run_ids = ingested
    body = client.post("/api/filtering/target-residues", json={"run_ids": run_ids}).json()

    assert len(body["targets"]) == 1, [t["label"] for t in body["targets"]]
    target = body["targets"][0]
    assert len(target["run_ids"]) == len(run_ids)

    client.post("/api/filtering/target-contacts/compute", json={"run_ids": target["run_ids"]})
    group = {
        "target_key": target["target_key"],
        "filters": [
            {
                "residues": [target["residues"][0]["label"]],
                "scope": "any",
                "metric": "distance",
                "distance_type": "heavy",
                "operator": ">",
                "value": 0.0,
            }
        ],
    }
    result = client.post(
        "/api/filtering/apply",
        json={"run_ids": target["run_ids"], "filters": [], "target_contact_groups": [group]},
    ).json()

    # A ">0 Å" condition is satisfied by every design whose record resolved, so every
    # run in the target's scope should contribute passing designs.
    runs_with_hits = {k["run_id"] for k in result["passing_keys"]}
    assert runs_with_hits == set(target["run_ids"])


def test_virtual_columns_are_not_offered_as_filterable_columns(ingested):
    client, run_ids = ingested
    columns = client.post("/api/filtering/columns", json={"run_ids": run_ids}).json()["columns"]
    assert not any(c["name"].startswith("__tc_") for c in columns)
