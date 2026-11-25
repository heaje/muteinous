"""Shared factories and fakes for storage unit and integration tests."""

from __future__ import annotations

import ctypes
import os
import subprocess
import sys
from collections.abc import Callable, Iterable, Iterator
from pathlib import Path
from types import SimpleNamespace

import pytest

import muteinous.infrastructure.storage._filesystem as filesystem
from muteinous.infrastructure.storage._filesystem import StorageError
from muteinous.infrastructure.storage.bundles import (
    ResultIdentity,
    ResultStore,
    Selection,
)

IDENTITY = ResultIdentity("source-a", "config-a", "generation-a")


def validate_domain(path: Path) -> None:
    if not (path / "payload.bin").is_file():
        raise StorageError("Domain requires a payload")


def publish(store: ResultStore, data: bytes = b"original") -> Selection:
    expected = store.selection("scan")
    with store.stage("job") as stage:
        (stage.path / "payload.bin").write_bytes(data)
        return store.publish(
            stage,
            "scan",
            IDENTITY,
            expected=expected,
            is_current=lambda: True,
            validate_domain=validate_domain,
        )


def read(store: ResultStore, identity: ResultIdentity = IDENTITY) -> bytes:
    with store.open_current("scan", identity, validate_domain=validate_domain) as path:
        return (path / "payload.bin").read_bytes()


def make_directory_link(link: Path, target: Path) -> None:
    if sys.platform == "win32":
        # NTFS junctions do not require the symlink-creation privilege.
        subprocess.run(
            ["cmd.exe", "/d", "/c", "mklink", "/J", str(link), str(target)],
            check=True,
            capture_output=True,
            timeout=10,
        )
    else:
        link.symlink_to(target, target_is_directory=True)


class _FakeWinFunction:
    def __init__(self, callback: Callable[..., object]) -> None:
        self.callback = callback
        self.argtypes: object = None
        self.restype: object = None

    def __call__(self, *args: object) -> object:
        return self.callback(*args)


def install_fake_stream_api(
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


def install_directory_listing(
    monkeypatch: pytest.MonkeyPatch, root: Path, entries: Iterable[Path]
) -> None:
    selected = tuple(entries)
    original_iterdir = Path.iterdir

    def listing(path: Path) -> Iterator[Path]:
        if path == root:
            return iter(selected)
        return original_iterdir(path)

    monkeypatch.setattr("pathlib.Path.iterdir", listing)


def stat_namespace(info: os.stat_result, **changes: int) -> SimpleNamespace:
    names = ("st_size", "st_mtime_ns", "st_ctime_ns", "st_ino", "st_dev")
    values = {name: getattr(info, name) for name in names}
    values.update(changes)
    return SimpleNamespace(**values)
