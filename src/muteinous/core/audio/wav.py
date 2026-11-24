"""Canonical WAVE extensible lossless scratch backend, not a native adapter."""

import errno
import os
import shutil
import struct
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import BinaryIO

from .pcm import BLOCK_FRAMES, PCMFormat, Representation, checked_blocks
from .storage import Reader

_HEADER = struct.Struct("<4sI4s4sIHHIIHHHHI16s4sII4sI")
_GUID_TAIL = b"\x00\x00\x10\x00\x80\x00\x00\xaa\x00\x38\x9b\x71"


def _header(info: PCMFormat) -> bytes:
    size = info.frames * info.frame_bytes
    total = _HEADER.size + size + size % 2
    if total - 8 > 0xFFFFFFFF or info.rate * info.frame_bytes > 0xFFFFFFFF:
        raise ValueError("PCM exceeds RIFF WAVE limits")
    bits = info.width * 8
    tag = 3 if info.representation.startswith("f") else 1
    return _HEADER.pack(
        b"RIFF",
        total - 8,
        b"WAVE",
        b"fmt ",
        40,
        0xFFFE,
        info.channels,
        info.rate,
        info.rate * info.frame_bytes,
        info.frame_bytes,
        bits,
        22,
        bits,
        info.channel_mask,
        struct.pack("<I", tag) + _GUID_TAIL,
        b"fact",
        4,
        info.frames,
        b"data",
        size,
    )


class _WaveReader:
    def __init__(self, stream: BinaryIO, info: PCMFormat) -> None:
        self._stream = stream
        self.info = info

    def blocks(self) -> Iterator[bytes]:
        remaining = self.info.frames
        while remaining:
            frames = min(remaining, BLOCK_FRAMES)
            size = frames * self.info.frame_bytes
            block = self._stream.read(size)
            if len(block) != size:
                raise ValueError("truncated PCM data")
            remaining -= frames
            yield block


class WaveStorage:
    """Only reads its own canonical WAVE layout, not arbitrary native WAV assets."""

    def supports(self, info: PCMFormat) -> bool:
        try:
            _header(info)
        except ValueError:
            return False
        return True

    def write(self, path: Path, info: PCMFormat, blocks: Iterable[bytes]) -> None:
        header = _header(info)
        size = info.frames * info.frame_bytes
        # Existing source scratch is already reflected in available space.
        if shutil.disk_usage(path.parent).free < len(header) + size + size % 2:
            raise OSError(errno.ENOSPC, "insufficient audio scratch space")
        # Exclusive creation; never truncate a pre-existing path. Only remove our file.
        stream = path.open("xb")
        try:
            with stream:
                stream.write(header)
                for block in checked_blocks(info, blocks):
                    stream.write(block)
                if size % 2:
                    stream.write(b"\x00")
            with self.open(path) as reader:
                if reader.info != info:
                    raise ValueError("written PCM metadata mismatch")
        except BaseException:
            path.unlink(missing_ok=True)
            raise

    @contextmanager
    def open(self, path: Path) -> Iterator[Reader]:
        with path.open("rb") as stream:
            raw = stream.read(_HEADER.size)
            if len(raw) != _HEADER.size:
                raise ValueError("truncated WAVE header")
            fields = _HEADER.unpack(raw)
            channels, rate, bits, mask, guid, frames = (
                fields[i] for i in (6, 7, 10, 13, 14, 17)
            )
            representations: dict[tuple[int, int], Representation] = {
                (1, 8): "u8",
                (1, 16): "s16",
                (1, 24): "s24",
                (1, 32): "s32",
                (3, 32): "f32",
                (3, 64): "f64",
            }
            representation = representations.get(
                (int.from_bytes(guid[:4], "little"), bits)
            )
            if representation is None:
                raise ValueError("unsupported WAVE representation")
            info = PCMFormat(rate, channels, representation, frames, mask)
            size = info.frames * info.frame_bytes
            if (
                raw != _header(info)
                or os.fstat(stream.fileno()).st_size != _HEADER.size + size + size % 2
            ):
                raise ValueError("invalid canonical WAVE metadata or length")
            yield _WaveReader(stream, info)
