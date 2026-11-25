"""Scan-scoped source metadata: assets, fingerprints and exact text."""

import pytest

from muteinous.models.segment import SegmentKey
from muteinous.models.source import (
    AssetFingerprints,
    SegmentAssets,
    SourceAssetId,
    SourceFingerprint,
    SourceTexts,
)


def test_shared_and_multiple_source_assets() -> None:
    audio = SourceAssetId("opaque:audio")
    text = SourceAssetId("opaque:text")
    dependencies: SegmentAssets = {
        "first": frozenset({audio, text}),
        "second": frozenset({audio}),
        "known-empty": frozenset(),
    }
    fingerprints: AssetFingerprints = {
        audio: SourceFingerprint("same-digest"),
        text: SourceFingerprint("same-digest"),
    }

    assert dependencies["first"] == frozenset({audio, text})
    assert dependencies["first"] & dependencies["second"] == frozenset({audio})
    assert len(fingerprints) == 2
    assert fingerprints[audio] == fingerprints[text]
    assert "unknown" not in dependencies
    assert dependencies["known-empty"] == frozenset()


def test_matching_occurrence_identity_does_not_establish_source_validity() -> None:
    # Separate original-source scans can share logical IDs but not fingerprints.
    first = SegmentKey("compatible-content", "occurrence")
    second = SegmentKey("compatible-content", "occurrence")
    asset = SourceAssetId("asset")
    dependencies: SegmentAssets = {first.segment_id: frozenset({asset})}
    first_scan: AssetFingerprints = {asset: SourceFingerprint("old")}
    second_scan: AssetFingerprints = {asset: SourceFingerprint("new")}

    assert first == second
    assert dependencies[first.segment_id] == dependencies[second.segment_id]
    assert first_scan[asset] != second_scan[asset]


def test_source_asset_ids_and_fingerprints_are_distinct_static_types() -> None:
    # These ignores are consumed by strict mypy only while the values are distinct NewTypes.
    asset_id: SourceAssetId = SourceFingerprint("opaque:fingerprint")  # type: ignore[assignment]
    fingerprint: SourceFingerprint = SourceAssetId("opaque:asset")  # type: ignore[assignment]

    assert type(asset_id) is str
    assert type(fingerprint) is str
    assert asset_id == "opaque:fingerprint"
    assert fingerprint == "opaque:asset"


def test_source_texts_do_not_admit_explicit_none_values_statically() -> None:
    # Strict mypy keeps this ignore useful only while SourceTexts excludes None.
    source_texts: SourceTexts = {"explicit-none": None}  # type: ignore[dict-item]

    assert source_texts["explicit-none"] is None


@pytest.mark.portable
def test_source_text_preserves_exact_unicode_whitespace_and_presence() -> None:
    # Decomposed accent, non-Latin text, emoji, punctuation and mixed whitespace.
    exact = "\t  Cafe\u0301 — ‘你好’! 🙂\r\n "
    source_texts: SourceTexts = {"written": exact, "empty": ""}
    dependencies: SegmentAssets = {"audio-only": frozenset({SourceAssetId("audio")})}

    assert source_texts["written"] == exact
    assert source_texts["written"] != "\t  Café — ‘你好’! 🙂\r\n "
    assert source_texts["empty"] == ""
    assert "audio-only" in dependencies
    assert "audio-only" not in source_texts
    assert source_texts.get("audio-only") is None
