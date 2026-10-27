"""The prepare / script endpoints, and that a generated script actually runs."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

from backend.seq_prep import PrepareConfig, build_rows
from backend.seq_prep.script import generate_script

DESIGNS = [
    {"design_id": "batch-1_dA", "run_id": "r1", "tag": "N", "Sequence": "MKWVTFISLLWACDEF"},
    {"design_id": "batch-1_dB", "run_id": "r1", "tag": "C", "Sequence": "GGCDEFHIKWMMMM"},
]


@pytest.fixture
def client(api_client):
    return api_client


def test_tag_presets_are_served_as_data(client):
    r = client.get("/api/sequences/tag-presets")
    assert r.status_code == 200
    body = r.json()
    kinds = {p["kind"] for p in body["presets"]}
    assert {"hisN", "hisC", "flag", "linker", "stop"} <= kinds
    assert body["default_constraints"]
    assert body["default_post_stop_padding"]


def test_prepare_builds_rows(client):
    r = client.post("/api/sequences/prepare", json={"config": {}, "designs": DESIGNS})
    assert r.status_code == 200
    body = r.json()
    assert body["validation_errors"] == []
    assert [row["design_id"] for row in body["rows"]] == ["batch-1_dA", "batch-1_dB"]
    assert body["rows"][0]["prepared_aa"].startswith("MKWVTFISLLWACDEF")
    assert body["rows"][0]["segments_aa"]


def test_prepare_can_omit_segments(client):
    r = client.post(
        "/api/sequences/prepare",
        json={"config": {}, "designs": DESIGNS, "include_segments": False},
    )
    assert "segments_aa" not in r.json()["rows"][0]


def test_prepare_reports_config_errors_without_building(client):
    bad = {"n_terminal_prefix": "MGS!!!"}
    r = client.post("/api/sequences/prepare", json={"config": bad, "designs": DESIGNS})
    assert r.status_code == 200
    body = r.json()
    assert body["rows"] == []
    assert any("invalid character" in e for e in body["validation_errors"])


def test_script_download_is_attached_python(client):
    r = client.post("/api/sequences/prepare/script", json={"config": {}})
    assert r.status_code == 200
    assert "attachment" in r.headers["content-disposition"]
    assert r.text.startswith("#!/usr/bin/env -S uv run --script")
    assert "# /// script" in r.text


def test_script_rejects_an_invalid_config(client):
    r = client.post(
        "/api/sequences/prepare/script", json={"config": {"c_terminal_suffix": "??"}}
    )
    assert r.status_code == 400


def _write_script(tmp_path: Path, payload: dict) -> Path:
    cfg = PrepareConfig.from_payload(payload)
    path = tmp_path / "prepare_sequences.py"
    path.write_text(generate_script(cfg))
    return path


def _run(script: Path, *args: str) -> subprocess.CompletedProcess:
    # -I so the script cannot import from its own directory or the CWD.
    return subprocess.run(
        [sys.executable, "-I", str(script), *args],
        capture_output=True,
        text=True,
        cwd=script.parent,
        timeout=900,
    )


def test_generated_script_self_check_passes(tmp_path):
    result = _run(_write_script(tmp_path, {}), "--self-check")
    assert result.returncode == 0, result.stderr
    assert "Self-check passed" in result.stdout


def test_generated_script_reproduces_the_servers_constructs(tmp_path):
    """The point of the whole feature: same config, same input, same output."""
    payload = {"stop_options": {"postStopPadUpToNucleotideLength": None}}
    script = _write_script(tmp_path, payload)

    tsv = tmp_path / "designs.tsv"
    tsv.write_text(
        "design_id\ttag\tSequence\n"
        + "\n".join(f"{d['design_id']}\t{d['tag']}\t{d['Sequence']}" for d in DESIGNS)
        + "\n"
    )

    result = _run(script, str(tsv), "--format", "fasta", "--stdout")
    assert result.returncode == 0, result.stderr

    cfg = PrepareConfig.from_payload(payload)
    rows = build_rows(DESIGNS, cfg)
    expected = "\n".join(f">{r.design_id}\n{r.prepared_aa}" for r in rows)
    assert result.stdout.strip() == expected.strip()


def test_generated_script_requires_a_tag_column(tmp_path):
    script = _write_script(tmp_path, {})
    tsv = tmp_path / "notag.tsv"
    tsv.write_text("design_id\tSequence\nd1\tMKWVTFISLL\n")

    result = _run(script, str(tsv))
    assert result.returncode != 0
    assert "tag" in result.stderr

    ok = _run(script, str(tsv), "--default-tag", "N")
    assert ok.returncode == 0, ok.stderr


def test_generated_script_short_name_prefix_overrides_the_config(tmp_path):
    payload = {
        "dna_mode": False,
        "short_name_strategy": {
            "shortNameKind": "smartStemHash",
            "shortNameSmartStemAddPrefix": "nb",
        },
    }
    script = _write_script(tmp_path, payload)
    tsv = tmp_path / "designs.tsv"
    tsv.write_text(
        "design_id\ttag\tSequence\n"
        + "\n".join(f"{d['design_id']}\t{d['tag']}\t{d['Sequence']}" for d in DESIGNS)
        + "\n"
    )

    result = _run(script, str(tsv), "--format", "twist", "--stdout",
                  "--short-name-prefix", "zz")
    assert result.returncode == 0, result.stderr
    names = [line.split(",")[0] for line in result.stdout.strip().splitlines()[1:]]
    assert names and all(n.startswith("zz") for n in names), result.stdout


# --- MCP download URL ------------------------------------------------------


def test_prepare_download_round_trip(client):
    """The MCP tool stashes a request and hands back a tokenised URL; the REST
    handler re-renders it. Nothing is written to disk."""
    from backend.download_tokens import mint_prepare_download_token
    from backend.seq_prep import stash as prepare_stash

    prepare_id = prepare_stash.put({}, DESIGNS)
    token = mint_prepare_download_token(prepare_id, "twist")

    r = client.get(
        "/api/sequences/prepare/download",
        params={"prepare_id": prepare_id, "format": "twist", "download_token": token},
    )
    assert r.status_code == 200
    assert r.text.splitlines()[0] == "name,sequence,original_name"
    assert "batch-1_dA" in r.text


def test_prepare_download_rejects_a_token_for_another_format(client):
    from backend.download_tokens import mint_prepare_download_token
    from backend.seq_prep import stash as prepare_stash

    prepare_id = prepare_stash.put({}, DESIGNS)
    token = mint_prepare_download_token(prepare_id, "twist")

    r = client.get(
        "/api/sequences/prepare/download",
        params={"prepare_id": prepare_id, "format": "fasta", "download_token": token},
    )
    assert r.status_code == 403


def test_prepare_download_rejects_a_token_for_another_request(client):
    from backend.download_tokens import mint_prepare_download_token
    from backend.seq_prep import stash as prepare_stash

    mine = prepare_stash.put({}, DESIGNS)
    theirs = prepare_stash.put({}, DESIGNS)
    token = mint_prepare_download_token(theirs, "twist")

    r = client.get(
        "/api/sequences/prepare/download",
        params={"prepare_id": mine, "format": "twist", "download_token": token},
    )
    assert r.status_code == 403


def test_prepare_download_404s_after_the_stash_is_gone(client):
    """A restart drops the stash, so the agent is told to run the tool again
    rather than served a stale or empty file."""
    from backend.download_tokens import mint_prepare_download_token
    from backend.seq_prep import stash as prepare_stash

    prepare_id = prepare_stash.put({}, DESIGNS)
    token = mint_prepare_download_token(prepare_id, "twist")
    prepare_stash.clear()

    r = client.get(
        "/api/sequences/prepare/download",
        params={"prepare_id": prepare_id, "format": "twist", "download_token": token},
    )
    assert r.status_code == 404


def test_always_tags_ignore_the_tag_end_column_and_keep_their_position() -> None:
    from backend.seq_prep import PrepareConfig, build_rows

    cfg = PrepareConfig.from_payload(
        {
            "n_tags": [
                {"id": "1", "kind": "custom", "sequence": "MK", "label": "x", "always": True},
                {"id": "2", "kind": "flag", "sequence": "DYKDDDDK", "label": "FLAG"},
            ],
            "c_tags": [{"id": "3", "kind": "hisC", "sequence": "GSHHHHHH", "label": "His-C"}],
            "stop_options": {"includeStopForNTagged": False, "includeStopForCTagged": False},
        }
    )
    designs = [
        {"design_id": "a", "sequence": "AAA", "tag": "N"},
        {"design_id": "b", "sequence": "AAA", "tag": "C"},
        {"design_id": "c", "sequence": "AAA", "tag": ""},
    ]
    aa = {r.design_id: r.prepared_aa.rstrip("acgt") for r in build_rows(designs, cfg)}
    assert aa["a"].startswith("MKDYKDDDDKAAA")
    assert aa["b"].startswith("MKAAAGSHHHHHH")
    assert aa["c"].startswith("MKAAA") and "DYKD" not in aa["c"]


def test_legacy_prefix_and_suffix_become_always_tags() -> None:
    from backend.seq_prep import PrepareConfig

    cfg = PrepareConfig.from_payload({"n_terminal_prefix": "MG", "c_terminal_suffix": "LE"})
    assert [(t.sequence, t.always) for t in cfg.n_tags] == [("MG", True)]
    assert [(t.sequence, t.always) for t in cfg.c_tags] == [("LE", True)]
