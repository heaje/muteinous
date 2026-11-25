"""Deterministic result integrity and safe-path unit checks."""

import hashlib
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace

import pytest

from muteinous.infrastructure.storage._filesystem import (
    InsufficientSpace,
    StorageError,
    canonical_json,
    checked_directory,
    checked_stat,
    file_record,
    read_json,
    safe_name,
    walk_files,
)
from muteinous.infrastructure.storage.bundles import ResultIdentity, _metadata
from muteinous.infrastructure.storage.space import SpaceRequirement, preflight

pytestmark = pytest.mark.portable


def test_metadata_has_exact_canonical_bytes_and_order(tmp_path: Path) -> None:
    (tmp_path / "z.bin").write_bytes(b"z")
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "member.txt").write_bytes(b"a")
    identity = ResultIdentity("source", "config", "generation")
    bundle = "0" * 32
    records = [
        {
            "path": "a/member.txt",
            "length": 1,
            "sha256": hashlib.sha256(b"a").hexdigest(),
        },
        {"path": "z.bin", "length": 1, "sha256": hashlib.sha256(b"z").hexdigest()},
    ]
    expected = canonical_json(
        {
            "bundle": bundle,
            "configuration": "config",
            "files": records,
            "generation": "generation",
            "result": "scan",
            "schema": 1,
            "source": "source",
        }
    )
    assert (
        _metadata(tmp_path, "scan", bundle, identity, controlled_root=tmp_path)
        == expected
    )
    assert (
        _metadata(tmp_path, "scan", bundle, identity, controlled_root=tmp_path)
        == expected
    )
    assert canonical_json({"key": "é"}) == '{"key":"é"}'.encode("utf-8")
    assert canonical_json({"z": 2, "a": 1}) == b'{"a":1,"z":2}'


@pytest.mark.parametrize(
    "raw",
    [
        b'{"a":1,"a":1}',
        b'{"a": 1}',
        b'{"a":NaN}',
        b'{"a":Infinity}',
        b'{"a":"\\ud800"}',
        b"[]",
        b"\xff",
        b"\xef\xbb\xbf{}",
    ],
)
def test_invalid_or_noncanonical_json_is_rejected(raw: bytes) -> None:
    with pytest.raises(StorageError):
        read_json(raw)


@pytest.mark.parametrize(
    "name",
    [
        "",
        ".",
        "..",
        "../escape",
        "a/b",
        "a\\b",
        "C:drive",
        "NUL.txt",
        "COM1",
        "x.",
        "x ",
        "a\x00",
    ],
)
def test_unsafe_path_components_are_rejected(name: str) -> None:
    with pytest.raises(StorageError):
        safe_name(name)


def test_walk_files_rejects_casefold_collisions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = tmp_path / "payload.bin"
    second = tmp_path / "PAYLOAD.BIN"
    first.write_bytes(b"one")
    if not second.exists():
        second.write_bytes(b"two")

    def collision_listing(path: Path) -> Iterator[Path]:
        if path == tmp_path:
            return iter([first, second])
        return path.iterdir()

    monkeypatch.setattr("pathlib.Path.iterdir", collision_listing)
    with pytest.raises(StorageError, match="Ambiguous path"):
        walk_files(tmp_path, controlled_root=tmp_path)


def test_walk_files_rejects_unsafe_inventory_names(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    unsafe = tmp_path / "NUL.txt"

    def unsafe_listing(path: Path) -> Iterator[Path]:
        if path == tmp_path:
            return iter([unsafe])
        return path.iterdir()

    monkeypatch.setattr("pathlib.Path.iterdir", unsafe_listing)
    with pytest.raises(StorageError, match="Unsafe path component"):
        walk_files(tmp_path, controlled_root=tmp_path)


@pytest.mark.parametrize("entry_type", ["file", "directory"])
def test_walk_files_rejects_alternate_streams(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, entry_type: str
) -> None:
    if entry_type == "file":
        target = tmp_path / "payload.bin"
        target.write_bytes(b"payload")
    else:
        target = tmp_path / "nested"
        target.mkdir()
        (target / "payload.bin").write_bytes(b"payload")

    def streams(path: Path) -> tuple[str, ...]:
        if path == target:
            return ("::$DATA", ":review:$DATA")
        return ("::$DATA",)

    monkeypatch.setattr(
        "muteinous.infrastructure.storage._filesystem._enumerate_streams",
        streams,
        raising=False,
    )
    with pytest.raises(StorageError, match="alternate data stream"):
        walk_files(tmp_path, controlled_root=tmp_path)


def test_walk_files_fails_closed_on_stream_enumeration_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail_enumeration(path: Path) -> tuple[str, ...]:
        raise StorageError(f"Cannot enumerate streams: {path}")

    monkeypatch.setattr(
        "muteinous.infrastructure.storage._filesystem._enumerate_streams",
        fail_enumeration,
        raising=False,
    )
    with pytest.raises(StorageError, match="Cannot enumerate streams"):
        walk_files(tmp_path, allow_empty=True, controlled_root=tmp_path)


def test_metadata_rejects_case_variant_integrity_metadata(tmp_path: Path) -> None:
    (tmp_path / "Integrity.JSON").write_bytes(b"producer metadata")
    with pytest.raises(StorageError, match="Ambiguous reserved"):
        _metadata(
            tmp_path,
            "scan",
            "0" * 32,
            ResultIdentity("source", "config", "generation"),
            controlled_root=tmp_path,
        )


def _stat_namespace(info: object, **changes: int) -> SimpleNamespace:
    names = (
        "st_size",
        "st_mtime_ns",
        "st_ctime_ns",
        "st_ino",
        "st_dev",
    )
    values = {name: getattr(info, name) for name in names}
    values.update(changes)
    return SimpleNamespace(**values)


def test_file_record_rejects_read_length_different_from_initial_stat(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    member = tmp_path / "member.bin"
    member.write_bytes(b"payload")
    original_checked_stat = checked_stat

    def oversized_initial_stat(path: Path, *, directory: bool) -> object:
        info = original_checked_stat(path, directory=directory)
        if path == member and not directory:
            return _stat_namespace(info, st_size=info.st_size + 1)
        return info

    monkeypatch.setattr(
        "muteinous.infrastructure.storage._filesystem.checked_stat",
        oversized_initial_stat,
    )
    with pytest.raises(StorageError, match="File changed"):
        file_record(tmp_path, member)


@pytest.mark.parametrize(
    ("field", "attribute"),
    [
        ("mtime", "st_mtime_ns"),
        ("ctime", "st_ctime_ns"),
        ("inode", "st_ino"),
        ("device", "st_dev"),
    ],
)
def test_file_record_rejects_changed_stat_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    attribute: str,
) -> None:
    member = tmp_path / "member.bin"
    member.write_bytes(b"payload")
    original_checked_stat = checked_stat
    calls = 0

    def changed_final_stat(path: Path, *, directory: bool) -> object:
        nonlocal calls
        info = original_checked_stat(path, directory=directory)
        if path == member and not directory:
            calls += 1
            if calls == 2:
                return _stat_namespace(
                    info, **{attribute: getattr(info, attribute) + 1}
                )
        return info

    monkeypatch.setattr(
        "muteinous.infrastructure.storage._filesystem.checked_stat",
        changed_final_stat,
    )
    with pytest.raises(StorageError, match="File changed"):
        file_record(tmp_path, member)


@pytest.mark.parametrize("mode", ["path", "controlled-path", "controlled-root"])
def test_checked_directory_rejects_parent_components(tmp_path: Path, mode: str) -> None:
    root = tmp_path / "root"
    (root / "staging").mkdir(parents=True)
    (root / "outside").mkdir()
    boundary: Path | None
    if mode == "controlled-root":
        boundary = tmp_path / "parent" / ".." / "root"
        checked_path = boundary / "staging"
    else:
        checked_path = root / "staging" / ".." / "outside"
        boundary = root if mode == "controlled-path" else None
    with pytest.raises(StorageError, match="parent|traversal"):
        checked_directory(checked_path, root=boundary)


def test_preflight_rejects_parent_components_before_normalizing(tmp_path: Path) -> None:
    root = tmp_path / "root"
    (root / "staging").mkdir(parents=True)
    traversing_directory = root / "staging" / ".." / "staging"
    with pytest.raises(StorageError, match="parent|traversal"):
        preflight([SpaceRequirement(traversing_directory, 0)], root=root)


@pytest.mark.parametrize(
    ("available", "minimum", "estimate", "shortage", "uncertain"),
    [
        (10, 10, 10, False, False),
        (9, 10, None, True, None),
        (10, 1, 10, False, False),
        (10, 1, 11, False, True),
    ],
)
def test_preflight_exact_space_boundaries(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    available: int,
    minimum: int,
    estimate: int | None,
    shortage: bool,
    uncertain: bool | None,
) -> None:
    monkeypatch.setattr(
        "muteinous.infrastructure.storage.space.shutil.disk_usage",
        lambda path: SimpleNamespace(free=available),
    )
    requirement = SpaceRequirement(tmp_path, minimum, estimate)
    if shortage:
        with pytest.raises(InsufficientSpace):
            preflight([requirement])
        return

    (assessment,) = preflight([requirement])
    assert assessment.available == available
    assert assessment.minimum == minimum
    assert assessment.uncertain is uncertain
