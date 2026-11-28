"""Content fingerprinting uses bounded, deterministic reads."""

import hashlib
from pathlib import Path
from typing import Any, cast

import pytest
from blake3 import blake3

from muteinous.infrastructure.sources import fingerprints
from muteinous.infrastructure.sources.fingerprints import (
    fingerprint_assets,
    fingerprint_file,
)
from muteinous.models.source import SourceAssetId


@pytest.mark.portable
def test_fingerprint_is_deterministic_and_algorithm_distinguishable(
    tmp_path: Path,
) -> None:
    source = tmp_path / "asset.bin"
    source.write_bytes(b"abc")

    first = fingerprint_file(source)
    second = fingerprint_file(source)

    assert first == second
    assert (
        first
        == "blake3:6437b3ac38465133ffb63b75273a8db548c558465d79db03fd359c6cd5bd9d85"
    )
    assert first != f"sha256:{hashlib.sha256(b'abc').hexdigest()}"


def test_fingerprinting_constructs_single_threaded_hashers(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "asset.bin"
    source.write_bytes(b"asset")
    max_threads_values: list[int] = []

    def record_constructor(*, max_threads: int) -> blake3:
        max_threads_values.append(max_threads)
        return blake3(max_threads=max_threads)

    monkeypatch.setattr(fingerprints, "blake3", record_constructor)

    file_fingerprint = fingerprints.fingerprint_file(source)
    asset_fingerprint = fingerprints.fingerprint_assets(
        {SourceAssetId("asset"): source}
    )[SourceAssetId("asset")]

    assert file_fingerprint == asset_fingerprint
    assert max_threads_values == [1, 1]


def test_fingerprint_streams_in_fixed_size_chunks_and_does_not_modify_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "large.bin"
    content = b"x" * (1024 * 1024 + 17)
    source.write_bytes(content)
    before = source.read_bytes()
    original_open = Path.open
    read_sizes: list[int] = []

    class TrackingReader:
        def __init__(self, wrapped: Any) -> None:
            self._wrapped = wrapped

        def __enter__(self) -> TrackingReader:
            return self

        def __exit__(self, *args: Any) -> None:
            self._wrapped.close()

        def fileno(self) -> int:
            return cast(int, self._wrapped.fileno())

        def readinto(self, buffer: Any) -> int:
            read_sizes.append(len(buffer))
            return cast(int, self._wrapped.readinto(buffer))

    def tracked_open(path: Path, mode: str = "r", *args: Any, **kwargs: Any) -> Any:
        wrapped = original_open(path, mode, *args, **kwargs)
        return TrackingReader(wrapped) if path == source else wrapped

    monkeypatch.setattr(Path, "open", cast(Any, tracked_open))
    result = fingerprint_file(source)

    assert result == f"blake3:{blake3(content, max_threads=1).hexdigest()}"
    assert len(read_sizes) > 1
    assert max(read_sizes) <= 1024 * 1024
    with original_open(source, "rb") as check:
        assert check.read() == before


def test_missing_or_unreadable_file_is_not_fingerprinted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    missing = tmp_path / "missing.bin"
    with pytest.raises(FileNotFoundError):
        fingerprint_file(missing)

    source = tmp_path / "asset.bin"
    source.write_bytes(b"asset")
    original_open = Path.open

    def unreadable(path: Path, mode: str = "r", *args: Any, **kwargs: Any) -> Any:
        if path == source:
            raise PermissionError("synthetic unreadable source")
        return original_open(path, mode, *args, **kwargs)

    monkeypatch.setattr(Path, "open", cast(Any, unreadable))
    with pytest.raises(PermissionError):
        fingerprint_assets({SourceAssetId("asset"): source})
