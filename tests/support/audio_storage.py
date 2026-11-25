"""Reusable in-memory-behavior fake for exercising injected audio storage."""

from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from pathlib import Path

from muteinous.core.audio.pcm import BLOCK_FRAMES, PCMFormat
from muteinous.core.audio.storage import Reader

FAKE_STORAGE_MARKER = b"fake-pcm-storage-v1\n"


class FakeReader:
    def __init__(
        self, info: PCMFormat, data: bytes, events: list[str] | None = None
    ) -> None:
        self.info = info
        self._data = data
        self._events = events

    def blocks(self) -> Iterator[bytes]:
        block_size = BLOCK_FRAMES * self.info.frame_bytes
        for index, offset in enumerate(range(0, len(self._data), block_size)):
            if self._events is not None:
                self._events.append(f"read:{index}")
            yield self._data[offset : offset + block_size]


class FakeStorage:
    def __init__(self, supported: bool = True, events: list[str] | None = None) -> None:
        self.supported = supported
        self.events = events
        self.support_calls: list[PCMFormat] = []
        self.write_paths: list[Path] = []
        self.open_paths: list[Path] = []
        self._infos: dict[Path, PCMFormat] = {}

    def supports(self, info: PCMFormat) -> bool:
        self.support_calls.append(info)
        return self.supported

    def write(self, path: Path, info: PCMFormat, blocks: Iterable[bytes]) -> None:
        self.write_paths.append(path)
        with path.open("xb") as stream:
            stream.write(FAKE_STORAGE_MARKER)
            for index, block in enumerate(blocks):
                if self.events is not None:
                    self.events.append(f"write:{index}")
                stream.write(block)
        self._infos[path] = info

    @contextmanager
    def open(self, path: Path) -> Iterator[Reader]:
        self.open_paths.append(path)
        with path.open("rb") as stream:
            encoded = stream.read()
        if not encoded.startswith(FAKE_STORAGE_MARKER):
            raise ValueError("not a fake-storage file")
        yield FakeReader(
            self._infos[path], encoded[len(FAKE_STORAGE_MARKER) :], self.events
        )
