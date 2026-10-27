"""The Prepare Sequences configuration.

Mirrors ``backend.bundles.models.PrepareSequencesPayload`` minus ``rows``: the
same JSON serves as the bundle record, the prepare-endpoint request body and the
``CONFIG`` dict of a downloaded script.

The wire format keeps the frontend's camelCase keys inside ``stop_options`` and
``short_name_strategy`` because those dicts are already persisted in user bundles
and IndexedDB; translating them here is cheaper than migrating stored data.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .codon import CodonTable
from .shortnames import ShortNameStrategy
from .tags import DEFAULT_POST_STOP_PADDING, DEFAULT_TWIST_CONSTRAINTS

SCHEMA_VERSION = "1.1"
KIND = "binderdash.prepare_sequences"

_STOP_DEFAULTS: Dict[str, Any] = {
    "includeStopForNTagged": True,
    "includeStopForCTagged": True,
    "useDoubleStop": False,
    "dontModifyStartAtg": True,
    "showPostStopPadding": True,
    "postStopPadding": DEFAULT_POST_STOP_PADDING,
    "postStopPadUpToNucleotideLength": 300,
    "onlyUseNTerminalTagWhenPaddingRequired": False,
    "onlyUseCTerminalTagWhenPaddingRequired": False,
    "minDnaFragmentLength": 300,
}

_SHORT_NAME_KEY_MAP = {
    "shortNameKind": "kind",
    "shortNameRegexPattern": "pattern",
    "shortNameRegexReplacement": "replacement",
    "shortNameRegexFlags": "flags",
    "shortNameSplitDelimiter": "delimiter",
    "shortNameSplitAddPrefix": "add_prefix",
    "shortNameSplitAddSuffix": "add_suffix",
    "shortNameSplitAddHash": "add_hash",
    "shortNamePatternPrefix": "prefix",
    "shortNamePatternUidLength": "uid_length",
    "shortNamePatternNumberPad": "number_pad",
    "shortNameSmartHashLen": "hash_len",
    "shortNameSmartStemIncludeHash": "include_hash",
    "shortNameSmartStemIncludeIndex": "include_index",
    "shortNameSmartStemRemoveCommonPrefix": "remove_common_prefix",
    "shortNameSmartStemRemoveCommonSuffix": "remove_common_suffix",
    "shortNameSmartStemAddPrefix": "add_prefix",
    "shortNameSmartStemAddSuffix": "add_suffix",
    "shortNameStripPrefixRegex": "prefix_pattern",
    "shortNameStripSuffixRegex": "suffix_pattern",
    "shortNameStripNewPrefix": "new_prefix",
}

_JS_BACKREF = re.compile(r"\$(\d)")


def migrate_js_replacement(replacement: str) -> str:
    """Rewrite JS ``$1`` backreferences as Python ``\\1``.

    Short names used to be generated in the browser, so replacements stored in
    schema 1.0 bundles use JS syntax. ``$&`` (whole match) has no single-token
    Python equivalent and becomes ``\\g<0>``.
    """
    return _JS_BACKREF.sub(r"\\\1", replacement.replace("$&", r"\g<0>"))


@dataclass
class PlacedTag:
    kind: str
    sequence: str
    label: str = ""
    id: str = ""
    #: Applied to every design, ignoring its tag-end column.
    always: bool = False

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "PlacedTag":
        return cls(
            kind=str(d.get("kind") or "custom"),
            sequence=str(d.get("sequence") or ""),
            label=str(d.get("label") or ""),
            id=str(d.get("id") or ""),
            always=bool(d.get("always")),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {"id": self.id, "kind": self.kind, "sequence": self.sequence, "label": self.label, "always": self.always}


@dataclass
class PrepareConfig:
    """Everything the UI sets, flattened into one record."""

    n_tags: List[PlacedTag] = field(default_factory=list)
    c_tags: List[PlacedTag] = field(default_factory=list)

    include_stop_for_n_tagged: bool = True
    include_stop_for_c_tagged: bool = True
    use_double_stop: bool = False
    dont_modify_start_atg: bool = True
    show_post_stop_padding: bool = True
    post_stop_padding: str = DEFAULT_POST_STOP_PADDING
    post_stop_pad_up_to_nucleotide_length: Optional[int] = 300
    only_use_n_terminal_tag_when_padding_required: bool = False
    only_use_c_terminal_tag_when_padding_required: bool = False
    min_dna_fragment_length: int = 300

    dna_mode: bool = False
    good_only: bool = False
    order_name: str = ""
    extract_chain: str = "B"

    codon_table_id: Optional[str] = None
    codon_table: Optional[CodonTable] = None
    optimization_method: str = "match_codon_usage"
    optimization_constraints: List[Dict[str, Any]] = field(
        default_factory=lambda: [dict(c) for c in DEFAULT_TWIST_CONSTRAINTS]
    )

    short_name: ShortNameStrategy = field(default_factory=ShortNameStrategy)
    short_name_max_len: int = 32

    def table(self) -> CodonTable:
        return self.codon_table or CodonTable.ecoli_fallback()

    # -- wire format ---------------------------------------------------------

    @classmethod
    def from_payload(cls, payload: Dict[str, Any]) -> "PrepareConfig":
        stop = {**_STOP_DEFAULTS, **(payload.get("stop_options") or {})}
        raw_sn = payload.get("short_name_strategy") or {}
        version = str(payload.get("schema_version") or "1.0")

        sn_kwargs: Dict[str, Any] = {}
        for js_key, py_key in _SHORT_NAME_KEY_MAP.items():
            if js_key not in raw_sn:
                continue
            value = raw_sn[js_key]
            # smartStemHash and splitTake both map onto add_prefix/add_suffix;
            # only the fields belonging to the selected kind are meaningful.
            sn_kwargs[py_key] = value

        kind = str(raw_sn.get("shortNameKind") or "none")
        sn_kwargs["kind"] = kind
        if kind == "smartStemHash":
            sn_kwargs["add_prefix"] = raw_sn.get("shortNameSmartStemAddPrefix", "") or ""
            sn_kwargs["add_suffix"] = raw_sn.get("shortNameSmartStemAddSuffix", "") or ""
        elif kind == "splitTake":
            sn_kwargs["add_prefix"] = raw_sn.get("shortNameSplitAddPrefix", "") or ""
            sn_kwargs["add_suffix"] = raw_sn.get("shortNameSplitAddSuffix", "") or ""

        indices_raw = str(raw_sn.get("shortNameSplitIndices") or "")
        indices = [int(p) for p in re.split(r"[,\s]+", indices_raw) if p.strip().isdigit()]
        sn_kwargs["indices"] = [i for i in indices if i > 0] or [1, 2, 3]

        if "replacement" in sn_kwargs and version.startswith("1.0"):
            sn_kwargs["replacement"] = migrate_js_replacement(str(sn_kwargs["replacement"]))

        sn_kwargs = {k: v for k, v in sn_kwargs.items() if v is not None}
        strategy = ShortNameStrategy(**sn_kwargs)

        table_dict = payload.get("codon_table")
        pad_target = stop.get("postStopPadUpToNucleotideLength")
        n_tags = [PlacedTag.from_dict(t) for t in payload.get("n_tags") or []]
        c_tags = [PlacedTag.from_dict(t) for t in payload.get("c_tags") or []]
        # Older payloads had free-text N/C additions applied to every design; they are
        # now ordinary custom tags flagged "always", outermost as before.
        n_fix = str(payload.get("n_terminal_prefix") or "").strip()
        c_fix = str(payload.get("c_terminal_suffix") or "").strip()
        if n_fix:
            n_tags.insert(0, PlacedTag("custom", n_fix, "N-terminal prefix", "legacy-n-prefix", True))
        if c_fix:
            c_tags.append(PlacedTag("custom", c_fix, "C-terminal suffix", "legacy-c-suffix", True))
        return cls(
            n_tags=n_tags,
            c_tags=c_tags,
            include_stop_for_n_tagged=bool(stop["includeStopForNTagged"]),
            include_stop_for_c_tagged=bool(stop["includeStopForCTagged"]),
            use_double_stop=bool(stop["useDoubleStop"]),
            dont_modify_start_atg=bool(stop["dontModifyStartAtg"]),
            show_post_stop_padding=bool(stop["showPostStopPadding"]),
            post_stop_padding=str(stop["postStopPadding"] or ""),
            post_stop_pad_up_to_nucleotide_length=(
                int(pad_target) if pad_target not in (None, "", False) else None
            ),
            only_use_n_terminal_tag_when_padding_required=bool(
                stop["onlyUseNTerminalTagWhenPaddingRequired"]
            ),
            only_use_c_terminal_tag_when_padding_required=bool(
                stop["onlyUseCTerminalTagWhenPaddingRequired"]
            ),
            min_dna_fragment_length=int(stop["minDnaFragmentLength"] or 0),
            dna_mode=bool(payload.get("dna_mode")),
            good_only=bool(payload.get("good_only")),
            order_name=str(payload.get("order_name") or ""),
            extract_chain=str(payload.get("extract_chain") or "B"),
            codon_table_id=payload.get("codon_table_id") or None,
            codon_table=CodonTable.from_dict(table_dict) if table_dict else None,
            optimization_method=str(payload.get("optimization_method") or "match_codon_usage"),
            optimization_constraints=list(
                payload.get("optimization_constraints") or [dict(c) for c in DEFAULT_TWIST_CONSTRAINTS]
            ),
            short_name=strategy,
            short_name_max_len=int(raw_sn.get("shortNameMaxLen") or 32),
        )

    def to_payload(self) -> Dict[str, Any]:
        sn = self.short_name
        return {
            "schema_version": SCHEMA_VERSION,
            "kind": KIND,
            "order_name": self.order_name,
            "extract_chain": self.extract_chain,
            "good_only": self.good_only,
            "dna_mode": self.dna_mode,
            "n_tags": [t.to_dict() for t in self.n_tags],
            "c_tags": [t.to_dict() for t in self.c_tags],
            "stop_options": {
                "includeStopForNTagged": self.include_stop_for_n_tagged,
                "includeStopForCTagged": self.include_stop_for_c_tagged,
                "useDoubleStop": self.use_double_stop,
                "dontModifyStartAtg": self.dont_modify_start_atg,
                "showPostStopPadding": self.show_post_stop_padding,
                "postStopPadding": self.post_stop_padding,
                "postStopPadUpToNucleotideLength": self.post_stop_pad_up_to_nucleotide_length,
                "onlyUseNTerminalTagWhenPaddingRequired": self.only_use_n_terminal_tag_when_padding_required,
                "onlyUseCTerminalTagWhenPaddingRequired": self.only_use_c_terminal_tag_when_padding_required,
                "minDnaFragmentLength": self.min_dna_fragment_length,
            },
            "short_name_strategy": {
                "shortNameKind": sn.kind,
                "shortNameMaxLen": self.short_name_max_len,
                "shortNameRegexPattern": sn.pattern,
                "shortNameRegexReplacement": sn.replacement,
                "shortNameRegexFlags": sn.flags,
                "shortNameSplitDelimiter": sn.delimiter,
                "shortNameSplitIndices": ",".join(str(i) for i in sn.indices),
                "shortNameSplitAddPrefix": sn.add_prefix,
                "shortNameSplitAddSuffix": sn.add_suffix,
                "shortNameSplitAddHash": sn.add_hash,
                "shortNamePatternPrefix": sn.prefix,
                "shortNamePatternUidLength": sn.uid_length,
                "shortNamePatternNumberPad": sn.number_pad,
                "shortNameSmartHashLen": sn.hash_len,
                "shortNameSmartStemIncludeHash": sn.include_hash,
                "shortNameSmartStemIncludeIndex": sn.include_index,
                "shortNameSmartStemRemoveCommonPrefix": sn.remove_common_prefix,
                "shortNameSmartStemRemoveCommonSuffix": sn.remove_common_suffix,
                "shortNameSmartStemAddPrefix": sn.add_prefix,
                "shortNameSmartStemAddSuffix": sn.add_suffix,
                "shortNameStripPrefixRegex": sn.prefix_pattern,
                "shortNameStripSuffixRegex": sn.suffix_pattern,
                "shortNameStripNewPrefix": sn.new_prefix,
            },
            "codon_table_id": self.codon_table_id,
            "codon_table": self.codon_table.to_dict() if self.codon_table else None,
            "optimization_method": self.optimization_method,
            "optimization_constraints": self.optimization_constraints,
        }

    def validation_errors(self) -> List[str]:
        from .mixed import mixed_to_dna_segments, validate_mixed_sequence

        errors: List[str] = []
        from .shortnames import validate_short_name_regex, validate_short_name_regex_strip

        for check in (validate_short_name_regex, validate_short_name_regex_strip):
            err = check(self.short_name)
            if err:
                errors.append(err)
        for tag in [*self.n_tags, *self.c_tags]:
            if tag.kind == "custom":
                err = validate_mixed_sequence(tag.sequence, f'Tag "{tag.label}"')
                if err:
                    errors.append(err)
        pad = self.post_stop_padding.strip()
        target = self.post_stop_pad_up_to_nucleotide_length
        if target is not None and target > 0:
            err = validate_mixed_sequence(pad, "Post-stop padding")
            if err:
                errors.append(err)
            dna, _ = mixed_to_dna_segments(pad, self.table(), "dna_body")
            if not dna:
                errors.append(
                    "Post-stop padding: must expand to at least one nucleotide "
                    "to pad to a target length"
                )
        return errors
