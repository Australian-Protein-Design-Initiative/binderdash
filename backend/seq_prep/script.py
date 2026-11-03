"""Generate a standalone, uv-runnable copy of this package.

The script is not a port: it is this package's own source, inlined at request
time, plus a ``CONFIG`` dict. That is what makes drift between the app and a
downloaded script structurally impossible rather than merely tested for.

It deliberately embeds nothing from the set it was generated from - no
sequences, no seeds, no row hashes - so the same script stays usable on a
similar set later. ``--self-check`` runs a synthetic vector instead.
"""

from __future__ import annotations

import json
import pprint
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..version import build_label
from .config import PrepareConfig
from .optimize import tool_versions

#: Dependency order: each module may only use names defined above it.
_MODULES = (
    "codon",
    "protparam",
    "shortnames",
    "tags",
    "mixed",
    "config",
    "build",
    "export",
    "optimize",
)

_RELATIVE_IMPORT = re.compile(r"^(\s*)from \.\w*(\s|\.)?.*import")
# Every module opens with one; the generated file carries a single copy up top,
# because __future__ imports are only legal at the start of a file.
_FUTURE_IMPORT = re.compile(r"^\s*from __future__ import")
_DOCSTRING_HEADER = re.compile(r'^"""', re.MULTILINE)


def _strip_module_imports(source: str) -> str:
    """Drop ``from .x import y`` and ``from __future__ import ...``.

    Everything lands in one module namespace, so the relative names resolve
    without them, and the single ``__future__`` import lives at the top of the
    generated file.
    """
    out: List[str] = []
    lines = source.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        if _FUTURE_IMPORT.match(line):
            i += 1
            continue
        if _RELATIVE_IMPORT.match(line):
            if "(" in line and ")" not in line:
                while i < len(lines) and ")" not in lines[i]:
                    i += 1
            i += 1
            continue
        out.append(line)
        i += 1
    return "\n".join(out)


def _module_sources() -> str:
    here = Path(__file__).parent
    blocks: List[str] = []
    for name in _MODULES:
        source = (here / f"{name}.py").read_text()
        blocks.append(
            f"# {'=' * 70}\n# from binderdash backend/seq_prep/{name}.py\n# {'=' * 70}\n"
            + _strip_module_imports(source)
        )
    return "\n\n".join(blocks)


def _self_check_vector(cfg: PrepareConfig) -> Dict[str, Any]:
    """A synthetic design and its expected construct under this config.

    Computed here by the server's own builder, so running it later proves the
    pinned dependencies still behave as they did at download time. It carries no
    user data, which is why it is synthetic rather than a real row.
    """
    from .build import build_rows

    design = {
        "design_id": "selfcheck_design_1",
        "run_id": "selfcheck",
        "tag": "N",
        "Sequence": "MKWVTFISLLWACDEFGHIKLMNPQRSTVWY",
    }
    row = build_rows([design], cfg)[0]
    return {
        "design": design,
        "expected_prepared_aa": row.prepared_aa,
        "expected_prepared_dna": row.prepared_dna,
        "expected_short_name": row.short_name,
    }


def _as_python_literal(value: Any) -> str:
    """Render as Python source, not JSON: ``True`` and ``None``, not ``true``/``null``."""
    return pprint.pformat(value, indent=4, width=96, sort_dicts=False)


def _header(versions: Dict[str, str]) -> str:
    pins = ", ".join(
        f'"{pkg}=={ver}"' for pkg, ver in sorted(versions.items())
    )
    return f'''#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = [{pins}]
# ///
'''


_MAIN = '''

# ======================================================================
# Command line
# ======================================================================

SEQUENCE_COLUMNS = ("prepared_aa", "original_sequence", "Sequence", "sequence", "binder_sequence", "seq")


def read_designs(path, default_tag=None):
    """Read a Prepare Sequences export, or any TSV/CSV with design_id, a
    sequence column, and tag."""
    text = Path(path).read_text()
    delimiter = "\\t" if "\\t" in text.splitlines()[0] else ","
    rows = list(csv.DictReader(io.StringIO(text), delimiter=delimiter))
    if not rows:
        raise SystemExit(f"{path}: no data rows")

    if default_tag:
        rows = [{**r, "tag": (r.get("tag") or "").strip() or default_tag} for r in rows]

    missing_tag = [r for r in rows if not (r.get("tag") or "").strip()]
    if missing_tag:
        raise SystemExit(
            f"{path}: {len(missing_tag)} row(s) have no 'tag' column value.\\n"
            "Tag placement is decided from the 3D structure (buried surface area and\\n"
            "distance to the target), so it cannot be recomputed here. Export from\\n"
            "Binderdash with the tag column, or pass --default-tag N|C."
        )
    return rows


def run_self_check():
    vector = SELF_CHECK
    if not vector:
        print("No self-check vector embedded.", file=sys.stderr)
        return 1
    cfg = PrepareConfig.from_payload(CONFIG)
    row = build_rows([vector["design"]], cfg)[0]
    problems = []
    for field_name, expected in (
        ("prepared_aa", vector["expected_prepared_aa"]),
        ("prepared_dna", vector["expected_prepared_dna"]),
        ("short_name", vector["expected_short_name"]),
    ):
        actual = getattr(row, field_name)
        if actual != expected:
            problems.append(f"  {field_name}:\\n    expected {expected!r}\\n    got      {actual!r}")
    if problems:
        print(
            "Self-check FAILED. This script no longer reproduces what Binderdash\\n"
            "produced when it was downloaded, most likely because an installed\\n"
            "dependency version differs from the pins in the header.\\n"
            + "\\n".join(problems),
            file=sys.stderr,
        )
        return 1
    print("Self-check passed: constructs match what Binderdash produced at download time.")
    return 0


def main(argv=None):
    global OPTIMIZATION_ATTEMPTS
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("input", nargs="?", help="TSV/CSV of designs (needs design_id, a sequence column, and tag)")
    parser.add_argument("--format", default="twist",
                        help="comma-separated: twist, fasta, tsv, csv (default: twist)")
    parser.add_argument("--out-prefix", default=None,
                        help="output basename (default: derived from the order name and the date)")
    parser.add_argument("--stdout", action="store_true", help="write the first format to stdout instead of a file")
    parser.add_argument("--self-check", action="store_true",
                        help="verify this script still reproduces what Binderdash produced")
    parser.add_argument("--default-tag", choices=["N", "C"], default=None,
                        help="tag zone for rows with no tag column value")

    parser.add_argument("--optimize", dest="optimize", action="store_true", default=None,
                        help="codon-optimise the DNA with DnaChisel (implied by --dna)")
    parser.add_argument("--no-optimize", dest="optimize", action="store_false",
                        help="skip codon optimisation; use the naive reverse translation")
    parser.add_argument("--seed-map", default=None,
                        help="bundle JSON (or {design_id: seed} JSON) whose seeds to replay")
    parser.add_argument("--retries", type=int, default=None,
                        help=f"attempts per design before reporting no solution (default {OPTIMIZATION_ATTEMPTS})")

    parser.add_argument("--dna", dest="dna_mode", action="store_true", default=None,
                        help="produce DNA rather than amino acids")
    parser.add_argument("--no-dna", dest="dna_mode", action="store_false", help="produce amino acids")
    parser.add_argument("--post-stop-pad-to", type=int, default=None,
                        help="pad the construct to this many nucleotides after the stop")
    parser.add_argument("--no-post-stop-pad", action="store_true", help="disable post-stop padding")
    parser.add_argument("--min-dna-fragment-length", type=int, default=None)
    parser.add_argument("--double-stop", dest="double_stop", action="store_true", default=None)
    parser.add_argument("--no-double-stop", dest="double_stop", action="store_false")
    parser.add_argument("--n-terminal-prefix", default=None)
    parser.add_argument("--c-terminal-suffix", default=None)
    parser.add_argument("--order-name", default=None)
    parser.add_argument("--short-name-prefix", default=None,
                        help="override the leading segment of the construct "
                             "short names (CONFIG's short_name_strategy)")
    args = parser.parse_args(argv)

    if args.self_check:
        return run_self_check()
    if not args.input:
        parser.error("an input TSV/CSV is required (or use --self-check)")

    payload = json.loads(json.dumps(CONFIG))
    stop = payload.setdefault("stop_options", {})
    if args.dna_mode is not None:
        payload["dna_mode"] = args.dna_mode
    if args.post_stop_pad_to is not None:
        stop["postStopPadUpToNucleotideLength"] = args.post_stop_pad_to
    if args.no_post_stop_pad:
        stop["postStopPadUpToNucleotideLength"] = None
    if args.min_dna_fragment_length is not None:
        stop["minDnaFragmentLength"] = args.min_dna_fragment_length
    if args.double_stop is not None:
        stop["useDoubleStop"] = args.double_stop
    if args.n_terminal_prefix is not None:
        payload["n_terminal_prefix"] = args.n_terminal_prefix
    if args.c_terminal_suffix is not None:
        payload["c_terminal_suffix"] = args.c_terminal_suffix
    if args.order_name is not None:
        payload["order_name"] = args.order_name
    if args.short_name_prefix is not None:
        # Which key from_payload reads depends on shortNameKind, so set the
        # prefix under every kind's name rather than only the configured one.
        sn = payload.setdefault("short_name_strategy", {})
        for key in ("shortNameSmartStemAddPrefix", "shortNameSplitAddPrefix",
                    "shortNamePatternPrefix", "shortNameStripNewPrefix"):
            sn[key] = args.short_name_prefix

    cfg = PrepareConfig.from_payload(payload)
    errors = cfg.validation_errors()
    if errors:
        raise SystemExit("Configuration is not valid:\\n  " + "\\n  ".join(errors))

    designs = read_designs(args.input, args.default_tag)

    optimized, opt_errors, seeds_used = {}, {}, {}
    want_optimize = args.optimize if args.optimize is not None else cfg.dna_mode
    if want_optimize:
        seeds = {}
        if args.seed_map:
            raw = json.loads(Path(args.seed_map).read_text())
            rows = raw.get("prepared", raw).get("rows", []) if isinstance(raw, dict) else []
            if rows:
                seeds = {r["design_id"]: r["seed"] for r in rows if r.get("seed") is not None}
            elif isinstance(raw, dict):
                seeds = {k: int(v) for k, v in raw.items() if isinstance(v, int)}
            print(f"Replaying {len(seeds)} recorded seed(s) from {args.seed_map}", file=sys.stderr)

        if args.retries is not None:
            OPTIMIZATION_ATTEMPTS = max(1, args.retries)

        base_rows = build_rows(designs, cfg)
        coding, fixed = {}, {}
        for row in base_rows:
            aa, mask = row.coding_aa_and_fixed()
            if aa:
                coding[row.design_id] = aa
                fixed[row.design_id] = mask
        print(f"Optimising {len(coding)} sequence(s); this is the slow part.", file=sys.stderr)
        results = optimize_sequences(
            coding,
            cfg.codon_table_id or "e_coli_316407",
            [serialize_constraint_for_dnachisel(c) for c in cfg.optimization_constraints],
            cfg.optimization_method,
            fixed,
            seeds or None,
        )
        for design_id, res in results.items():
            if res.get("optimized_dna"):
                optimized[design_id] = res["optimized_dna"]
            if res.get("error"):
                opt_errors[design_id] = res["error"]
            if res.get("seed") is not None:
                seeds_used[design_id] = res["seed"]

    rows = build_rows(designs, cfg, optimized=optimized, errors=opt_errors, seeds=seeds_used)

    failed = [d for d, e in opt_errors.items() if e]
    if failed:
        print(
            f"{len(failed)} design(s) failed optimisation: {', '.join(sorted(failed)[:5])}"
            f"{' ...' if len(failed) > 5 else ''}\\n"
            "Re-run to try different seeds, or raise --retries.",
            file=sys.stderr,
        )

    formats = [f.strip() for f in args.format.split(",") if f.strip()]
    if args.stdout:
        print(render(formats[0], rows, cfg))
        return 0

    stem = args.out_prefix or export_basename(cfg.order_name)
    for fmt in formats:
        text = render(fmt, rows, cfg)
        suffix = FORMATS[fmt][1]
        path = Path(f"{stem}_{fmt}.{suffix}" if len(formats) > 1 else f"{stem}.{suffix}")
        path.write_text(text + "\\n")
        print(f"wrote {path} ({len(rows)} row(s))", file=sys.stderr)

    if seeds_used:
        seed_path = Path(f"{stem}_seeds.json")
        seed_path.write_text(json.dumps(seeds_used, indent=2) + "\\n")
        print(f"wrote {seed_path} - pass it to --seed-map to reproduce this DNA", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
'''


def generate_script(cfg: PrepareConfig, *, include_self_check: bool = True) -> str:
    """Return the complete single-file script for this configuration."""
    versions = tool_versions()
    payload = cfg.to_payload()
    self_check = _self_check_vector(cfg) if include_self_check else None

    doc = f'''"""Regenerate Binderdash sequence constructs.

Generated by Binderdash from the Prepare Sequences tab. The builder below is
Binderdash's own source, inlined verbatim, so this script produces exactly what
the app produced - there is no second implementation to drift.

The settings are in CONFIG at the top of this file. Edit them, or override the
common ones on the command line:

    uv run {_FILENAME}  designs.tsv
    uv run {_FILENAME}  designs.tsv --format fasta --post-stop-pad-to 400
    uv run {_FILENAME}  --self-check

The input needs design_id, a sequence column, and tag (N or C). Tag placement
comes from 3D structure analysis in Binderdash and cannot be recomputed here.

Codon table: {payload.get("codon_table_id") or "E. coli (built-in fallback)"}
Binderdash: {build_label()}
Generated against: {", ".join(f"{k} {v}" for k, v in sorted(versions.items()))}
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import sys
from pathlib import Path

CONFIG = {_as_python_literal(payload)}

SELF_CHECK = {_as_python_literal(self_check)}
'''
    return "".join(
        [_header(versions), doc, "\n\n", _module_sources(), _MAIN]
    )


_FILENAME = "prepare_sequences.py"


def script_filename(cfg: PrepareConfig) -> str:
    from .export import sanitize_order_name

    stem = sanitize_order_name(cfg.order_name)
    return f"prepare_sequences_{stem}.py" if stem else _FILENAME
