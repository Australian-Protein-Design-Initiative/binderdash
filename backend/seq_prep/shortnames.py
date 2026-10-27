"""Twist / vendor short names: base52 FNV-1a 64-bit.

Ported from ``frontend/src/stores/shortName.ts`` with two deliberate differences,
both consequences of this being the single implementation rather than a copy:

* regex patterns and replacements use Python ``re`` syntax (``\\1``, not ``$1``),
  and ``re.sub`` replaces every match where JS ``String.replace`` without ``g``
  replaced only the first;
* sets are sorted by codepoint, not by ``localeCompare`` ICU collation, which
  disagree on mixed-case identifiers.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Set, Tuple

FNV_OFFSET = 14695981039346656037
FNV_PRIME = 1099511628211
MASK64 = (1 << 64) - 1
BASE52_ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"

_NON_NAME_CHARS = re.compile(r"[^A-Za-z0-9_-]+")
_UNDERSCORE_RUN = re.compile(r"_+")
_EDGE_UNDERSCORE = re.compile(r"^_|_$")


def fnv1a64(text: str) -> int:
    h = FNV_OFFSET
    for b in text.encode("utf-8"):
        h = ((h ^ b) * FNV_PRIME) & MASK64
    return h


def base52(n: int, length: int) -> str:
    length = max(1, min(32, length))
    v = n & MASK64
    chars: List[str] = []
    for _ in range(length):
        chars.append(BASE52_ALPHABET[v % 52])
        v //= 52
    return "".join(reversed(chars))


def hash_base52(text: str, length: int = 5) -> str:
    return base52(fnv1a64(text), length)


def sanitize_short_name_segment(raw: str) -> str:
    """Allow only ``[A-Za-z0-9_-]``; other runs collapse to one underscore."""
    t = raw.strip()
    if not t:
        return ""
    return _EDGE_UNDERSCORE.sub("", _UNDERSCORE_RUN.sub("_", _NON_NAME_CHARS.sub("_", t)))


def _clamp_hash_len(n: object) -> int:
    try:
        return max(3, min(10, int(n)))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 5


@dataclass
class ShortNameRowInput:
    row_key: str
    design_id: str
    original_aa: str = ""
    prepared_aa: str = ""
    prepared_dna: Optional[str] = None
    tag: str = ""


@dataclass
class ShortNameStrategy:
    """One flat record rather than a tagged union; ``kind`` selects the fields used."""

    kind: str = "none"
    # regex
    pattern: str = ""
    replacement: str = ""
    flags: str = ""
    # splitTake
    delimiter: str = "_"
    indices: List[int] = field(default_factory=list)
    add_prefix: str = ""
    add_suffix: str = ""
    add_hash: bool = False
    # pattern
    prefix: str = ""
    uid_length: int = 5
    number_pad: int = 0
    # smartStemHash
    include_hash: bool = True
    include_index: bool = False
    remove_common_prefix: bool = False
    remove_common_suffix: bool = True
    # smartRegexStrip
    prefix_pattern: str = ""
    suffix_pattern: str = ""
    new_prefix: str = ""
    # shared
    hash_len: int = 5


def _compile(pattern: str, flags: str = "") -> re.Pattern:
    f = 0
    if "i" in flags:
        f |= re.IGNORECASE
    if "m" in flags:
        f |= re.MULTILINE
    if "s" in flags:
        f |= re.DOTALL
    return re.compile(pattern, f)


def validate_short_name_regex(strategy: ShortNameStrategy) -> Optional[str]:
    if strategy.kind != "regex":
        return None
    try:
        _compile(strategy.pattern, strategy.flags)
    except re.error as e:
        return f"Short name regex: invalid pattern ({e})"
    return None


def validate_short_name_regex_strip(strategy: ShortNameStrategy) -> Optional[str]:
    if strategy.kind != "smartRegexStrip":
        return None
    pre = (strategy.prefix_pattern or "").strip()
    suf = (strategy.suffix_pattern or "").strip()
    if not pre and not suf:
        return "Short name: enter at least one of prefix regex or suffix regex"
    for label, pat in (("prefix", pre), ("suffix", suf)):
        if not pat:
            continue
        try:
            re.compile(pat)
        except re.error as e:
            return f"Short name {label} regex: invalid ({e})"
    return None


def _longest_common_prefix_length(strings: Sequence[str]) -> int:
    if len(strings) < 2:
        return 0
    n = 0
    first = strings[0]
    while n < len(first) and all(n < len(s) and s[n] == first[n] for s in strings[1:]):
        n += 1
    return n


def _longest_common_suffix_length(strings: Sequence[str]) -> int:
    if len(strings) < 2:
        return 0
    n = 0
    min_len = min(len(s) for s in strings)
    first = strings[0]
    while n < min_len and all(s[len(s) - 1 - n] == first[len(first) - 1 - n] for s in strings[1:]):
        n += 1
    return n


def compute_smart_stem_affix_strip(
    rows: Sequence[ShortNameRowInput], strategy: ShortNameStrategy
) -> Optional[Tuple[int, int]]:
    """Longest prefix/suffix shared by every ``design_id``; needs at least 2 rows."""
    if strategy.kind != "smartStemHash" or len(rows) < 2:
        return None
    ids = [r.design_id for r in rows]
    lcp = _longest_common_prefix_length(ids) if strategy.remove_common_prefix else 0
    lcs = _longest_common_suffix_length(ids) if strategy.remove_common_suffix else 0
    if lcp == 0 and lcs == 0:
        return None
    return lcp, lcs


def _compute_pattern_set_uid(rows: Sequence[ShortNameRowInput], uid_length: int) -> str:
    uid_len = _clamp_hash_len(uid_length or 5)
    nt = sorted((r.prepared_dna or "") for r in rows)
    return hash_base52("\x1e".join(nt), uid_len)


def _raw_name_for_row(
    row: ShortNameRowInput,
    index: int,
    strategy: ShortNameStrategy,
    rows: Sequence[ShortNameRowInput],
    max_len: int,
    affix_strip: Optional[Tuple[int, int]] = None,
    pattern_set_uid: Optional[str] = None,
) -> str:
    design_id = row.design_id
    hash_input = row.original_aa or design_id
    kind = strategy.kind

    if kind == "none":
        return design_id

    if kind == "regex":
        try:
            return _compile(strategy.pattern, strategy.flags).sub(
                strategy.replacement or "", design_id
            )
        except re.error:
            return design_id

    if kind == "splitTake":
        delim = strategy.delimiter or "_"
        parts = design_id.split(delim)
        picked = [parts[i - 1] for i in strategy.indices if 0 < i <= len(parts)]
        stem = delim.join(picked) if picked else design_id
        ap = sanitize_short_name_segment((strategy.add_prefix or "").strip())
        as_ = sanitize_short_name_segment((strategy.add_suffix or "").strip())
        if ap:
            stem = f"{ap}_{stem}" if stem else ap
        if as_:
            stem = f"{stem}_{as_}" if stem else as_
        if not strategy.add_hash:
            return stem
        h = hash_base52(hash_input, _clamp_hash_len(strategy.hash_len))
        max_stem = max(1, max_len - 1 - len(h))
        return f"{stem[:max_stem]}_{h}"

    if kind == "pattern":
        uid_len = _clamp_hash_len(strategy.uid_length or 5)
        pad = max(0, min(6, int(strategy.number_pad or 0)))
        uid = pattern_set_uid or _compute_pattern_set_uid(rows, uid_len)
        num = str(index + 1).rjust(pad, "0") if pad > 0 else str(index + 1)
        pfx = sanitize_short_name_segment((strategy.prefix or "").strip())
        raw = f"{pfx}_{uid}_{num}" if pfx else f"{uid}_{num}"
        return raw[:max_len]

    if kind == "smartStemHash":
        id_for_stem = design_id
        if affix_strip:
            lcp, lcs = affix_strip
            if lcp > 0:
                id_for_stem = id_for_stem[lcp:]
            if lcs > 0:
                id_for_stem = id_for_stem[: max(0, len(id_for_stem) - lcs)]
        stem = sanitize_short_name_segment(id_for_stem)
        ap = sanitize_short_name_segment((strategy.add_prefix or "").strip())
        as_ = sanitize_short_name_segment((strategy.add_suffix or "").strip())
        if ap:
            stem = f"{ap}_{stem}" if stem else ap
        if as_:
            stem = f"{stem}_{as_}" if stem else as_
        num = str(index + 1) if strategy.include_index else ""
        if not strategy.include_hash:
            tail = f"_{num}" if num else ""
            max_stem = max(1, max_len - len(tail)) if tail else max_len
            return stem[:max_stem] + tail
        h = hash_base52(hash_input, _clamp_hash_len(strategy.hash_len))
        tail = f"_{h}_{num}" if num else f"_{h}"
        return stem[: max(1, max_len - len(tail))] + tail

    if kind == "smartRegexStrip":
        h = hash_base52(hash_input, _clamp_hash_len(strategy.hash_len))
        s = design_id
        pre = (strategy.prefix_pattern or "").strip()
        if pre:
            try:
                s = re.sub(pre, "", s)
            except re.error:
                s = design_id
        suf = (strategy.suffix_pattern or "").strip()
        if suf:
            try:
                s = re.sub(suf, "", s)
            except re.error:
                pass
        dropped = sanitize_short_name_segment(s)
        custom = sanitize_short_name_segment(strategy.new_prefix or "")
        if custom:
            stem = f"{custom}_{dropped}" if dropped else custom
        else:
            stem = dropped
        if not stem:
            return h
        return f"{stem[: max(1, max_len - 1 - len(h))]}_{h}"

    return design_id


def _normalized_base(raw: str, max_len: int) -> str:
    base = sanitize_short_name_segment(raw)[:max_len]
    return (base or "x")[:max_len]


def _uniqueify(raw: str, max_len: int, used: Set[str]) -> Tuple[str, bool]:
    candidate = _normalized_base(raw, max_len)
    if candidate not in used:
        used.add(candidate)
        return candidate, False
    n = 2
    while True:
        suffix = f"_{n}"
        stem = sanitize_short_name_segment(raw)
        while len(stem) + len(suffix) > max_len and stem:
            stem = stem[:-1]
        candidate = ((stem or "x") + suffix)[:max_len]
        if candidate not in used:
            used.add(candidate)
            return candidate, True
        n += 1
        if n > 999999:
            # Unreachable for any real set; keeps the loop total.
            candidate = hash_base52(f"{raw}\x1f{n}", min(8, max_len))
            if candidate not in used:
                used.add(candidate)
                return candidate, True


@dataclass
class ShortNameResult:
    names: Dict[str, str]
    dedupe_count: int
    non_unique_row_keys: Set[str]


def compute_short_names(
    rows: Sequence[ShortNameRowInput], strategy: ShortNameStrategy, max_len: int
) -> ShortNameResult:
    cap = max(8, min(64, max_len))
    affix_strip = compute_smart_stem_affix_strip(rows, strategy)
    pattern_uid = (
        _compute_pattern_set_uid(rows, strategy.uid_length or 5)
        if strategy.kind == "pattern"
        else None
    )
    raws = [
        _raw_name_for_row(row, i, strategy, rows, cap, affix_strip, pattern_uid)
        for i, row in enumerate(rows)
    ]
    bases = [_normalized_base(r, cap) for r in raws]
    base_counts: Dict[str, int] = {}
    for b in bases:
        base_counts[b] = base_counts.get(b, 0) + 1

    used: Set[str] = set()
    names: Dict[str, str] = {}
    non_unique: Set[str] = set()
    dedupe_count = 0
    for i, row in enumerate(rows):
        name, deduped = _uniqueify(raws[i], cap, used)
        if deduped:
            dedupe_count += 1
        if deduped or base_counts.get(bases[i], 0) > 1:
            non_unique.add(row.row_key)
        names[row.row_key] = name
    return ShortNameResult(names, dedupe_count, non_unique)
