"""Sequential, owned audio scratch; never a game-facing or result-store path."""

import tempfile
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from muteinous.infrastructure.platform.file_lock import lock_exclusive

from .pcm import Curve, PCMFormat, censor_blocks
from .storage import Storage

_MARKER = b"muteinous-audio-v1\n"
_AUDIO_FILES = ("source.pcmstore", "edited.pcmstore")


@dataclass(frozen=True)
class Scratch:
    directory: Path
    storage: Storage

    def write_source(self, info: PCMFormat, blocks: Iterable[bytes]) -> Path:
        path = self.directory / "source.pcmstore"
        if not self.storage.supports(info):
            raise ValueError("unsupported lossless intermediate representation")
        self.storage.write(path, info, blocks)
        return path

    def edit(
        self,
        ranges: Iterable[tuple[float, float]],
        *,
        before: float = 0,
        after: float = 0,
        fade: float = 0,
        curve: Curve = "cosine",
    ) -> Path:
        path = self.directory / "edited.pcmstore"
        if path.exists() or path.is_symlink():
            raise FileExistsError(path)
        written = False
        try:
            with self.storage.open(self.directory / "source.pcmstore") as reader:
                self.storage.write(
                    path,
                    reader.info,
                    censor_blocks(
                        reader.info,
                        reader.blocks(),
                        ranges,
                        before=before,
                        after=after,
                        fade=fade,
                        curve=curve,
                    ),
                )
                written = True
        except BaseException as error:
            # Even a decoder close failure invalidates the entire edited scratch.
            if written:
                try:
                    path.unlink(missing_ok=True)
                except BaseException as cleanup_error:
                    error.add_note(
                        f"failed to remove invalid edited audio {path}: "
                        f"{cleanup_error!r}"
                    )
            raise
        return path


@contextmanager
def audio_scratch(root: Path, storage: Storage) -> Iterator[Scratch]:
    """Root must be a dedicated application-owned scratch directory, not user data."""
    root.mkdir(parents=True, exist_ok=True)
    if root.is_symlink() or root.is_junction():
        raise ValueError("scratch root must not be a link")
    cleanup_abandoned(root)
    directory = Path(tempfile.mkdtemp(prefix="audio-", dir=root))
    try:
        with (directory / "owner.lock").open("xb+") as lock:
            lock.write(b"1")
            lock.flush()
            lock_exclusive(lock)
            marker = directory / "ready"
            marker.write_bytes(_MARKER)
            body_error: BaseException | None = None
            try:
                try:
                    yield Scratch(directory, storage)
                except BaseException as error:
                    body_error = error
                    raise
            finally:
                try:
                    for name in _AUDIO_FILES:
                        (directory / name).unlink(missing_ok=True)
                    marker.unlink()
                except BaseException as cleanup_error:
                    if body_error is None:
                        raise
                    body_error.add_note(
                        f"failed to clean audio scratch {directory}: {cleanup_error!r}"
                    )
    finally:
        # If deletion failed, keep the marker for a later cleanup attempt.
        if not (directory / "ready").exists():
            (directory / "owner.lock").unlink(missing_ok=True)
            directory.rmdir()


def cleanup_abandoned(root: Path) -> None:
    """Only reclaim recognizable, unlocked scratch; ambiguous entries are left alone."""
    if root.is_symlink() or root.is_junction():
        return
    for directory in root.glob("audio-*"):
        try:
            if (
                directory.is_symlink()
                or directory.is_junction()
                or not directory.is_dir()
            ):
                continue
            entries = {p.name: p for p in directory.iterdir()}
            if not {"owner.lock", "ready"} <= entries.keys() or not entries.keys() <= {
                "owner.lock",
                "ready",
                *_AUDIO_FILES,
            }:
                continue
            if any(p.is_symlink() or not p.is_file() for p in entries.values()):
                continue
            marker = entries["ready"]
            with entries["owner.lock"].open("rb+") as lock:
                lock_exclusive(lock)
                if (
                    marker.stat().st_size != len(_MARKER)
                    or marker.read_bytes() != _MARKER
                ):
                    continue
                # No processing owner can reattach to a published scratch directory.
                for name in _AUDIO_FILES:
                    (directory / name).unlink(missing_ok=True)
                marker.unlink()
            (directory / "owner.lock").unlink()
            directory.rmdir()
        except OSError:
            continue
