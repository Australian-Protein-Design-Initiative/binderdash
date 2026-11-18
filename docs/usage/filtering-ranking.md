# Filtering and ranking

The **Filtering** tab works on the runs picked in **Select Runs**. Those runs are pooled into one table. An **Available Metrics** panel (collapsed by default) lists every column in that pool: its canonical name, which methods have it, the raw column each method uses, and the min–max range.

Below that are six numbered sections. Hard filters and target contacts narrow the Designs table as you edit them. Ranking annotates every design with a rank and leaves the visible set as it is. Diversity selection, once applied and left on, narrows the table further. A Saved Set freezes the result on the server.

The in-progress recipe (filters, ranking metrics, budget, alpha, size buckets, diversity on/off) is stored in the browser (IndexedDB). A Saved Set is a separate server-side snapshot. See [Storage architecture](../development/storage.md).

REST shapes for the same pipeline are in [Filtering, ranking, and diversity selection](../development/api.md#filtering-ranking-and-diversity-selection).

## 1. Hard Filters

Every enabled filter must pass for a design to count as passing. Edits apply on a short debounce and update the Designs table and the [filter cascade](#5-filter-cascade). The status line shows how many designs pass. **Disable all filters** turns every row off without deleting it; a disabled row is kept in the list and ignored.

Each row is a column, an operator, and a value:

| Column kind | Operators | Value |
| --- | --- | --- |
| Numeric | `<`, `≤`, `>`, `≥` | threshold |
| Text | contains, does not contain, starts with, ends with, equals, not equals, regex | text |
| Either | is empty, is not empty | none |
| Good | good, bad, unrated | none |

Contains, starts with, and ends with are case-insensitive. Equals, not equals, and regex are case-sensitive. A null or blank value passes a "does not contain" / "not equals" check.

The column picker offers canonical metric names (`iptm`, `ptm`, `rmsd`, `pae_interaction`, `hbonds`, `saltbridge`, `delta_sasa`) and raw columns, plus `design_id`, `project_id`, `run_name`, `method`, and `Sequence`, and the user-set columns **Good** and **Tag**. Good is the thumbs rating: **good**, **bad**, or **unrated** (designs never marked). Tag is the N- or C-terminus choice (`N`, `C`, or empty). Both stay in the picker when no design has been rated or tagged yet. A canonical name is resolved per design from that design's method (`iptm` is `design_to_target_iptm` on BoltzGen, `Average_i_pTM` on BindCraft, `iptm` on RFdiffusion3, and `boltz_iptm` on RFdiffusion when a Boltz pulldown column is present). The mapping is `METRIC_ALIASES` in `backend/filtering/metrics.py`.

Canonical score metrics also carry a known direction in `METRIC_DIRECTIONS` (same module): higher-is-better metrics such as `iptm` default a new hard filter to `>`, and lower-is-better metrics such as `rmsd` / `pae_interaction` default to `<`. Adding or changing a ranking metric row sets the "Higher is better" checkbox from the same source. Unknown raw columns keep the previous defaults (`<` / higher-is-better). The columns API returns `higher_is_better` on each entry so the UI does not hardcode the map.

A design whose method has no equivalent for a canonical metric is exempt from that filter. A design whose method has the metric, but whose value is null, fails it. A filter on a literal column name that is absent fails every row. **Good** and **Tag** are the exception: until a design is rated or tagged the column is missing, and that counts as unrated or empty rather than a failure.

Per-replicate BindCraft columns (`1_pLDDT`, `2_i_pTM`, …) are omitted from the picker. They repeat the `Average_*` aggregates.

Passing filters is what narrows the table. Failing a filter still leaves the design in the ranked pool used by [section 3](#3-ranking-metrics-quality-score): the failure lowers its rank, and diversity selection and Saved Sets skip it.

## 2. Target contacts

Target-contact conditions are extra hard filters, evaluated from each design's structure rather than from a results-table column. They require a design to approach, avoid, bury, or expose chosen residues on the target. They apply alongside section 1, on the same debounce, and count toward "designs passing" and toward the filter-pass count used in ranking.

**Compute target contacts** parses the structures in the current run selection and caches a per-residue record. The coverage line shows how many designs already have a record. A design with no record fails every condition. Residues are only stored when they fall within 12 Å of the binder, so a distance threshold above 12 Å cannot be answered and the value field stops there.

Runs are grouped into targets by target sequence, so one target can span runs that letter the chain differently. With a single target the residue list is shown directly. With more than one, each group names its target and only applies to that target's runs; a design from another run is exempt from the group. A group whose target is no longer in the selection matches nothing until you pick a target that is in scope (that clears the residue chips) or remove the group.

A condition is: residues, a comparison, a number, a qualifier, and a scope.

| Comparison | Meaning |
| --- | --- |
| within X of binder | closest approach ≤ X |
| further than X from binder | closest approach > X |
| SASA when bound ≤ / ≥ | solvent-accessible surface of the residue in the complex |
| ΔSASA on binding ≥ / ≤ | drop in that surface on binding |

Distance uses heavy atoms, Cα, or Cβ. SASA and ΔSASA are in Å², or as a percent of that residue's theoretical maximum (Tien et al. 2013).

| Scope | Passes when |
| --- | --- |
| any residue | at least one listed residue meets the comparison |
| all residues | every listed residue that could be evaluated meets it |
| at least N | at least N listed residues meet it |
| site total | the metric, summed over the residues and expressed as a percent of their combined maximum surface, meets the comparison |

Site total applies to SASA and ΔSASA. Distance has no site total. A residue the target does not have is skipped. If none of the listed residues can be evaluated, the condition passes. If the target chain moves between designs in a run, unbound SASA is computed per design; otherwise it is computed once per run.

## 3. Ranking Metrics (Quality Score)

The **Mode** menu chooses how the metric list becomes one order. A fresh session uses **Simple ranking**.

| Mode | What the list means |
| --- | --- |
| Simple ranking | The first enabled metric is the primary key, the next breaks ties, and so on. Each row is labelled 1st, 2nd, 3rd. Weights are not used. |
| Weighted-Worst-Rank-Across-Metrics (Boltzgen-style) | Each metric is ranked, the rank is divided by that metric's weight, and the **worst** of those scaled ranks is the design's score. |

Both modes rank a design that passed more filters ahead of one that passed fewer, and both leave failing designs in the table. **Apply Ranking** calls `POST /api/filtering/rank`, then adds a **Ranking** column (`binderdash_ranking`, 1 = best) as the first data column of the Designs table and sorts that table by it, ascending. Doing this again — or applying diversity, which recomputes the same ranks — puts that column back in front and re-sorts, even if it had been hidden or moved. The set of visible rows stays whatever sections 1, 2, and 4 have already decided.

The preset menu lists recipes for the current mode and replaces the metric list. Editing a row afterwards clears the preset selection, because the list no longer matches a preset exactly.

A fresh session loads **ipTM + Binder pLDDT + Binder RMSD**:

| Priority | Metric | Direction | Resolves to |
| --- | --- | --- | --- |
| 1st | `iptm` | higher | BoltzGen `design_to_target_iptm`, BindCraft `Average_i_pTM`, RFdiffusion3 `iptm`, RFdiffusion `boltz_iptm` |
| 2nd | `binder_plddt` | higher | BindCraft `Average_Binder_pLDDT`, RFdiffusion `plddt_binder` (else `plddt`), BoltzGen `complex_plddt` or `design_plddt` when present, RFdiffusion3 `plddt` |
| 3rd | `rmsd` | lower | BoltzGen `bb_rmsd`, RFdiffusion `rmsd`, RFdiffusion3 `rf3_rmsd_target_aligned_binder_rmsd_all`, BindCraft `Average_Binder_RMSD` |

`binder_plddt` is binder-chain confidence. BoltzGen's final metrics table often has no pLDDT column; that row is then skipped and the panel warns.

**ipSAE + Binder pLDDT + Binder RMSD** uses the same second and third keys, with `ipsae` (higher is better) first. That name resolves to BoltzGen `design_ipsae_min` and RFdiffusion3 `rf3_ipsae_min`. BindCraft and plain RFdiffusion have no ipSAE column, so that row is skipped and the panel warns. **iptm only** is the other simple-ranking preset.

### Weighted worst rank (BoltzGen-style)

In this mode a design is only as good as its weakest metric. For each enabled metric the engine ranks every design, divides that rank by the metric's weight, and keeps the worst (largest) of those numbers. A design that is excellent on one metric and poor on another is scored by the poor one.

| Preset | Metrics |
| --- | --- |
| BoltzGen defaults | the six metrics in the table below |
| iptm only | `iptm` at weight 1, higher is better |

**BoltzGen defaults** reproduces BoltzGen's own `Filter` recipe (`from_inverse_folded=True`, `use_affinity=False`), written with Binderdash canonical names so the same preset can run on other methods that have an equivalent column. BoltzGen stores interaction PAE already negated (`neg_min_design_to_target_pae`); here the raw PAE is used and **Higher is better** is off.

| Metric | BoltzGen column | Also resolves to | Weight | Direction |
| --- | --- | --- | --- | --- |
| `iptm` | `design_to_target_iptm` | BindCraft `Average_i_pTM`, RFdiffusion3 `iptm`, RFdiffusion `boltz_iptm` | 1 | higher |
| `ptm` | `design_ptm` | BindCraft `Average_pTM`, RFdiffusion3 `ptm` | 1 | higher |
| `pae_interaction` | `interaction_pae` | RFdiffusion `pae_interaction`, RFdiffusion3 `pair_pae`, BindCraft `Average_i_pAE` | 1 | lower |
| `hbonds` | `plip_hbonds_refolded` | BindCraft `Average_n_InterfaceHbonds` | 2 | higher |
| `saltbridge` | `plip_saltbridge_refolded` | BoltzGen only | 2 | higher |
| `delta_sasa` | `delta_sasa_refolded` | BindCraft `Average_dSASA` | 2 | higher |

`delta_sasa` is the pipeline's own buried-surface column. Binderdash's independently computed `binderdash_delta_sasa` (as-generated structure, any method) is a different column and is not part of this preset.

A metric that resolves to no non-null value for the selected runs is skipped, and the panel warns. That is what happens to `saltbridge` on a non-BoltzGen selection. A disabled row is kept in the list and omitted from the request. Weight 0 is also omitted; the field in the UI starts at 0.01.

### Per-metric rank (weighted worst rank)

Hard filters and target contacts are applied first as annotations. Each design gets `num_filters_passed` (how many enabled filters it passed) and `pass_filters` (whether it passed all of them). Rows stay in the table.

For each enabled metric the engine then:

1. Resolves a canonical name per row, the same way filters do. A method with no equivalent contributes a null. A raw column that exists is used as-is. A metric that matches nothing in the pool is skipped.
2. Negates the value when **Higher is better** is off, so a larger number is always better.
3. Ranks every design on the pair `(num_filters_passed, value)`, best first. Passing more filters outranks passing fewer, whatever the metric value is. Among designs with the same pass count, the better value wins. Ties share the best rank in the tie (two designs tied for 2nd are both rank 2; the next is 4). A null value sorts last on that metric.
4. Divides that rank by the metric's weight.

Weight is inverse importance. Dividing by a larger weight shrinks that metric's rank number, so it is less likely to be the worst one and less likely to decide the design's place. BoltzGen's interface counts (hydrogen bonds, salt bridges, ΔSASA) use weight 2 for this reason: a mediocre hydrogen-bond count hurts half as much as a mediocre ipTM, which stays at weight 1.

### Combining metrics

The design's score key, `max_rank`, is the maximum of those scaled ranks — its worst metric. Designs are ordered by `max_rank` ascending (smaller is better). When two designs share the same worst rank, the tie breaks on the first available of `design_to_target_iptm`, `iptm`, or `Average_i_pTM`, higher first.

`final_rank` is 1…N in that order. That is the **Ranking** column. `quality_score` stretches the same order onto 1 (best) … 0 (worst); [diversity selection](#4-diversity-selection) uses it, and the Designs table does not show it.

With four designs, no filters, and two metrics at weight 1:

| Design | ipTM rank | RMSD rank | worst (`max_rank`) |
| --- | --- | --- | --- |
| A | 1 | 1 | 1 |
| D | 3 | 3 | 3 |
| B | 2 | 4 | 4 |
| C | 4 | 2 | 4 |

A is best on both metrics, so it ranks first. B and C each have a worst rank of 4; the ipTM tie-break then prefers B. Raising RMSD's weight to 2 turns B's RMSD rank of 4 into 2, so B's worst rank becomes 2 and B moves up.

A design that fails a hard filter ranks below every design that passed more filters, even when its metric values are better. Diversity selection and Saved Sets still omit that design: eligibility there is `pass_filters`, while the rank column covers the whole pool.

## 4. Diversity Selection

Diversity selection picks a subset of the designs that passed every hard filter and target-contact condition. The objective for each candidate is

```text
(1 − α) × quality_score + α × (1 − similarity to the closest design already picked)
```

Similarity is pairwise sequence identity from a Biopython global alignment, divided by the longer sequence (the same normalisation BoltzGen uses). The first pick is the highest `quality_score`. Later picks use a lazy-greedy loop: a candidate's gain is recomputed against the whole set so far, and it is accepted only when it is still the best pending candidate.

The section is off by default. While it is off, **Create Saved Set** keeps every design that passed the filters, and budget is ignored. Turning it on does not run the selection. **Apply Diversity Filter** does; pairwise alignment is slow, so it is a deliberate click. After a successful apply the Designs table shows only the diverse subset and is sorted by **Ranking**.

Changing budget, α, the size buckets, or the ranking metrics and mode after an apply marks the panel **Unapplied** and puts the table back to the hard-filter set until you apply again. **Apply Diversity Filter** re-ranks with the current metrics before it selects, and updates the Ranking column. Turning the section off does the same, and keeps the last diverse subset cached so turning it back on (with unchanged settings) restores it without another alignment pass. The same on/off state is the Diversity row in the [filter cascade](#5-filter-cascade).

| Control | Default | Effect |
| --- | --- | --- |
| Budget | 24 | Maximum number of designs in the subset. If fewer designs pass with a usable sequence, the subset is smaller and the result says why. |
| α | 0 | 0 is quality only, 1 is diversity only. The slider is logarithmic from 0.0001 to 1 because the useful range sits near zero. The number field accepts an exact value, including 0. BoltzGen uses 0.001 for proteins and 0.01 for its peptide-anything protocol; those stay as slider marks. |
| Size buckets | none | Optional caps. A bucket `{min, max, num_designs}` allows at most `num_designs` selections whose sequence length is in `[min, max)`. |

Designs with a missing or blank sequence are left out of the pool. A blank sequence would look maximally dissimilar to everything, so including it would prefer the designs the selector knows least about. If the runs have no `Sequence` column at all, selection is skipped until sequences are extracted (`POST /api/sequences/extract`).

**Keep only best MPNN variant per backbone** sits above Budget. While diversity selection is on, designs that share a `backbone_id` collapse to the one with the best primary score, and designs with no `backbone_id` are kept. That collapse runs **before** diversity selection: the budget is spent on distinct backbones, not on several MPNN variants of one backbone. Turning diversity selection off leaves the checkbox as it was but stops the collapse, and a Saved Set created with diversity off still keeps every design that passed the hard filters. The [filter cascade](#5-filter-cascade) lists it as **Remove MPNN duplicates**, above Diversity Selection, with the number of designs left after the collapse. Changing the checkbox after an apply marks diversity **Unapplied** until you apply again.

## 5. Filter cascade

The cascade is the sequential count of designs remaining after each enabled stage. It refreshes on the same debounce as hard filters and target contacts.

Rows appear in order: each hard filter, then each target-contact condition, then **Remove MPNN duplicates** when **Keep only best MPNN variant per backbone** is collapsing the table, then Diversity Selection when that section is on or has a cached result, then a **Final set** row. Disabled filters stay in the list with no remaining count. The final count is the last stage that actually narrowed the set: the diverse subset when diversity is on and applied, otherwise the count after MPNN duplicate removal when that option is active, otherwise the last enabled filter, otherwise the unfiltered total.

While diversity is on but not yet applied, the cascade says so. If MPNN duplicate removal is also on, the final count is the hard-filter set after that collapse; otherwise it stays at the hard-filter total. While diversity is off, MPNN duplicate removal does not run and the final set is every design that passes the hard filters and target contacts.

## 6. Create Saved Set

**Create Saved Set** runs the same filter → rank → (best MPNN variant, when that option is on) → diversity pipeline and stores an immutable snapshot: the source run ids, the recipe, a result summary, the designs that made the cut (with `final_rank`, `quality_score`, and whether each was in the diverse subset), and the UI state at save time (table columns, sort, and **Keep only best MPNN variant per backbone**). **Reapply filters** / **Load filters** restore that UI state along with the recipe.

With diversity on, the set is the diverse subset (at most Budget, and only designs that passed every filter and have a sequence). With diversity off, the set is every design that passed the filters. The confirmation line reports designs selected, how many passed the filters, and the total input.

Sets are visible to every user of the same server and survive a browser reset. Rename and delete are the later mutations; reapplying filters builds a new set. Open the result under **Saved Sets**. Download is the standard design bundle (ranked rows, structures, and the UI state the set was saved with); see [Download bundles](../development/download-bundles.md).
