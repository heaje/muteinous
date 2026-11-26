"""Representative source-freshness boundary using actual synthetic assets."""

from pathlib import Path

import pytest

from muteinous.infrastructure.sources.fingerprints import fingerprint_assets
from muteinous.infrastructure.sources.validity import (
    StaleSourceEvidenceError,
    compare_source_evidence,
    require_source_validity,
)
from muteinous.models.source import SegmentAssets, SourceAssetId


@pytest.mark.portable
def test_source_change_refuses_stale_result_and_preserves_independent_result(
    tmp_path: Path,
) -> None:
    changed_asset = SourceAssetId("plugin:logical-audio")
    stable_asset = SourceAssetId("plugin:logical-text")
    changed_path = tmp_path / "audio-source.bin"
    stable_path = tmp_path / "text-source.bin"
    changed_path.write_bytes(b"original audio")
    stable_path.write_bytes(b"unchanged source text")
    dependencies: SegmentAssets = {
        "same-segment-id": frozenset({changed_asset}),
        "unaffected-segment": frozenset({stable_asset}),
    }
    prior_fingerprints = fingerprint_assets(
        {changed_asset: changed_path, stable_asset: stable_path}
    )

    changed_path.write_bytes(b"changed audio!")
    current_fingerprints = fingerprint_assets(
        {changed_asset: changed_path, stable_asset: stable_path}
    )
    validity = compare_source_evidence(
        {"same-segment-id": "stale-edit", "unaffected-segment": "valid-result"},
        dependencies,
        dependencies,
        prior_fingerprints,
        current_fingerprints,
    )

    assert validity.invalidated == frozenset({"same-segment-id"})
    assert validity.retained == {"unaffected-segment": "valid-result"}
    with pytest.raises(StaleSourceEvidenceError):
        require_source_validity(validity)
