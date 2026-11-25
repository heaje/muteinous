"""Content-neutral identities and scan-scoped source metadata invariants."""

import ast
import sys
from dataclasses import FrozenInstanceError, fields
from pathlib import Path

import pytest

import muteinous.models as models
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
def test_models_imports_are_stdlib_or_within_models_package() -> None:
    package_dir = Path(models.__file__).parent
    violations: list[str] = []

    for path in sorted(package_dir.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        relative_parts = path.relative_to(package_dir).with_suffix("").parts
        package_parts = relative_parts[:-1]
        current_package = ".".join(("muteinous", "models", *package_parts))

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported_modules = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                if node.level:
                    base_parts = current_package.split(".")
                    base_parts = base_parts[: max(0, len(base_parts) - node.level + 1)]
                    if node.module:
                        base_parts.extend(node.module.split("."))
                    imported_modules = [".".join(base_parts)]
                elif node.module:
                    imported_modules = [node.module]
                else:
                    continue
            else:
                continue

            for module in imported_modules:
                top_level = module.partition(".")[0]
                if top_level in sys.stdlib_module_names or (
                    module == "muteinous.models"
                    or module.startswith("muteinous.models.")
                ):
                    continue
                violations.append(f"{path}: imports {module}")

    assert not violations, "\n".join(violations)


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
