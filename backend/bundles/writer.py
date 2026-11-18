"""BundleSpec -> zip, built into a spooled temp file.

Buffered into a ``SpooledTemporaryFile`` rather than streamed from a generator. zipfile
can write to a non-seekable stream, but doing so costs the Content-Length header (so the
browser shows no download progress), turns a mid-archive exception into a truncated zip
delivered with a 200, and saves no memory: ``write_file_member`` streams each structure
file either way. What scales with bundle size is the temp file, which spills to disk.
"""

from __future__ import annotations

import json
import logging
import shutil
import tempfile
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, BinaryIO, Iterator, List, Optional

from . import members as M
from .hashing import MemberDigest, write_file_member
from .json_schemas import schema_arcname, schema_document, schema_names_for_kind
from .models import (
    BuildInfo,
    BundleFileEntry,
    BundleManifest,
)
from .sources import safe_label
from .spec import BundleSpec
from ..settings import settings

logger = logging.getLogger(__name__)

SPOOL_THRESHOLD_BYTES = 32 * 1024 * 1024
STREAM_CHUNK_BYTES = 256 * 1024
COMPRESS_LEVEL = 6

MANIFEST_ARCNAME = "manifest.json"
README_ARCNAME = "README.txt"


def bundle_spool_dir() -> Optional[str]:
    """Where the zip is built.

    Not simply ``tempfile.gettempdir()``: in the packaged desktop app ``/tmp`` is often
    tmpfs, i.e. RAM, which would silently defeat spilling to disk.
    """
    configured = (settings.bundle_spool_dir or "").strip()
    if configured:
        Path(configured).mkdir(parents=True, exist_ok=True)
        return configured
    try:
        from ..runtime_paths import is_frozen

        if is_frozen():
            from desktop.paths import user_data_dir

            spool = Path(user_data_dir()) / "bundle_spool"
            spool.mkdir(parents=True, exist_ok=True)
            return str(spool)
    except Exception:
        pass
    return None


@dataclass
class BuiltBundle:
    fileobj: BinaryIO
    size_bytes: int
    filename: str
    manifest: BundleManifest

    def close(self) -> None:
        try:
            self.fileobj.close()
        except Exception:
            logger.debug("bundle temp file already closed")


def build_info() -> BuildInfo:
    from ..version import build_identity, platform_label, python_version

    identity = build_identity()
    return BuildInfo(
        app_version=identity.app_version,
        git_commit=identity.git_commit,
        git_dirty=identity.git_dirty,
        build_source=identity.source,
        python_version=python_version(),
        platform=platform_label(),
    )


_DESCRIPTIONS = {
    "designs.tsv": "One row per design: every column Binderdash holds for it.",
    "binders.fasta": "Binder amino acid sequences, one record per design.",
    "target_contacts.tsv": "Cached per-residue target contact distances and SASA.",
    "target_contacts_reference.json": "Per-run apo SASA reference and compute parameters.",
    "binderdash_session.json": "The Binderdash UI state that produced this bundle.",
    "prepare_sequences.json": "Tag placement, short-name and codon optimisation settings.",
    "constructs.tsv": "Prepared constructs: tagged AA and optimised DNA per design.",
    "constructs_aa.fasta": "Tagged construct amino acid sequences.",
    "constructs_dna.fasta": "Codon-optimised construct nucleotide sequences.",
    "constructs_twist_aa.csv": "Twist vendor order format, amino acid sequences.",
    "constructs_twist_dna.csv": "Twist vendor order format, codon-optimised nucleotide sequences.",
    README_ARCNAME: "This description of the bundle's contents.",
}

_MEDIA_TYPES = {
    ".tsv": "text/tab-separated-values",
    ".csv": "text/csv",
    ".json": "application/json",
    ".fasta": "text/x-fasta",
    ".txt": "text/plain",
    ".pdb": "chemical/x-pdb",
    ".cif": "chemical/x-mmcif",
}


def _media_type(arcname: str) -> str:
    return _MEDIA_TYPES.get(Path(arcname).suffix.lower(), "application/octet-stream")


def bundle_root(label: str) -> str:
    """Single path segment every zip member lives under.

    The segment is the download name (order name, or saved-set name). Without it,
    extracting the archive scatters designs.tsv, structures/ and the rest into the
    current directory.
    """
    return safe_label(label)


def _describe(relative: str) -> str:
    if relative in _DESCRIPTIONS:
        return _DESCRIPTIONS[relative]
    if relative.startswith("structures/"):
        return "Design structure file, as produced by the pipeline."
    if relative.startswith("schemas/"):
        return "JSON Schema for the correspondingly named JSON file."
    return ""


class _Inventory:
    def __init__(self, root: str) -> None:
        self.root = root
        self.entries: List[BundleFileEntry] = []

    def member(self, relative: str) -> str:
        return f"{self.root}/{relative}"

    def add(self, relative: str, digest: MemberDigest) -> None:
        self.entries.append(
            BundleFileEntry(
                path=self.member(relative),
                size_bytes=digest.size_bytes,
                sha256=digest.sha256,
                media_type=_media_type(relative),
                description=_describe(relative),
            )
        )


def _readme(spec: BundleSpec, root: str) -> str:
    lines = [
        "Binderdash design bundle",
        "========================",
        "",
        f"bundle_id:  {spec.bundle_id}",
        f"created:    {spec.created_at}",
        f"kind:       {spec.kind}",
        f"folder:     {root}",
        "",
        "Extracting the zip creates that one folder. Everything listed below is inside it.",
        "Paths in manifest.json include the folder name, matching the names inside the zip.",
        "",
        "Contents",
        "--------",
    ]
    for arcname, description in _DESCRIPTIONS.items():
        lines.append(f"  {arcname:<34} {description}")
    lines += [
        "  structures/                        Design structure files, one per design.",
        "  schemas/                           JSON Schema for each JSON file above.",
        "",
        "Integrity",
        "---------",
        "manifest.json lists every other file with its size and sha256. It cannot list",
        "itself; `unzip -t` verifies the archive's own CRCs, including the manifest.",
        "",
        "Reproducibility",
        "---------------",
        "binderdash_session.json records the selected runs, table sort, active filters and",
        "ranking configuration. Restore it through Binderdash's \"Restore session from",
        "JSON\" action to return the UI to the state that produced this bundle.",
    ]
    return "\n".join(lines) + "\n"


def write_bundle(spec: BundleSpec) -> BuiltBundle:
    """Build the zip. Synchronous; call under asyncio.to_thread."""
    spool = bundle_spool_dir()
    tmp = tempfile.SpooledTemporaryFile(max_size=SPOOL_THRESHOLD_BYTES, dir=spool)
    root = bundle_root(spec.label)
    inventory = _Inventory(root)
    warnings: List[str] = list(spec.warnings)

    try:
        with zipfile.ZipFile(
            tmp,
            "w",
            compression=zipfile.ZIP_DEFLATED,
            compresslevel=COMPRESS_LEVEL,
            allowZip64=True,
        ) as zf:
            inventory.add(
                README_ARCNAME,
                M.write_text_member(zf, inventory.member(README_ARCNAME), _readme(spec, root)),
            )

            if spec.rows:
                inventory.add(
                    "designs.tsv",
                    M.write_designs_table(zf, inventory.member("designs.tsv"), spec.rows),
                )
                digest, _written, skipped = M.write_binders_fasta(
                    zf, inventory.member("binders.fasta"), spec.rows
                )
                inventory.add("binders.fasta", digest)
                if skipped:
                    warnings.append(
                        f"{skipped} design(s) had no recognised sequence column and were "
                        "omitted from binders.fasta"
                    )

            if spec.contacts and spec.contacts.rows:
                inventory.add(
                    "target_contacts.tsv",
                    M.write_contacts_table(
                        zf, inventory.member("target_contacts.tsv"), spec.contacts
                    ),
                )
                if spec.contacts.reference is not None:
                    reference = spec.contacts.reference.model_copy(
                        update={"generated_at": spec.created_at, "binderdash": build_info()}
                    )
                    inventory.add(
                        "target_contacts_reference.json",
                        M.write_json_member(
                            zf, inventory.member("target_contacts_reference.json"), reference
                        ),
                    )

            if spec.session is not None:
                inventory.add(
                    "binderdash_session.json",
                    M.write_json_member(
                        zf, inventory.member("binderdash_session.json"), spec.session
                    ),
                )

            if spec.prepared is not None:
                prepared = spec.prepared.model_copy(
                    update={"generated_at": spec.created_at, "binderdash": build_info()}
                )
                inventory.add(
                    "constructs.tsv",
                    M.write_constructs_table(zf, inventory.member("constructs.tsv"), prepared),
                )
                aa_digest, dna_digest, _n = M.write_construct_fastas(
                    zf,
                    inventory.member("constructs_aa.fasta"),
                    inventory.member("constructs_dna.fasta"),
                    prepared,
                )
                inventory.add("constructs_aa.fasta", aa_digest)
                if dna_digest is not None:
                    inventory.add("constructs_dna.fasta", dna_digest)
                else:
                    warnings.append(
                        "No optimised DNA was available, so constructs_dna.fasta and "
                        "constructs_twist_dna.csv are absent"
                    )
                aa_twist_digest, aa_twist_skipped = M.write_constructs_twist_csv(
                    zf, inventory.member("constructs_twist_aa.csv"), prepared, "prepared_aa"
                )
                inventory.add("constructs_twist_aa.csv", aa_twist_digest)
                if aa_twist_skipped:
                    warnings.append(
                        f"{aa_twist_skipped} construct(s) had no amino acid sequence "
                        "and were omitted from constructs_twist_aa.csv"
                    )
                if dna_digest is not None:
                    dna_twist_digest, dna_twist_skipped = M.write_constructs_twist_csv(
                        zf, inventory.member("constructs_twist_dna.csv"), prepared, "prepared_dna"
                    )
                    inventory.add("constructs_twist_dna.csv", dna_twist_digest)
                    if dna_twist_skipped:
                        warnings.append(
                            f"{dna_twist_skipped} construct(s) had no optimised DNA "
                            "and were omitted from constructs_twist_dna.csv"
                        )
                inventory.add(
                    "prepare_sequences.json",
                    M.write_json_member(
                        zf,
                        inventory.member("prepare_sequences.json"),
                        prepared,
                        exclude={"rows": {"__all__": M.PREPARED_ROW_EXCLUDE}},
                    ),
                )

            for ref in spec.structures:
                try:
                    inventory.add(
                        ref.arcname, write_file_member(zf, inventory.member(ref.arcname), ref.path)
                    )
                except (OSError, ValueError) as e:
                    # A file removed between path resolution and here, or a pre-1980
                    # mtime that zipfile refuses. Neither is worth losing the bundle.
                    warnings.append(f"Could not archive {ref.path.name}: {e}")
                    logger.warning("skipping structure %s: %s", ref.path, e)

            for name in schema_names_for_kind(spec.kind):
                relative = schema_arcname(name)
                inventory.add(
                    relative,
                    M.write_text_member(
                        zf,
                        inventory.member(relative),
                        json.dumps(schema_document(name), indent=2) + "\n",
                    ),
                )

            manifest = BundleManifest(
                bundle_id=spec.bundle_id,
                bundle_kind=spec.kind,
                created_at=spec.created_at,
                label=spec.label,
                build=build_info(),
                provenance=spec.provenance,
                coverage=spec.coverage(),
                files=sorted(inventory.entries, key=lambda e: e.path),
                warnings=warnings,
            )
            M.write_json_member(zf, inventory.member(MANIFEST_ARCNAME), manifest)

        size = tmp.tell()
        tmp.seek(0)
        return BuiltBundle(
            fileobj=tmp,  # type: ignore[arg-type]
            size_bytes=size,
            filename=f"{root}.zip",
            manifest=manifest,
        )
    except BaseException:
        tmp.close()
        raise


def iter_bundle(built: BuiltBundle, chunk: int = STREAM_CHUNK_BYTES) -> Iterator[bytes]:
    try:
        while True:
            data = built.fileobj.read(chunk)
            if not data:
                break
            yield data
    finally:
        built.close()


def check_spool_space(required_bytes: int) -> Optional[str]:
    """None if there is room, otherwise a message. Better a clear error up front than an
    ENOSPC traceback halfway through a large build."""
    target = bundle_spool_dir() or tempfile.gettempdir()
    try:
        free = shutil.disk_usage(target).free
    except OSError:
        return None
    if required_bytes and free < required_bytes:
        return (
            f"Not enough scratch space to build the bundle: needs about "
            f"{required_bytes // (1024 * 1024)} MB, {free // (1024 * 1024)} MB free in {target}"
        )
    return None
