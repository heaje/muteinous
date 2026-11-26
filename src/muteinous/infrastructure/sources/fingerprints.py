"""Deterministic, bounded-memory content fingerprints."""

from collections.abc import Mapping
from pathlib import Path

from blake3 import blake3

from muteinous.models.source import SourceAssetId, SourceFingerprint

# One reused buffer per call. A fresh ``read(n)`` allocation per chunk was ~40%
# slower on large files at 1 MiB and ~6x slower on small files; see
# docs/source-validity.md.
_HASH_CHUNK_SIZE = 256 * 1024


def fingerprint_file(path: Path) -> SourceFingerprint:
    """Fingerprint a plugin-selected content boundary without loading it whole.

    The caller is responsible for establishing that ``path`` refers to the
    applicable original source. This operation neither establishes provenance
    nor grants installation authority.
    """
    hasher = blake3(max_threads=1)
    buffer = bytearray(_HASH_CHUNK_SIZE)
    view = memoryview(buffer)
    with path.open("rb", buffering=0) as source:
        while count := source.readinto(buffer):
            hasher.update(view[:count])
    return SourceFingerprint(f"blake3:{hasher.hexdigest()}")


def fingerprint_assets(
    paths: Mapping[SourceAssetId, Path],
) -> dict[SourceAssetId, SourceFingerprint]:
    """Fingerprint plugin-defined assets sequentially; errors reject the batch."""
    return {asset_id: fingerprint_file(path) for asset_id, path in paths.items()}
