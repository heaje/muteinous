"""Opaque occurrence identities, independent of source validity."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Segment:
    """A plugin-assigned identity unique within its content item."""

    id: str


@dataclass(frozen=True, slots=True)
class SegmentKey:
    """An occurrence key for use across content items.

    The content ID identifies a plugin-defined compatible occurrence namespace,
    not an installation. Key equality is not evidence of unchanged original
    assets, valid scan results, or authorization to edit or install anything.
    """

    content_id: str
    segment_id: str
