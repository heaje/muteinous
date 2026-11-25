"""Opaque occurrence identity and content-scoped keys."""

from dataclasses import FrozenInstanceError, fields

import pytest

from muteinous.models.segment import Segment, SegmentKey


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

    assert first == SegmentKey(content_id="content:A", segment_id=segment.id)
    assert first.content_id == "content:A"
    assert first.segment_id == segment.id
    assert second.content_id == "content:B"
    assert second.segment_id == segment.id
    assert first != second
    assert combined[SegmentKey("content:A", segment.id)] == "first"
    assert combined[SegmentKey("content:B", segment.id)] == "second"
    assert len(combined) == 2
    with pytest.raises(FrozenInstanceError):
        setattr(first, "content_id", "content:B")
