"""Separate source metadata for one scan of the applicable original assets.

The caller retains the enclosing content-item, original-source and scan
context. Matching identifiers alone do not make metadata valid across scans.
These mappings describe data, not a snapshot schema or validity mechanism.
"""

from collections.abc import Mapping
from typing import NewType

# Plugin-supplied opaque identifiers and fingerprints have different meanings.
# NewType distinguishes them in type checking without interpreting their values.
SourceAssetId = NewType("SourceAssetId", str)
SourceFingerprint = NewType("SourceFingerprint", str)

# Keys are local segment IDs. Shared assets and multiple dependencies are valid.
# An absent dependency record is not proof that a segment has no dependencies.
type SegmentAssets = Mapping[str, frozenset[SourceAssetId]]
type AssetFingerprints = Mapping[SourceAssetId, SourceFingerprint]

# Only actual source-backed text belongs here. Missing entries differ from
# empty strings; inferred transcripts are not source-backed text.
type SourceTexts = Mapping[str, str]
