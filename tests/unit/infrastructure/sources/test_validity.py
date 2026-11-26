"""Scan results are reused only with positively verified source evidence."""

import os
from pathlib import Path

import pytest

from muteinous.infrastructure.sources.fingerprints import fingerprint_file
from muteinous.infrastructure.sources.validity import (
    StaleSourceEvidenceError,
    compare_source_evidence,
    require_source_validity,
)
from muteinous.models.source import (
    AssetFingerprints,
    SegmentAssets,
    SourceAssetId,
    SourceFingerprint,
)


def test_changed_shared_asset_invalidates_dependents_only() -> None:
    shared = SourceAssetId("plugin:shared")
    other = SourceAssetId("plugin:other")
    dependencies: SegmentAssets = {
        "one": frozenset({shared}),
        "two": frozenset({shared, other}),
        "three": frozenset({other}),
    }
    old: AssetFingerprints = {
        shared: SourceFingerprint("blake3:old"),
        other: SourceFingerprint("blake3:same"),
    }
    current: AssetFingerprints = {
        shared: SourceFingerprint("blake3:new"),
        other: SourceFingerprint("blake3:same"),
    }

    result = compare_source_evidence(
        {"one": "one-result", "two": "two-result", "three": "three-result"},
        dependencies,
        dependencies,
        old,
        current,
    )

    assert result.invalidated == frozenset({"one", "two"})
    assert result.retained == {"three": "three-result"}


def test_multiple_assets_missing_fingerprint_and_algorithm_mismatch_invalidate() -> (
    None
):
    left = SourceAssetId("plugin:left")
    right = SourceAssetId("plugin:right")
    dependencies: SegmentAssets = {"multi": frozenset({left, right})}
    previous: AssetFingerprints = {
        left: SourceFingerprint("blake3:same"),
        right: SourceFingerprint("blake3:right"),
    }
    current: AssetFingerprints = {
        left: SourceFingerprint("sha256:same"),
    }

    result = compare_source_evidence(
        {"multi": "result"},
        dependencies,
        dependencies,
        previous,
        current,
    )

    assert result.invalidated == frozenset({"multi"})
    assert not result.retained


def test_incomplete_dependency_mapping_broadens_to_all_results() -> None:
    asset = SourceAssetId("plugin:asset")
    deps: SegmentAssets = {"known": frozenset({asset})}
    fingerprints: AssetFingerprints = {asset: SourceFingerprint("blake3:ok")}

    result = compare_source_evidence(
        {"known": "known", "unknown": "unknown"},
        deps,
        deps,
        fingerprints,
        fingerprints,
    )

    assert result.invalidated == frozenset({"known", "unknown"})
    assert not result.retained


def test_content_change_with_preserved_filesystem_metadata_is_detected(
    tmp_path: Path,
) -> None:
    asset = SourceAssetId("plugin:asset")
    deps: SegmentAssets = {"segment": frozenset({asset})}
    source = tmp_path / "asset.bin"
    source.write_bytes(b"before")
    original_stat = source.stat()
    before: AssetFingerprints = {asset: fingerprint_file(source)}
    source.write_bytes(b"afters")
    os.utime(source, ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns))
    after: AssetFingerprints = {asset: fingerprint_file(source)}

    result = compare_source_evidence(
        {"segment": "same-id-result"}, deps, deps, before, after
    )

    assert result.invalidated == frozenset({"segment"})
    with pytest.raises(StaleSourceEvidenceError):
        require_source_validity(result)


def test_empty_dependency_and_missing_current_asset_are_unverifiable() -> None:
    asset = SourceAssetId("plugin:asset")
    deps: SegmentAssets = {
        "empty": frozenset(),
        "missing": frozenset({asset}),
    }
    previous: AssetFingerprints = {asset: SourceFingerprint("blake3:old")}

    result = compare_source_evidence(
        {"empty": 1, "missing": 2},
        deps,
        deps,
        previous,
        {},
    )

    assert result.invalidated == frozenset({"empty", "missing"})
    assert not result.retained


@pytest.mark.portable
def test_changed_dependency_identity_invalidates_only_dependent_result() -> None:
    old_asset = SourceAssetId("plugin:old-boundary")
    new_asset = SourceAssetId("plugin:new-boundary")
    fingerprints: AssetFingerprints = {
        old_asset: SourceFingerprint("blake3:same"),
        new_asset: SourceFingerprint("blake3:same"),
    }

    result = compare_source_evidence(
        {"changed": "old", "unaffected": "valid"},
        {"changed": frozenset({old_asset}), "unaffected": frozenset({old_asset})},
        {"changed": frozenset({new_asset}), "unaffected": frozenset({old_asset})},
        fingerprints,
        fingerprints,
    )

    assert result.invalidated == frozenset({"changed"})
    assert result.retained == {"unaffected": "valid"}
