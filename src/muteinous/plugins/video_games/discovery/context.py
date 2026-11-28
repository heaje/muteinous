"""Shared discovery validation, accounting and cancellation."""

from __future__ import annotations

import ntpath
import os
import stat
from collections.abc import Iterator
from dataclasses import dataclass, field, replace
from pathlib import Path

from muteinous.infrastructure.platform.environment import CURRENT_OS, OperatingSystem

from .models import Cancel, Candidate, DiscoveryCancelled, Source

_MAX_ENTRIES = 4096
_MAX_METADATA = 1024 * 1024
_MAX_TOTAL_METADATA = 16 * _MAX_METADATA


class _LimitReached(Exception):
    pass


def _never_cancel() -> bool:
    return False


def _check(cancelled: Cancel) -> None:
    if cancelled():
        raise DiscoveryCancelled


@dataclass
class DiscoveryContext:
    cancelled: Cancel
    os: OperatingSystem = CURRENT_OS
    candidates: list[Candidate] = field(default_factory=list)
    issues: list[str] = field(default_factory=list)
    identities: dict[str, int] = field(default_factory=dict)
    entries: int = 0
    bytes_read: int = 0
    truncated: bool = False

    def step(self) -> None:
        _check(self.cancelled)
        if self.entries >= _MAX_ENTRIES:
            raise _LimitReached
        self.entries += 1

    def issue(self, location: object, detail: str) -> None:
        self.issues.append(f"{location}: {detail}")

    def add(self, location: object, name: object, source: Source) -> None:
        _check(self.cancelled)
        if not isinstance(location, (str, Path)) or not str(location).strip():
            self.issue(source, "missing or invalid installation path")
            return
        path = Path(location)
        if not _valid_path(path):
            self.issue(source, "invalid installation path")
            return
        label = path.name
        if isinstance(name, str) and name.strip():
            if _valid_text(name):
                label = name
            else:
                self.issue(source, "invalid installation display name")
        candidate, identity = _candidate(path, label, source)
        if identity is not None and identity in self.identities:
            index = self.identities[identity]
            previous = self.candidates[index]
            if source not in previous.sources:
                self.candidates[index] = replace(
                    previous, sources=(*previous.sources, source)
                )
        else:
            if identity is not None:
                self.identities[identity] = len(self.candidates)
            self.candidates.append(candidate)

    def read(self, path: Path) -> str:
        _check(self.cancelled)
        remaining = _MAX_TOTAL_METADATA - self.bytes_read
        if remaining <= 0:
            raise _LimitReached
        limit = min(remaining, _MAX_METADATA)
        parent = path.parent.lstat()
        if not _ordinary(parent) or not stat.S_ISDIR(parent.st_mode):
            raise ValueError("metadata parent is not an ordinary directory")
        info = path.lstat()
        if not _ordinary(info) or not stat.S_ISREG(info.st_mode):
            raise ValueError("metadata is not an ordinary file")
        if info.st_size > limit:
            self.truncated = True
            raise ValueError("metadata exceeds read limit")
        with path.open("rb", buffering=0) as stream:
            raw = stream.read(limit + 1)
        self.bytes_read += len(raw)
        _check(self.cancelled)
        if len(raw) > limit:
            self.truncated = True
            raise ValueError("metadata exceeds read limit")
        return raw.decode("utf-8-sig")

    def files(self, directory: Path) -> Iterator[Path]:
        _check(self.cancelled)
        try:
            info = directory.lstat()
            if not _ordinary(info) or not stat.S_ISDIR(info.st_mode):
                raise ValueError("metadata directory is not an ordinary directory")
            with os.scandir(directory) as entries:
                for entry in entries:
                    self.step()
                    yield Path(entry.path)
        except (OSError, ValueError) as error:
            self.issue(directory, str(error))


def _ordinary(info: os.stat_result) -> bool:
    # Do not follow symlinks or Windows junctions/reparse points during probes.
    return not (
        stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400
    )


def _valid_text(value: str) -> bool:
    return "\x00" not in value and not any(
        0xD800 <= ord(char) <= 0xDFFF for char in value
    )


def _valid_component(value: str) -> bool:
    """Accept one ordinary host-filesystem path component, not a path."""
    if (
        not value.strip()
        or value in (".", "..")
        or "/" in value
        or not _valid_text(value)
    ):
        return False
    if os.name == "nt":
        return "\\" not in value and ":" not in value and not ntpath.isreserved(value)
    return True


def _valid_path(path: Path) -> bool:
    if not path.is_absolute() or ".." in path.parts or not _valid_text(str(path)):
        return False
    if os.name == "nt":
        if path.anchor.startswith(("\\\\?\\", "\\\\.\\")):
            return False
        if any(ntpath.isreserved(part) for part in path.parts[1:]):
            return False
    return True


def _candidate(path: Path, name: str, source: Source) -> tuple[Candidate, str | None]:
    try:
        identity = path.resolve(strict=True)
        if not stat.S_ISDIR(identity.stat().st_mode):
            return Candidate(path, name, (source,), "missing"), None
    except FileNotFoundError, NotADirectoryError:
        return Candidate(path, name, (source,), "missing"), None
    except OSError, RuntimeError, ValueError:
        return Candidate(path, name, (source,), "inaccessible"), None
    return Candidate(path, name, (source,), "available"), str(identity)


def _object(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError("expected metadata object")
    return value
