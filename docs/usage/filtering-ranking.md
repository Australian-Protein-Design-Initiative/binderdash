# Filtering and ranking

The **Filtering** tab combines all runs selected in **Select Runs** into a single table. Expand the **Available Metrics** panel to inspect every column in the selection, including its canonical name, supporting methods, method-specific raw column names, and min-max range.

Use the six numbered sections below it to narrow and order your designs. Hard filters and target contacts filter the Designs table as you edit them. Ranking adds a rank column to all designs without hiding rows. Diversity selection narrows the table further when enabled and applied, and Saved Sets store a fixed snapshot on the server.

The in-progress recipe (filters, ranking metrics, budget, alpha, size buckets, diversity on/off) is stored in the browser (IndexedDB). A Saved Set is a separate server-side snapshot. See [Storage architecture](../development/storage.md).

For the REST API schemas, see [Filtering, ranking, and diversity selection](../development/api.md#filtering-ranking-and-diversity-selection).

## 1. Hard Filters

A design must pass all enabled filters to remain visible. Edits apply automatically after a short debounce, updating both the Designs table and the [filter cascade](#5-filter-cascade). The status line displays the passing count. Click **Disable all filters** to turn off every row without deleting your rules; disabled rows stay in the list but are ignored.

Each filter row specifies a column, an operator, and a threshold or value:

| Column kind | Operators | Value |
| --- | --- | --- |
| Numeric | `<`, `≤`, `>`, `≥` | threshold |
| Text | contains, does not contain, starts with, ends with, equals, not equals, regex | text |
| Either | is empty, is not empty | none |
| Good | good, bad, unrated | none |

Text matching for "contains", "starts with", and "ends with" is case-insensitive; "equals", "not equals", and "regex" are case-sensitive. Null or blank values pass "does not contain" and "not equals" filters.

The column picker includes canonical metric names (`iptm`, `ptm`, `rmsd`, `pae_interaction`, `hbonds`, `saltbridge`, `delta_sasa`), raw columns, metadata fields (`design_id`, `project_id`, `run_name`, `method`, `Sequence`), and user-set columns (**Good** and **Tag**). **Good** stores the thumbs rating (**good**, **bad**, or **unrated**), and **Tag** stores the terminus choice (`N`, `C`, or empty); both appear in the picker even before you rate or tag any designs. Canonical names map to each method's corresponding column via `METRIC_ALIASES` in `backend/filtering/metrics.py` (for example, `iptm` maps to `design_to_target_iptm` for BoltzGen, `Average_i_pTM` for BindCraft, `iptm` for RFdiffusion3, and `boltz_iptm` for RFdiffusion when a Boltz pulldown column exists).

`METRIC_DIRECTIONS` in the same module defines default directions for canonical score metrics. Higher-is-better metrics like `iptm` default new hard filters to `>`, while lower-is-better metrics like `rmsd` and `pae_interaction` default to `<`. Adding or changing a ranking metric sets the "Higher is better" checkbox from the same map. Unrecognised raw columns keep the default (`<` for filters, higher-is-better for ranking). The columns API includes `higher_is_better` on each entry so the UI reads these defaults dynamically.

If a design's method has no equivalent column for a canonical metric, that design skips the filter. If the method defines the metric but the design's value is null, the design fails the filter. Filtering on a missing raw column name fails all rows. As an exception, missing **Good** and **Tag** values are treated as unrated or empty instead of failing.

Per-replicate BindCraft columns (`1_pLDDT`, `2_i_pTM`, ...) are omitted from the picker because they duplicate the `Average_*` aggregates.

Only passing designs appear in the Designs table, but failing designs remain in the ranking pool ([section 3](#3-ranking-metrics-quality-score)) with a lower rank. Diversity selection and Saved Sets exclude failing designs.

## 2. Target contacts

Target-contact conditions act as additional hard filters computed directly from each design's 3D structure instead of table columns. Use them to require designs to contact, avoid, bury, or expose specific target residues. They apply on the same debounce as section 1 and count toward both the passing total and the filter-pass count used during ranking.

Click **Compute target contacts** to parse structures in the selected runs and cache per-residue contact data. The coverage line reports how many designs have cached data; designs without cached contact data fail all target-contact conditions. Contact caching only records residues within 12 Å of the binder, so the distance threshold input caps at 12 Å.

Binderdash groups runs by target sequence, allowing one target to span runs with different chain IDs. When only one target is present, the residue picker appears directly. With multiple targets, each condition group specifies one target and applies only to runs matching that target (designs from other targets skip the group). If you deselect a group's target run, that group matches zero designs until you remove it or select an active target (which clears the selected residue chips).

Each condition combines target residues, a comparison operator, a numeric threshold, a measurement qualifier, and a scope.

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

The "site total" scope applies only to SASA and ΔSASA, not distance. Listed residues absent from the target sequence are skipped, and if no listed residues exist on the target, the condition passes. Unbound SASA is computed once per run when the target chain coordinates stay fixed, or per design if the target chain moves between designs.

## 3. Ranking Metrics (Quality Score)

Select a **Mode** to control how the metric list orders designs. New sessions default to **Simple ranking**.

| Mode | Metric ordering |
| --- | --- |
| Simple ranking | The first enabled metric is the primary key, the next breaks ties, and so on. Each row is labelled 1st, 2nd, 3rd. Weights are not used. |
| Weighted-Worst-Rank-Across-Metrics (Boltzgen-style) | Each metric is ranked, the rank is divided by that metric's weight, and the **worst** of those scaled ranks is the design's score. |

In both modes, designs passing more filters always rank above designs passing fewer, and failing designs remain in the table. Clicking **Apply Ranking** calls `POST /api/filtering/rank`, inserts the **Ranking** column (`binderdash_ranking`, 1 = best) as the first data column of the Designs table, and sorts ascending. Re-applying ranking (or running diversity selection, which recomputes ranks) moves the Ranking column back to the front and re-sorts even if you hid or reordered it. Ranking does not change which rows are visible.

Choosing a preset replaces the current metric list with a predefined recipe for the active mode. Modifying any row clears the preset dropdown selection.

New sessions start with the **ipTM + Binder pLDDT + Binder RMSD** preset:

| Priority | Metric | Direction | Resolves to |
| --- | --- | --- | --- |
| 1st | `iptm` | higher | BoltzGen `design_to_target_iptm`, BindCraft `Average_i_pTM`, RFdiffusion3 `iptm`, RFdiffusion `boltz_iptm` |
| 2nd | `binder_plddt` | higher | BindCraft `Average_Binder_pLDDT`, RFdiffusion `plddt_binder` (else `plddt`), BoltzGen `complex_plddt` or `design_plddt` when present, RFdiffusion3 `plddt` |
| 3rd | `rmsd` | lower | BoltzGen `bb_rmsd`, RFdiffusion `rmsd`, RFdiffusion3 `rf3_rmsd_target_aligned_binder_rmsd_all`, BindCraft `Average_Binder_RMSD` |

`binder_plddt` measures binder-chain confidence. Because BoltzGen final metrics tables often omit pLDDT, Binderdash skips that row and displays a warning.

The **ipSAE + Binder pLDDT + Binder RMSD** preset replaces the primary key with `ipsae` (higher is better), which maps to `design_ipsae_min` in BoltzGen and `rf3_ipsae_min` in RFdiffusion3. BindCraft and standard RFdiffusion lack an ipSAE column, so that row is skipped with a warning. Simple ranking also includes an **iptm only** preset.

### Weighted worst rank (BoltzGen-style)

Weighted worst rank scores each design by its weakest metric. For every enabled metric, Binderdash ranks all designs, divides each rank by the metric's weight, and takes the largest (worst) scaled rank. Strong performance on one metric does not offset a poor score on another.

| Preset | Metrics |
| --- | --- |
| BoltzGen defaults | the six metrics in the table below |
| iptm only | `iptm` at weight 1, higher is better |

**BoltzGen defaults** mirrors BoltzGen's `Filter` recipe (`from_inverse_folded=True`, `use_affinity=False`) using canonical names so it works across other methods with matching columns. Instead of BoltzGen's negated `neg_min_design_to_target_pae`, Binderdash uses raw interaction PAE with **Higher is better** unchecked.

| Metric | BoltzGen column | Also resolves to | Weight | Direction |
| --- | --- | --- | --- | --- |
| `iptm` | `design_to_target_iptm` | BindCraft `Average_i_pTM`, RFdiffusion3 `iptm`, RFdiffusion `boltz_iptm` | 1 | higher |
| `ptm` | `design_ptm` | BindCraft `Average_pTM`, RFdiffusion3 `ptm` | 1 | higher |
| `pae_interaction` | `interaction_pae` | RFdiffusion `pae_interaction`, RFdiffusion3 `pair_pae`, BindCraft `Average_i_pAE` | 1 | lower |
| `hbonds` | `plip_hbonds_refolded` | BindCraft `Average_n_InterfaceHbonds` | 2 | higher |
| `saltbridge` | `plip_saltbridge_refolded` | BoltzGen only | 2 | higher |
| `delta_sasa` | `delta_sasa_refolded` | BindCraft `Average_dSASA` | 2 | higher |

`delta_sasa` refers to the design pipeline's reported buried-surface column, not Binderdash's own `binderdash_delta_sasa` column (computed from as-generated structures).

If an enabled metric has no non-null values in the selected runs (such as `saltbridge` outside BoltzGen), Binderdash skips it and shows a warning. Disabled rows and rows with weight `0` are omitted from the ranking request (the UI weight input starts at `0.01`).

### Per-metric rank (weighted worst rank)

Hard filters and target contacts are evaluated first as annotations, adding `num_filters_passed` (count of enabled filters passed) and `pass_filters` (whether all enabled filters passed) without removing rows.

For each enabled metric, the ranking engine:

1. Maps canonical names per row using the same aliases as filters (methods without an equivalent yield null). Existing raw columns are used directly, and metrics with no values in the pool are skipped.
2. Negates values when **Higher is better** is unchecked so larger numbers always rank higher.
3. Ranks all designs by `(num_filters_passed, value)` descending. Designs passing more filters always rank ahead of those passing fewer. Ties share the top rank (two designs tied for 2nd both get rank 2, and the next gets rank 4), and null values sort last.
4. Divides each rank by the metric's weight.

Weights represent inverse importance: dividing by a larger weight lowers the scaled rank, reducing how strongly that metric affects the final order. BoltzGen's interface metrics (hydrogen bonds, salt bridges, ΔSASA) use weight 2 so a weak interface count penalises a design half as much as a weak ipTM (weight 1).

### Combining metrics

Each design's score key, `max_rank`, is the maximum of its scaled ranks across enabled metrics. Binderdash orders designs by `max_rank` ascending (lower is better). Ties break using the first available column among `design_to_target_iptm`, `iptm`, or `Average_i_pTM` (higher is better).

`final_rank` assigns 1...N in that order and populates the **Ranking** column. `quality_score` normalises the same order to 1 (best) ... 0 (worst) for [diversity selection](#4-diversity-selection) and is hidden from the Designs table.

Example with four designs, no filters, and two metrics at weight 1:

| Design | ipTM rank | RMSD rank | worst (`max_rank`) |
| --- | --- | --- | --- |
| A | 1 | 1 | 1 |
| D | 3 | 3 | 3 |
| B | 2 | 4 | 4 |
| C | 4 | 2 | 4 |

Design A ranks first on both metrics. Designs B and C tie with a `max_rank` of 4, and the ipTM tie-break puts B ahead of C. Increasing the RMSD weight to 2 scales B's RMSD rank from 4 to 2, lowering B's `max_rank` to 2 and moving B above D.

Designs that fail a hard filter always rank below designs passing more filters, regardless of metric scores. Diversity selection and Saved Sets require `pass_filters` and exclude failing designs, whereas the Ranking column scores the full pool.

## 4. Diversity Selection

Diversity selection chooses a subset from designs that passed all hard filters and target-contact conditions, maximising:

```text
(1 − α) × quality_score + α × (1 − similarity to the closest design already picked)
```

Pairwise similarity is sequence identity from a Biopython global alignment divided by the length of the longer sequence (matching BoltzGen's normalisation). Selection starts with the highest `quality_score`, then runs a lazy-greedy loop that recomputes each candidate's marginal gain against all previously selected designs and accepts it once it remains the top candidate.

Diversity selection is off by default; while off, **Create Saved Set** includes all filter-passing designs and ignores the budget. Enabling the section does not run alignment automatically. Click **Apply Diversity Filter** to run selection (explicitly triggered because pairwise alignment can be slow). Once applied, the Designs table displays only the selected subset, sorted by **Ranking**.

Editing the budget, α, size buckets, or ranking configuration after applying marks the section **Unapplied** and reverts the table to the hard-filter set until you apply again. Clicking **Apply Diversity Filter** re-runs ranking with the current metrics before selecting and updates the Ranking column. Toggling the section off also reverts the table while caching the last result, so turning it back on with unchanged settings restores the subset without recomputing alignments. The Diversity row in the [filter cascade](#5-filter-cascade) mirrors this toggle state.

| Control | Default | Effect |
| --- | --- | --- |
| Budget | 24 | Maximum number of designs in the subset. If fewer passing designs have a usable sequence, the subset is smaller and the status message explains why. |
| α | 0 | 0 uses quality only; 1 uses diversity only. The slider uses a logarithmic scale from 0.0001 to 1 to give finer control near zero, while the number input accepts exact values including 0. Slider marks highlight BoltzGen's defaults: 0.001 for proteins and 0.01 for the peptide-anything protocol. |
| Size buckets | none | Optional length caps. Each bucket `{min, max, num_designs}` allows at most `num_designs` selected sequences with length in `[min, max)`. |

Designs with missing or blank sequences are excluded from diversity selection; otherwise they would score as maximally dissimilar to every other design. If the selected runs lack a `Sequence` column, diversity selection is skipped until you extract sequences (`POST /api/sequences/extract`).

Above Budget is **Keep only best MPNN variant per backbone**. When diversity selection is enabled, designs sharing a `backbone_id` collapse to the single variant with the best primary score (designs without a `backbone_id` are kept unchanged). This deduplication runs before diversity selection so the budget covers distinct backbones instead of multiple MPNN variants of the same backbone. Turning diversity selection off preserves the checkbox state but disables deduplication, so Saved Sets created with diversity off retain all filter-passing designs. The [filter cascade](#5-filter-cascade) displays this step as **Remove MPNN duplicates** above Diversity Selection. Toggling this checkbox after applying marks diversity **Unapplied**.

## 5. Filter cascade

The cascade is the sequential count of designs remaining after each enabled stage. It refreshes on the same debounce as hard filters and target contacts.

Rows appear in execution order: each hard filter, each target-contact condition, **Remove MPNN duplicates** (when active), Diversity Selection (when enabled or cached), and **Final set**. Disabled filters remain listed without a remaining count. **Final set** shows the count from the last active stage: the applied diverse subset, the post-MPNN-deduplication count, the last enabled filter, or the unfiltered total.

When diversity selection is enabled but unapplied, the cascade labels it as unapplied; **Final set** then reflects the hard-filter count after MPNN duplicate removal (if checked) or the hard-filter total. When diversity selection is off, MPNN deduplication does not run, and **Final set** equals all designs passing hard filters and target contacts.

## 6. Create Saved Set

**Create Saved Set** runs the full pipeline (filter, rank, optional best-MPNN-variant deduplication, and diversity selection) and saves an immutable snapshot containing the source run IDs, recipe, result summary, selected designs (with `final_rank`, `quality_score`, and diversity membership), and current UI state (table columns, sort order, and **Keep only best MPNN variant per backbone**). Clicking **Reapply filters** or **Load filters** restores both the recipe and that UI state.

When diversity is enabled, the saved set contains the diverse subset (up to Budget, limited to filter-passing designs with sequences). When diversity is off, it contains all designs passing the filters. The confirmation message reports the selected count, passing count, and total input count.

Saved sets are stored on the server, visible to all users on that instance, and unaffected by browser resets. You can rename or delete a saved set later; reapplying its filters creates a new set. Open saved sets under **Saved Sets** to inspect or export them as standard design bundles (ranked rows, structures, and saved UI state; see [Download bundles](../development/download-bundles.md)).
