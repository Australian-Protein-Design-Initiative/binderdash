# Binderdash

![Binderdash: the design table with scores, and a binder-target complex in the structure viewer](images/binderdash-hero.png)

**Binderdash filters, ranks, and designs DNA constructs for de novo protein binders.**

Point it at the output folders from your design runs to inspect scores and structures in one interface, filter and rank candidates, and export ready-to-order DNA constructs.

## Features

- Reads run output folders directly from RFdiffusion, RFdiffusion3, BindCraft, and BoltzGen, and detects `nf-binder-design` pipeline outputs without reformatting.
- Displays designs from different runs and methods in one sortable table, matching common metrics (ipTM, interface PAE, RMSD, pLDDT) across pipelines that name them differently.
- Includes a Mol\* 3D structure viewer to step through designs, colour by chain or pLDDT, overlay a reference structure, and mark designs as good or bad.
- Filters and ranks designs using score thresholds and target-contact conditions (for example, binding within 5 Å of selected epitope residues), multi-metric ranking, and diversity-aware shortlisting. The filter cascade UI shows how many designs each condition removes. See [Filtering and ranking](usage/filtering-ranking.md).
- Plots scatterplots and histograms for any pair of metrics.
- Saves design shortlists together with the filters and ranking that produced them.
- Designs DNA constructs with N- or C-terminal affinity tags and linkers (His, FLAG, Strep-tag II, AviTag, and others), codon optimisation under synthesis complexity constraints (GC content, hairpins, restriction sites), vendor-compatible short names, and Twist-ready CSV export.
- Exports design bundles containing structures, sequences, tables, selections, filters, and settings so a shortlist can be traced and restored later.
- Merges extra columns from uploaded TSV files (for example, lab results) onto designs by ID for filtering and ranking.
- Runs as a local desktop app or a shared server with sign-in (local accounts, Unix/PAM, or Google), per-user API keys, and an optional [MCP endpoint](development/mcp.md) and [REST API](development/api.md) for AI agents.

## Getting started

- [Desktop app](setup/desktop.md): download a build for Linux, macOS, or Windows from the [latest release](https://github.com/Australian-Protein-Design-Initiative/binderdash/releases/latest) for local single-user use.
- [Server with Docker](setup/docker.md): host a shared instance for a group, with HTTPS and [sign-in](setup/authentication.md).

## For developers

- [Development setup](development/setup.md): run from source, tests, and building these docs
- [REST API](development/api.md) and [MCP server](development/mcp.md)
- [Adding a pipeline method type](development/pipeline-methods.md)

Source code, issues and releases are on [GitHub](https://github.com/Australian-Protein-Design-Initiative/binderdash).
