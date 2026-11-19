# Sequence preparation (development notes)

## Base52 short-name hashing

Prepare Sequences builds short names (<=32 characters by default) in the frontend (`frontend/src/stores/shortName.ts`). Several strategies embed a fixed-length base52 token from `hashBase52`. The pattern strategy uses one set-wide `uid` derived from sorted prepared DNA strings; stem, regex, and split strategies hash each row's `original_aa` (pre-tag amino acid sequence), falling back to `design_id` if empty.

### 1. Hash primitive (UTF-8, FNV-1a 64, base52)

1. Encode the input string as UTF-8 bytes.
2. Compute a 64-bit FNV-1a hash (offset basis `14695981039346656037`, prime `1099511628211`), XORing and multiplying per byte, masked to 64 bits.
3. Convert the 64-bit integer to `L` characters with `base52(value, L)` using the 52-symbol alphabet `ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz`. Each step takes `value mod 52` and integer-divides by 52, then reverses the digits so the output reads most-significant digit first at fixed width `L`.

The exported helper is:

```text
hashBase52(input: string, length: number) := base52(fnv1a64(input), length)
```

In code, `base52` clamps `L` to `1..32`. Strategies that expose "hash length" or "UID length" in the UI use `clampHashLen`, which restricts lengths to `3..10` for Prepare Sequences short names.

Changing UID or hash length adjusts how many base52 characters are emitted without changing the hash algorithm. Longer lengths include more of the 64-bit digest (fewer collisions, longer strings); shorter lengths truncate to the leading (most-significant) base52 digits of the same 64-bit value.

### 2. Pattern strategy (UID length)

In the pattern strategy, all rows in the current prepared set share the same middle token (`uid`), computed from the multiset of nucleotide strings in the set:

1. Take each row's `prepared_dna`, or `''` if DNA is not available yet.
2. Sort those strings lexicographically (`localeCompare`).
3. Join with record separator `\x1e`.
4. Compute `uid = hashBase52(joined, uidLength)` with `uidLength` clamped to `3..10`.

The `uid` changes when any row's prepared DNA changes, when rows are added or removed, or when duplicate counts of identical DNA strings change. Amino acid sequences and `design_id` are not included in the input.

The final short name is `prefix_uid_index` (optional prefix, shared `uid`, and 1-based row index with optional zero padding), truncated to the global max length.

### 3. Per-row amino acid hash strategies

These strategies compute `hashBase52(original_aa || design_id, hashLen)` with `hashLen` clamped to `3..10`:

- `Smart: stem + hash` (when "Include hash" is enabled)
- `Smart: Regex drop prefix / suffix` (suffix hash after stem)
- `Split + take indices` (when "Add hash" is enabled)

Matching `original_aa` (or `design_id`) values with the same `hashLen` generate the same hash segment; `uniqueify` in `shortName.ts` deduplicates final short names afterward.

A duplicate `design_id` in the current set triggers a "Long name not unique" warning. A duplicate pre-suffix short name triggers a "Short name not unique" warning on all rows in the colliding group, including the unsuffixed row. Both warnings appear in the warnings column and the "less than ideal" banner, and highlight the Short name panel border in red. Rows given an `_N` suffix also display the auto-dedupe warning inside that panel.

### 4. Strategy summary

| Concept | UI / field | Clamped length | `hashBase52` input |
|--------|------------|----------------|-------------------|
| Pattern uid | UID length | 3-10 | Sorted list of `prepared_dna` (empty if missing), joined with `\x1e` |
| Stem / regex / split hash | Hash length (base52) | 3-10 | `original_aa` or `design_id` if AA missing |

`computeSetFingerprint` remains in `shortName.ts` as an exported helper for other stable-set digests if needed; pattern uids do not use it.

Implementation reference: `frontend/src/stores/shortName.ts` (`fnv1a64`, `base52`, `hashBase52`, `computeShortNames`, `rawNameForRow`).
