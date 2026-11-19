# Binderdash

![Binderdash: the design table with scores, and a binder-target complex in the structure viewer](docs/images/binderdash-hero.png)

**Binderdash filters, ranks, and designs DNA constructs for de novo protein binders.**

Point it at the output folders from your design runs to inspect scores and structures in one interface, filter and rank candidates, and export ready-to-order DNA constructs.

[Documentation](https://australian-protein-design-initiative.github.io/binderdash/) · [Download the desktop app](https://github.com/Australian-Protein-Design-Initiative/binderdash/releases/latest) · [Changelog](CHANGELOG.md)

## Features

- Reads run output folders directly from RFdiffusion, RFdiffusion3, BindCraft, and BoltzGen, and detects `nf-binder-design` pipeline outputs without reformatting.
- Displays designs from different runs and methods in one sortable table, matching common metrics (ipTM, interface PAE, RMSD, pLDDT) across pipelines that name them differently.
- Includes a Mol\* 3D structure viewer to step through designs, colour by chain or pLDDT, overlay a reference structure, and mark designs as good or bad.
- Filters and ranks designs using score thresholds and target-contact conditions (for example, binding within 5 Å of selected epitope residues), multi-metric ranking, and diversity-aware shortlisting. The filter cascade UI shows how many designs each condition removes.
- Plots scatterplots and histograms for any pair of metrics.
- Saves design shortlists together with the filters and ranking that produced them.
- Designs DNA constructs with N- or C-terminal affinity tags and linkers (His, FLAG, Strep-tag II, AviTag, and others), codon optimisation under synthesis complexity constraints (GC content, hairpins, restriction sites), vendor-compatible short names, and Twist-ready CSV export.
- Exports design bundles containing structures, sequences, tables, selections, filters, and settings so a shortlist can be traced and restored later.
- Merges extra columns from uploaded TSV files (for example, lab results) onto designs by ID for filtering and ranking.
- Runs as a local desktop app or a shared server with sign-in (local accounts, Unix/PAM, or Google), per-user API keys, and an optional MCP endpoint and REST API for AI agents.

## Getting started

### Desktop

Download the build for your platform from the **[latest release](https://github.com/Australian-Protein-Design-Initiative/binderdash/releases/latest)**:

| Platform | File |
| --- | --- |
| Linux (x86_64) | `Binderdash-<version>-x86_64.AppImage` |
| macOS (Apple silicon) | `Binderdash-<version>-macos-arm64.zip` |
| Windows (64-bit) | `Binderdash-<version>-win64.zip` |

Start the app, open **Ingest Runs**, choose the folder that contains your design runs, and ingest them. See [Desktop app](https://australian-protein-design-initiative.github.io/binderdash/latest/setup/desktop/) for platform notes (the builds are not code-signed, so macOS and Windows will ask you to confirm the first launch).

### Server

For a shared instance, run Binderdash with Docker Compose. The Compose setup includes a Caddy reverse proxy for HTTPS.

```bash
git clone https://github.com/Australian-Protein-Design-Initiative/binderdash.git
cd binderdash
cp .env.example .env        # then edit: RUN_BASE_DIRS, DOMAIN and sign-in settings
printf 'BINDERDASH_UID=%s\nBINDERDASH_GID=%s\n' "$(id -u)" "$(id -g)" >> .env   # run as you
docker compose up -d --build
```

Mount your run directories into the `binderdash` service in `docker-compose.yml` (read-only mounts are supported) and list the in-container paths in `RUN_BASE_DIRS`. Then open `https://<DOMAIN>` (or `https://localhost`).

The example `.env` has authentication turned off. Before exposing the server to other people, set up sign-in as described in [Authentication](https://australian-protein-design-initiative.github.io/binderdash/latest/setup/authentication/). Full deployment details are in [Docker deployment](https://australian-protein-design-initiative.github.io/binderdash/latest/setup/docker/).

## Documentation

The full documentation is at **<https://australian-protein-design-initiative.github.io/binderdash/>**, covering:

- [Filtering and ranking](https://australian-protein-design-initiative.github.io/binderdash/latest/usage/filtering-ranking/)
- [Docker deployment](https://australian-protein-design-initiative.github.io/binderdash/latest/setup/docker/) and [authentication](https://australian-protein-design-initiative.github.io/binderdash/latest/setup/authentication/)
- The [REST API](https://australian-protein-design-initiative.github.io/binderdash/latest/development/api/) and [MCP server](https://australian-protein-design-initiative.github.io/binderdash/latest/development/mcp/) for scripted and agent access

## Development

To run Binderdash from source, work on the code, or add support for a new design pipeline, see the [development guide](docs/development/setup.md). In short:

```bash
uv venv -p python3.12 .venv && source .venv/bin/activate
uv pip install -r backend/requirements.txt
(cd frontend && pnpm install && pnpm run build)
uv run uvicorn backend.main:app --reload --port 8000
```

Contributions are welcome. Please add an entry to [CHANGELOG.md](CHANGELOG.md) for notable changes.
