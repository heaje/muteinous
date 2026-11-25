"""Narrow internal boundary for lossless intermediate storage (D06)."""

from collections.abc import Iterable, Iterator
from contextlib import AbstractContextManager
from pathlib import Path
from typing import Protocol

from .pcm import PCMFormat


class Reader(Protocol):
    @property
    def info(self) -> PCMFormat: ...

    def blocks(self) -> Iterator[bytes]:
        """Single-pass bounded PCM stream."""
        ...


class Storage(Protocol):
    def supports(self, info: PCMFormat) -> bool: ...

    def write(self, path: Path, info: PCMFormat, blocks: Iterable[bytes]) -> None:
        """Create an owned scratch file exclusively; remove failed output."""
        ...

    def open(self, path: Path) -> AbstractContextManager[Reader]: ...
