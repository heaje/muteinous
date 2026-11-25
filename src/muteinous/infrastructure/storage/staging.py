"""Private per-job staging and conservative abandoned-work cleanup."""

from __future__ import annotations

import errno
import os
import shutil
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO
from uuid import uuid4

from ._filesystem import (
    StorageError,
    canonical_json,
    checked_directory,
    checked_stat,
    is_token,
    read_json,
    read_regular,
    walk_files,
)
from .space import SpaceAssessment, translate_write_error

_OWNER = "owner.json"


@contextmanager
def try_lock(path: Path, *, root: Path | None = None) -> Iterator[BinaryIO | None]:
    """An OS-held exclusive nonblocking lease, released even on process exit."""
    checked_directory(path.parent, root=root)
    if checked_stat(path, directory=False).st_size < 1:
        raise StorageError(f"Empty lease file: {path}")
    with path.open("r+b") as stream:
        try:
            if sys.platform == "win32":
                import msvcrt

                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            if exc.errno not in {errno.EACCES, errno.EAGAIN, errno.EDEADLK}:
                raise
            yield None
        else:
            # Close releases the lease. The lock file itself is never unlinked.
            yield stream


@dataclass(frozen=True)
class CleanupReport:
    removed: tuple[str, ...]
    retained: tuple[tuple[str, str], ...]


class StagingArea:
    """Writable private payload; valid only inside its owning context."""

    def __init__(
        self,
        manager: Staging,
        directory: Path,
        assessments: tuple[SpaceAssessment, ...],
    ) -> None:
        self._manager = manager
        self._directory = directory
        self.space_assessments = assessments
        self._active = True
        self._published = False
        self._publisher_files: set[str] = set()

    @property
    def path(self) -> Path:
        if not self._active or self._published:
            raise StorageError("Staging area is no longer writable")
        return self._directory / "payload"


class Staging:
    def __init__(self, root: Path, leases: Path, *, controlled_root: Path) -> None:
        self.root = root
        self.leases = leases
        self.controlled_root = controlled_root
        self._session = uuid4().hex

    @contextmanager
    def create(
        self, job_id: str, assessments: tuple[SpaceAssessment, ...]
    ) -> Iterator[StagingArea]:
        if not isinstance(job_id, str) or not job_id:
            raise ValueError("A nonempty job identity is required")
        token = uuid4().hex
        marker = canonical_json(
            {
                "schema": 1,
                "stage": token,
                "session": self._session,
                "process": os.getpid(),
                "job": job_id,
            }
        )
        directory = self.root / token
        lease = self.leases / f"{token}.lock"
        try:
            checked_directory(self.root, root=self.controlled_root)
            checked_directory(self.leases, root=self.controlled_root)
            with lease.open("xb") as stream:
                stream.write(marker)
            with try_lock(lease, root=self.controlled_root) as held:
                if held is None:
                    raise StorageError("New staging lease could not be acquired")
                directory.mkdir()
                (directory / _OWNER).write_bytes(marker)
                (directory / "payload").mkdir()
                area = StagingArea(self, directory, assessments)
                try:
                    yield area
                finally:
                    area._active = False
        except OSError as exc:
            translate_write_error(exc)

    def cleanup_abandoned(self) -> CleanupReport:
        """Delete only marked, inactive, safely inspectable staging trees."""
        root_device = checked_directory(self.root, root=self.controlled_root).st_dev
        if (
            checked_directory(self.leases, root=self.controlled_root).st_dev
            != root_device
        ):
            raise StorageError("Staging lease directory is on another filesystem")
        removed: list[str] = []
        retained: list[tuple[str, str]] = []
        for directory in sorted(self.root.iterdir()):
            try:
                if not is_token(directory.name):
                    raise StorageError("Not an application staging identity")
                checked_directory(directory, root=self.controlled_root)
                raw = read_regular(directory / _OWNER, root=self.controlled_root)
                marker = read_json(raw)
                if (
                    set(marker) != {"schema", "stage", "session", "process", "job"}
                    or type(marker["schema"]) is not int
                    or marker["schema"] != 1
                    or marker["stage"] != directory.name
                    or not is_token(marker["session"])
                    or type(marker["process"]) is not int
                    or marker["process"] <= 0
                    or not isinstance(marker["job"], str)
                    or not marker["job"]
                ):
                    raise StorageError("Invalid staging ownership marker")
                lease = self.leases / f"{directory.name}.lock"
                with try_lock(lease, root=self.controlled_root) as held:
                    if held is None:
                        raise StorageError("Staging owner is active")
                    # Never infer abandonment from age or a reused PID.
                    # Windows locks the first byte; read through the held handle.
                    held.seek(0)
                    if (
                        held.read() != raw
                        or read_regular(directory / _OWNER, root=self.controlled_root)
                        != raw
                    ):
                        raise StorageError("Staging ownership evidence disagrees")
                    if (
                        checked_directory(directory, root=self.controlled_root).st_dev
                        != root_device
                    ):
                        raise StorageError("Staging directory is on another filesystem")
                    for entry in directory.iterdir():
                        if entry.name not in {_OWNER, "payload", "candidate.json"}:
                            raise StorageError("Unexpected entry at staging root")
                        checked_stat(entry, directory=entry.name == "payload")
                    walk_files(
                        directory,
                        allow_empty=True,
                        controlled_root=self.controlled_root,
                    )
                    shutil.rmtree(directory)
                removed.append(directory.name)
            except (OSError, StorageError) as exc:
                retained.append((directory.name, str(exc)))
        return CleanupReport(tuple(removed), tuple(retained))
