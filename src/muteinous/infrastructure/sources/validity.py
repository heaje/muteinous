"""Conservative comparison of scan-scoped source dependencies."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Generic, TypeVar

from muteinous.models.source import (
    AssetFingerprints,
    SegmentAssets,
    SourceFingerprint,
)

_Result = TypeVar("_Result")


@dataclass(frozen=True, slots=True)
class SourceValidity(Generic[_Result]):
    """Results positively verified against the currently hashed sources."""

    retained: Mapping[str, _Result]
    invalidated: frozenset[str]


def compare_source_evidence(
    results: Mapping[str, _Result],
    previous_dependencies: SegmentAssets,
    current_dependencies: SegmentAssets,
    previous_fingerprints: AssetFingerprints,
    current_fingerprints: AssetFingerprints,
) -> SourceValidity[_Result]:
    """Retain only results with complete, unchanged source evidence.

    Dependency records are supplied separately by the plugin for each scan.
    If a result has no dependency record in either scan, its relationship to
    source changes cannot be isolated, so the whole supplied result set is
    invalidated. Missing fingerprints invalidate only results that depend on
    them; an empty dependency set is not evidence of source validity.
    """
    if any(
        segment_id not in previous_dependencies
        or segment_id not in current_dependencies
        for segment_id in results
    ):
        return SourceValidity(retained={}, invalidated=frozenset(results))

    retained: dict[str, _Result] = {}
    invalidated: set[str] = set()
    for segment_id, result in results.items():
        old_assets = previous_dependencies[segment_id]
        new_assets = current_dependencies[segment_id]
        valid = bool(old_assets) and old_assets == new_assets
        if valid:
            for asset_id in old_assets:
                old_fingerprint: SourceFingerprint | None = previous_fingerprints.get(
                    asset_id
                )
                new_fingerprint: SourceFingerprint | None = current_fingerprints.get(
                    asset_id
                )
                if (
                    old_fingerprint is None
                    or new_fingerprint is None
                    or old_fingerprint != new_fingerprint
                ):
                    valid = False
                    break
        if valid:
            retained[segment_id] = result
        else:
            invalidated.add(segment_id)
    return SourceValidity(
        retained=retained,
        invalidated=frozenset(invalidated),
    )


def require_source_validity(
    validity: SourceValidity[_Result],
) -> Mapping[str, _Result]:
    """Reject a stale result set before it is used for source-bound edits."""
    if validity.invalidated:
        raise StaleSourceEvidenceError(
            f"{len(validity.invalidated)} segment result(s) have stale or "
            "unverifiable source evidence"
        )
    return validity.retained


class StaleSourceEvidenceError(ValueError):
    """Raised when source-bound results are stale or cannot be verified."""
