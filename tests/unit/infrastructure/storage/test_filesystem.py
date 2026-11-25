"""Storage unit tests for the corresponding infrastructure module."""

from __future__ import annotations

import os
import stat
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest

import muteinous.infrastructure.storage._filesystem as filesystem
from muteinous.infrastructure.storage._filesystem import (
    StorageError,
    checked_directory,
    checked_stat,
    file_record,
    is_digest,
    read_json,
    read_regular,
    safe_name,
    walk_files,
)
from tests.support.storage import (
    install_directory_listing,
    install_fake_stream_api,
    make_directory_link,
    stat_namespace,
)

pytestmark = pytest.mark.portable


@pytest.mark.parametrize(
    ("error", "no_streams"),
    [(38, True), (87, True), (5, False), (120, False), (1, False), (50, False)],
)
def test_windows_stream_first_call_error_mapping(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    error: int,
    no_streams: bool,
) -> None:
    state = install_fake_stream_api(monkeypatch, first_error=error)
    if no_streams:
        assert filesystem._enumerate_windows_streams(tmp_path) == ()
    else:
        with pytest.raises(StorageError, match="Windows error"):
            filesystem._enumerate_windows_streams(tmp_path)
    assert state["close_calls"] == 0


@pytest.mark.parametrize(("error", "refused"), [(38, False), (5, True), (87, True)])
def test_windows_stream_next_error_mapping_and_handle_close(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    error: int,
    refused: bool,
) -> None:
    state = install_fake_stream_api(monkeypatch, next_error=error)
    if refused:
        with pytest.raises(StorageError, match="Windows error"):
            filesystem._enumerate_windows_streams(tmp_path)
    else:
        filesystem._enumerate_windows_streams(tmp_path)
    assert state["close_calls"] == 1


def test_windows_stream_next_exception_closes_handle_and_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = install_fake_stream_api(monkeypatch, next_raises=True)
    with pytest.raises(StorageError, match="Cannot enumerate data streams"):
        filesystem._enumerate_windows_streams(tmp_path)
    assert state["close_calls"] == 1


def test_windows_stream_close_failure_is_storage_error_and_closed_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = install_fake_stream_api(monkeypatch, close_error=5)
    with pytest.raises(StorageError, match="Cannot close data-stream enumeration"):
        filesystem._enumerate_windows_streams(tmp_path)
    assert state["close_calls"] == 1


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
        "PRN",
        "AUX",
        "PRN.txt",
        "AUX.txt",
        "prn.txt",
        "COM1",
        "COM¹",
        "COM²",
        "COM³",
        "LPT¹",
        "LPT²",
        "LPT³",
        "CONIN$",
        "CONOUT$",
        "x.",
        "x ",
        "a\x00",
        "control\x1fcharacter",
    ],
)
def test_unsafe_path_components_are_rejected(name: str) -> None:
    with pytest.raises(StorageError):
        safe_name(name)


@pytest.mark.parametrize(
    "name", ["name with spaces.txt", "COMA", "LPTX", "CONSOLE", "com10"]
)
def test_safe_name_allows_valid_names(name: str) -> None:
    safe_name(name)


def test_safe_name_rejects_unencodable_utf8_component() -> None:
    with pytest.raises(StorageError, match="valid UTF-8"):
        safe_name("\ud800")


def test_walk_files_rejects_unencodable_utf8_component(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    unsafe = tmp_path / "\ud800"
    install_directory_listing(monkeypatch, tmp_path, [unsafe])
    with pytest.raises(StorageError, match="valid UTF-8"):
        walk_files(tmp_path, controlled_root=tmp_path)


def test_checked_stat_rejects_fifo_as_nonregular_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    entry = tmp_path / "fifo"
    synthetic = os.stat_result((stat.S_IFIFO | 0o600, 1, 1, 1, 0, 0, 0, 0, 0, 0))
    fifo = cast(
        os.stat_result,
        SimpleNamespace(
            st_mode=synthetic.st_mode,
            st_nlink=synthetic.st_nlink,
            st_file_attributes=0,
        ),
    )
    original_lstat = Path.lstat

    def synthetic_lstat(path: Path) -> os.stat_result:
        if path == entry:
            return fifo
        return original_lstat(path)

    monkeypatch.setattr(Path, "lstat", synthetic_lstat)
    with pytest.raises(StorageError, match="Unexpected filesystem entry"):
        checked_stat(entry, directory=False)


def test_checked_stat_rejects_directory_where_file_expected(tmp_path: Path) -> None:
    directory = tmp_path / "directory"
    directory.mkdir()
    with pytest.raises(StorageError, match="Unexpected filesystem entry"):
        checked_stat(directory, directory=False)


def test_walk_files_rejects_casefold_collisions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = tmp_path / "payload.bin"
    second = tmp_path / "PAYLOAD.BIN"
    first.write_bytes(b"one")
    if not second.exists():
        second.write_bytes(b"two")

    install_directory_listing(monkeypatch, tmp_path, [first, second])
    with pytest.raises(StorageError, match="Ambiguous path"):
        walk_files(tmp_path, controlled_root=tmp_path)


def test_walk_files_rejects_unicode_casefold_collision(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = tmp_path / "\u00df"
    second = tmp_path / "ss"
    backing_file = tmp_path / "backing.bin"
    backing_file.write_bytes(b"fixture")
    backing_info = backing_file.lstat()
    original_lstat = Path.lstat

    def synthetic_lstat(path: Path) -> os.stat_result:
        if path in {first, second}:
            return backing_info
        return original_lstat(path)

    install_directory_listing(monkeypatch, tmp_path, [first, second])
    monkeypatch.setattr(Path, "lstat", synthetic_lstat)
    monkeypatch.setattr(filesystem, "_enumerate_streams", lambda path: ("::$DATA",))
    with pytest.raises(StorageError, match="Ambiguous path"):
        walk_files(tmp_path, controlled_root=tmp_path)


def test_walk_files_rejects_unsafe_inventory_names(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    unsafe = tmp_path / "NUL.txt"
    install_directory_listing(monkeypatch, tmp_path, [unsafe])
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


@pytest.mark.parametrize(
    ("evidence", "field", "attribute"),
    [
        ("initial-size", None, None),
        ("changed-stat", "mtime", "st_mtime_ns"),
        ("changed-stat", "ctime", "st_ctime_ns"),
        ("changed-stat", "inode", "st_ino"),
        ("changed-stat", "device", "st_dev"),
    ],
)
def test_file_record_rejects_unstable_inventory_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    evidence: str,
    field: str | None,
    attribute: str | None,
) -> None:
    member = tmp_path / "member.bin"
    member.write_bytes(b"payload")
    original_checked_stat = checked_stat
    calls = 0

    def changed_stat(path: Path, *, directory: bool) -> object:
        nonlocal calls
        info = original_checked_stat(path, directory=directory)
        if path == member and not directory:
            calls += 1
            if evidence == "initial-size" and calls == 1:
                return stat_namespace(info, st_size=info.st_size + 1)
            if evidence == "changed-stat" and calls == 2:
                assert field is not None and attribute is not None
                return stat_namespace(info, **{attribute: getattr(info, attribute) + 1})
        return info

    monkeypatch.setattr(
        "muteinous.infrastructure.storage._filesystem.checked_stat",
        changed_stat,
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


def test_checked_directory_rejects_path_outside_controlled_root(
    tmp_path: Path,
) -> None:
    controlled = tmp_path / "inside"
    outside = tmp_path / "outside"
    controlled.mkdir()
    outside.mkdir()
    with pytest.raises(StorageError, match="outside controlled root"):
        checked_directory(outside, root=controlled)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (123, False),
        (None, False),
        ([], False),
        ("0" * 63, False),
        ("A" * 64, False),
        ("g" * 64, False),
        ("a" * 64, True),
    ],
)
def test_is_digest_validation(value: object, expected: bool) -> None:
    assert is_digest(value) is expected


def test_filesystem_helpers_work_without_controlled_root(tmp_path: Path) -> None:
    directory = tmp_path / "uncontrolled"
    directory.mkdir()
    member = directory / "member.bin"
    member.write_bytes(b"payload")

    assert checked_directory(directory).st_dev == directory.stat().st_dev
    assert read_regular(member) == b"payload"
    assert walk_files(directory) == [member]


@pytest.mark.parametrize("helper", ["checked_directory", "read_regular", "walk_files"])
def test_filesystem_helpers_without_root_reject_parent_components(
    tmp_path: Path, helper: str
) -> None:
    directory = tmp_path / "root"
    directory.mkdir()
    member = directory / "member.bin"
    member.write_bytes(b"payload")
    traversing_directory = directory / ".." / "root"

    with pytest.raises(StorageError, match="Parent traversal"):
        if helper == "checked_directory":
            checked_directory(traversing_directory)
        elif helper == "read_regular":
            read_regular(traversing_directory / "member.bin")
        else:
            walk_files(traversing_directory)


def test_filesystem_helpers_without_root_reject_linked_paths(tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.mkdir()
    member = target / "member.bin"
    member.write_bytes(b"payload")
    linked = tmp_path / "linked"
    make_directory_link(linked, target)

    with pytest.raises(StorageError, match="Unsafe link"):
        checked_directory(linked)
    with pytest.raises(StorageError, match="Unsafe link"):
        read_regular(linked / "member.bin")
    with pytest.raises(StorageError, match="Unsafe link"):
        walk_files(linked)
