"""Content-neutral identities and scan-scoped source metadata invariants."""

from dataclasses import FrozenInstanceError, fields

import pytest

from muteinous.models.segment import Segment, SegmentKey
from muteinous.models.source import (
    AssetFingerprints,
    SegmentAssets,
    SourceAssetId,
    SourceFingerprint,
    SourceTexts,
)


def test_segment_is_immutable_and_identity_only() -> None:
    opaque_id = "  Native/Ω:0007 "
    segment = Segment(opaque_id)

    assert segment.id == opaque_id
    assert [field.name for field in fields(segment)] == ["id"]
    assert not hasattr(segment, "__dict__")
    assert segment == Segment(opaque_id)
    assert segment != Segment(opaque_id.lower())
    assert {segment, Segment(opaque_id)} == {segment}
    with pytest.raises(FrozenInstanceError):
        setattr(segment, "id", "different")


@pytest.mark.portable
def test_content_context_disambiguates_equal_segment_ids() -> None:
    segment = Segment("occurrence:1")
    first = SegmentKey("content:A", segment.id)
    second = SegmentKey("content:B", segment.id)
    combined = {first: "first", second: "second"}

    assert first != second
    assert combined[SegmentKey("content:A", segment.id)] == "first"
    assert combined[SegmentKey("content:B", segment.id)] == "second"
    assert len(combined) == 2
    with pytest.raises(FrozenInstanceError):
        setattr(first, "content_id", "content:B")


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
