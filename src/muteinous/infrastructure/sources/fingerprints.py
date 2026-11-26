"""Deterministic, bounded-memory content fingerprints."""

from collections.abc import Mapping
from pathlib import Path

from blake3 import blake3

from muteinous.models.source import SourceAssetId, SourceFingerprint

_HASH_CHUNK_SIZE = 1024 * 1024


def fingerprint_file(path: Path) -> SourceFingerprint:
    """Fingerprint a plugin-selected content boundary without loading it whole.

    The caller is responsible for establishing that ``path`` refers to the
    applicable original source. This operation neither establishes provenance
    nor grants installation authority.
    """
    hasher = blake3(max_threads=1)
    with path.open("rb") as source:
        while chunk := source.read(_HASH_CHUNK_SIZE):
            hasher.update(chunk)
    return SourceFingerprint(f"blake3:{hasher.hexdigest()}")


def fingerprint_assets(
    paths: Mapping[SourceAssetId, Path],
) -> dict[SourceAssetId, SourceFingerprint]:
    """Fingerprint plugin-defined assets sequentially; errors reject the batch."""
    return {asset_id: fingerprint_file(path) for asset_id, path in paths.items()}
