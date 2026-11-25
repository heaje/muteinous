"""Deterministic result integrity and safe-path unit checks."""

import ctypes
import hashlib
import ntpath
import os
import stat
from collections.abc import Callable, Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest

import muteinous.infrastructure.storage._filesystem as filesystem
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


class _FakeWinFunction:
    def __init__(self, callback: Callable[..., object]) -> None:
        self.callback = callback
        self.argtypes: object = None
        self.restype: object = None

    def __call__(self, *args: object) -> object:
        return self.callback(*args)


def _install_fake_stream_api(
    monkeypatch: pytest.MonkeyPatch,
    *,
    first_error: int | None = None,
    next_error: int = 38,
    next_raises: bool = False,
    close_error: int | None = None,
) -> dict[str, int]:
    state = {"last_error": 0, "close_calls": 0}

    def find_first(*args: object) -> object:
        if first_error is not None:
            state["last_error"] = first_error
            return ctypes.c_void_p(-1).value
        return 1234

    def find_next(*args: object) -> object:
        if next_raises:
            raise OSError("synthetic FindNextStreamW failure")
        state["last_error"] = next_error
        return 0

    def find_close(*args: object) -> object:
        state["close_calls"] += 1
        if close_error is not None:
            state["last_error"] = close_error
            return 0
        return 1

    kernel32 = SimpleNamespace(
        FindFirstStreamW=_FakeWinFunction(find_first),
        FindNextStreamW=_FakeWinFunction(find_next),
        FindClose=_FakeWinFunction(find_close),
    )
    monkeypatch.setattr(filesystem, "sys", SimpleNamespace(platform="win32"))
    monkeypatch.setattr(
        ctypes,
        "WinDLL",
        lambda name, *, use_last_error: kernel32,
        raising=False,
    )
    monkeypatch.setattr(
        ctypes,
        "get_last_error",
        lambda: state["last_error"],
        raising=False,
    )
    monkeypatch.setattr(
        ctypes,
        "set_last_error",
        lambda error: state.__setitem__("last_error", error),
        raising=False,
    )
    return state


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
    ("error", "no_streams"),
    [(38, True), (87, True), (5, False), (120, False), (1, False), (50, False)],
)
def test_windows_stream_first_call_error_mapping(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    error: int,
    no_streams: bool,
) -> None:
    state = _install_fake_stream_api(monkeypatch, first_error=error)
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
    state = _install_fake_stream_api(monkeypatch, next_error=error)
    if refused:
        with pytest.raises(StorageError, match="Windows error"):
            filesystem._enumerate_windows_streams(tmp_path)
    else:
        filesystem._enumerate_windows_streams(tmp_path)
    assert state["close_calls"] == 1


def test_windows_stream_next_exception_closes_handle_and_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = _install_fake_stream_api(monkeypatch, next_raises=True)
    with pytest.raises(StorageError, match="Cannot enumerate data streams"):
        filesystem._enumerate_windows_streams(tmp_path)
    assert state["close_calls"] == 1


def test_windows_stream_close_failure_is_storage_error_and_closed_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = _install_fake_stream_api(monkeypatch, close_error=5)
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


def test_safe_name_allows_space_inside_component() -> None:
    safe_name("name with spaces.txt")


def test_safe_name_rejects_unencodable_utf8_component() -> None:
    with pytest.raises(StorageError, match="valid UTF-8"):
        safe_name("\ud800")


def test_walk_files_rejects_unencodable_utf8_component(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    unsafe = tmp_path / "\ud800"

    def unsafe_listing(path: Path) -> Iterator[Path]:
        if path == tmp_path:
            return iter([unsafe])
        return path.iterdir()

    monkeypatch.setattr("pathlib.Path.iterdir", unsafe_listing)
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


@pytest.mark.parametrize(
    ("minimum", "estimate"),
    [
        (-1, None),
        (True, None),
        (1.5, None),
        (5, 4),
        (1, True),
        (1, 1.5),
    ],
)
def test_space_requirement_rejects_invalid_bounds(
    tmp_path: Path, minimum: int, estimate: int | None
) -> None:
    with pytest.raises(ValueError, match="Invalid space requirement"):
        SpaceRequirement(tmp_path, minimum, estimate)


@pytest.mark.parametrize("field_index", [0, 1, 2])
@pytest.mark.parametrize(
    ("value", "error"),
    [("", ValueError), (None, ValueError), ("\ud800", UnicodeEncodeError)],
)
def test_result_identity_rejects_invalid_values_in_each_field(
    field_index: int, value: object, error: type[Exception]
) -> None:
    values: list[object] = ["source", "configuration", "generation"]
    values[field_index] = value
    with pytest.raises(error):
        ResultIdentity(*cast(tuple[str, str, str], tuple(values)))


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


def test_walk_files_rejects_unicode_casefold_collision(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = tmp_path / "\u00df"
    second = tmp_path / "ss"
    backing_file = tmp_path / "backing.bin"
    backing_file.write_bytes(b"fixture")
    backing_info = backing_file.lstat()
    original_lstat = Path.lstat

    def collision_listing(path: Path) -> Iterator[Path]:
        if path == tmp_path:
            return iter([first, second])
        return path.iterdir()

    def synthetic_lstat(path: Path) -> os.stat_result:
        if path in {first, second}:
            return backing_info
        return original_lstat(path)

    monkeypatch.setattr("pathlib.Path.iterdir", collision_listing)
    monkeypatch.setattr(Path, "lstat", synthetic_lstat)
    monkeypatch.setattr(filesystem, "_enumerate_streams", lambda path: ("::$DATA",))
    with pytest.raises(StorageError, match="Ambiguous path"):
        walk_files(tmp_path, controlled_root=tmp_path)


def test_extended_windows_path_handles_drive_unc_prefix_and_relative_paths(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("muteinous.infrastructure.storage._filesystem.os.path", ntpath)

    assert (
        filesystem._extended_windows_path(Path(r"C:\results\bundle"))
        == r"\\?\C:\results\bundle"
    )
    prefixed = r"\\?\C:\already\extended"
    assert filesystem._extended_windows_path(Path(prefixed)) == prefixed
    assert (
        filesystem._extended_windows_path(Path(r"\\server\share\x"))
        == r"\\?\UNC\server\share\x"
    )

    relative = filesystem._extended_windows_path(Path(r"relative\result"))
    absolute_without_prefix = relative.removeprefix("\\\\?\\")
    assert ntpath.isabs(absolute_without_prefix)
    assert absolute_without_prefix == ntpath.abspath(r"relative\result")


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


def test_checked_directory_rejects_path_outside_controlled_root(
    tmp_path: Path,
) -> None:
    controlled = tmp_path / "inside"
    outside = tmp_path / "outside"
    controlled.mkdir()
    outside.mkdir()
    with pytest.raises(StorageError, match="outside controlled root"):
        checked_directory(outside, root=controlled)


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


def test_preflight_uses_lowest_free_space_report_on_same_device(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    free = {first: 20, second: 8}

    monkeypatch.setattr(
        "muteinous.infrastructure.storage.space.checked_directory",
        lambda path, *, root=None: SimpleNamespace(st_dev=7),
    )
    monkeypatch.setattr(
        "muteinous.infrastructure.storage.space.shutil.disk_usage",
        lambda path: SimpleNamespace(free=free[path]),
    )
    (assessment,) = preflight(
        [
            SpaceRequirement(first, 2, 3),
            SpaceRequirement(second, 3, 4),
        ]
    )
    assert assessment.available == 8
    assert assessment.minimum == 5
    assert assessment.estimate == 7


def test_preflight_groups_and_checks_each_device_independently(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = tmp_path / "device-one-a"
    second = tmp_path / "device-one-b"
    third = tmp_path / "device-two"
    first.mkdir()
    second.mkdir()
    third.mkdir()
    devices = {first: 11, second: 11, third: 22}
    free = {first: 8, second: 12, third: 7}

    def checked_device(path: Path, *, root: Path | None = None) -> SimpleNamespace:
        return SimpleNamespace(st_dev=devices[path])

    monkeypatch.setattr(
        "muteinous.infrastructure.storage.space.checked_directory", checked_device
    )
    monkeypatch.setattr(
        "muteinous.infrastructure.storage.space.shutil.disk_usage",
        lambda path: SimpleNamespace(free=free[path]),
    )
    assessments = preflight(
        [
            SpaceRequirement(first, 2, 3),
            SpaceRequirement(second, 3, 4),
            SpaceRequirement(third, 6, 7),
        ]
    )
    assert [
        (
            assessment.directory,
            assessment.available,
            assessment.minimum,
            assessment.estimate,
        )
        for assessment in assessments
    ] == [(first, 8, 5, 7), (third, 7, 6, 7)]
