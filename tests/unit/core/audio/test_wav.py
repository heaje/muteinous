import errno
import shutil
import struct
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any, BinaryIO
from unittest.mock import Mock

import pytest

from muteinous.core.audio.pcm import BLOCK_FRAMES, PCMFormat, Representation
from muteinous.core.audio.wav import WaveStorage

pytestmark = pytest.mark.portable


@pytest.mark.parametrize(
    "info,blocks",
    [
        (
            PCMFormat(10, 1, "s16", BLOCK_FRAMES + 1),
            [bytes((BLOCK_FRAMES + 1) * 2)],
        ),
        (PCMFormat(10, 1, "s16", 1), [b"\x00"]),
        (PCMFormat(10, 1, "s16", 1), [b""]),
        (PCMFormat(10, 1, "s16", 2), [b"\x00\x00"]),
        (PCMFormat(10, 1, "s16", 1), [b"\x00\x00\x00\x00"]),
    ],
    ids=["oversized", "partial-frame", "empty", "short", "excess"],
)
def test_wave_write_rejects_malformed_bounded_streams_without_file(
    tmp_path: Path, info: PCMFormat, blocks: list[bytes]
) -> None:
    path = tmp_path / "invalid.pcmstore"
    with pytest.raises(ValueError):
        WaveStorage().write(path, info, blocks)
    assert not path.exists()


def test_wave_write_preflight_includes_header_and_padding(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    info = PCMFormat(8000, 1, "u8", 3)
    payload = b"\x80\x81\x82"
    storage = WaveStorage()
    reference = tmp_path / "reference.pcmstore"
    storage.write(reference, info, [payload])
    required = reference.stat().st_size
    reference.unlink()
    assert required > len(payload)

    insufficient = tmp_path / "insufficient.pcmstore"
    monkeypatch.setattr(
        shutil, "disk_usage", lambda _: SimpleNamespace(free=required - 1)
    )
    with pytest.raises(OSError) as error:
        storage.write(insufficient, info, [payload])
    assert error.value.errno == errno.ENOSPC
    assert not insufficient.exists()

    exact = tmp_path / "exact.pcmstore"
    monkeypatch.setattr(shutil, "disk_usage", lambda _: SimpleNamespace(free=required))
    storage.write(exact, info, [payload])
    assert exact.stat().st_size == required
    with pytest.raises(FileExistsError):
        storage.write(exact, info, [payload])


def test_wave_write_requests_each_block_after_writing_the_previous_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    info = PCMFormat(48000, 1, "s16", 2 * BLOCK_FRAMES + 3)
    blocks = (
        bytes([0x11]) * (BLOCK_FRAMES * info.frame_bytes),
        bytes([0x22]) * (BLOCK_FRAMES * info.frame_bytes),
        bytes([0x33]) * (3 * info.frame_bytes),
    )
    output = tmp_path / "streamed.pcmstore"
    events: list[tuple[str, int, int]] = []
    output_stream: BinaryIO | None = None
    original_open = Path.open

    def observed_open(path: Path, *args: Any, **kwargs: Any) -> Any:
        nonlocal output_stream
        stream: BinaryIO = original_open(path, *args, **kwargs)
        if path != output or args != ("xb",):
            return stream
        output_stream = stream
        wrapped = Mock()

        def write(data: bytes) -> int:
            written = stream.write(data)
            events.append(("write", len(data), stream.tell()))
            return written

        wrapped.write.side_effect = write
        wrapped.__enter__ = Mock(return_value=wrapped)
        wrapped.__exit__ = Mock(side_effect=lambda *_: stream.close())
        return wrapped

    def source() -> Iterator[bytes]:
        for index, block in enumerate(blocks):
            assert output_stream is not None
            events.append(("request", index, output_stream.tell()))
            yield block

    monkeypatch.setattr(Path, "open", observed_open)
    WaveStorage().write(output, info, source())

    assert [event[0] for event in events] == [
        "write",
        *(kind for _ in blocks for kind in ("request", "write")),
    ]
    writes = [event for event in events if event[0] == "write"]
    requests = [event for event in events if event[0] == "request"]
    assert [event[1] for event in writes[1:]] == [len(block) for block in blocks]
    assert [event[2] for event in requests] == [event[2] for event in writes[:-1]]
    assert requests[0][2] > 0  # The canonical header was written before block 0.


def test_unsupported_riff_size(tmp_path: Path) -> None:
    info = PCMFormat(48000, 2, "f64", 1 << 30, 3)
    storage = WaveStorage()
    path = tmp_path / "oversized.pcmstore"
    assert not storage.supports(info)
    with pytest.raises(ValueError):
        storage.write(path, info, [])
    assert not path.exists()


def test_actual_write_failure_removes_partial_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    info = PCMFormat(10, 1, "s16", 2)
    output = tmp_path / "partial"
    original_open = Path.open

    def failing_open(path: Path, *args: Any, **kwargs: Any) -> Any:
        stream = original_open(path, *args, **kwargs)
        if path != output or args != ("xb",):
            return stream
        wrapped = Mock()

        # First write is real; the second fails after the file exists.
        def write(data: bytes) -> int:
            if stream.tell():
                raise OSError(errno.ENOSPC, "simulated write failure")
            return int(stream.write(data))

        wrapped.write.side_effect = write
        wrapped.__enter__ = Mock(return_value=wrapped)
        wrapped.__exit__ = Mock(side_effect=lambda *_: stream.close())
        return wrapped

    monkeypatch.setattr(Path, "open", failing_open)
    with pytest.raises(OSError) as error:
        WaveStorage().write(output, info, [b"1234"])
    assert error.value.errno == errno.ENOSPC
    assert not output.exists()


def test_write_failure_is_preserved_when_partial_cleanup_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    info = PCMFormat(10, 1, "s16", 2)
    output = tmp_path / "partial"
    original_open = Path.open
    original_unlink = Path.unlink

    def failing_open(path: Path, *args: Any, **kwargs: Any) -> Any:
        stream: BinaryIO = original_open(path, *args, **kwargs)
        if path != output or args != ("xb",):
            return stream
        wrapped = Mock()

        def write(data: bytes) -> int:
            if stream.tell():
                raise OSError(errno.ENOSPC, "simulated write failure")
            return stream.write(data)

        wrapped.write.side_effect = write
        wrapped.__enter__ = Mock(return_value=wrapped)
        wrapped.__exit__ = Mock(side_effect=lambda *_: stream.close())
        return wrapped

    def failing_unlink(path: Path, *args: Any, **kwargs: Any) -> None:
        if path == output:
            raise PermissionError("simulated cleanup failure")
        original_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", failing_open)
    monkeypatch.setattr(Path, "unlink", failing_unlink)
    with pytest.raises(OSError) as error:
        WaveStorage().write(output, info, [b"1234"])
    assert error.value.errno == errno.ENOSPC
    assert any("cleanup failure" in note for note in error.value.__notes__)
    assert output.exists()
    monkeypatch.undo()
    output.unlink()


@pytest.mark.parametrize(
    "offset,replacement",
    [
        (0, b"JUNK"),
        (4, struct.pack("<I", 77)),
        (8, b"NOPE"),
        (20, struct.pack("<H", 1)),
        (36, struct.pack("<H", 21)),
        (44, struct.pack("<I", 2) + bytes(12)),
        (28, struct.pack("<I", 16001)),
        (32, struct.pack("<H", 4)),
        (38, struct.pack("<H", 8)),
        (64, struct.pack("<I", 8)),
        (68, struct.pack("<I", 3)),
        (72, b"JUNK"),
        (76, struct.pack("<I", 5)),
    ],
)
def test_malformed_canonical_headers_are_rejected(
    tmp_path: Path, offset: int, replacement: bytes
) -> None:
    path = tmp_path / "source.pcmstore"
    WaveStorage().write(path, PCMFormat(8000, 1, "s16", 2), [b"1234"])
    raw = bytearray(path.read_bytes())
    raw[offset : offset + len(replacement)] = replacement
    path.write_bytes(raw)

    with pytest.raises(ValueError):
        with WaveStorage().open(path):
            pass


@pytest.mark.parametrize(
    "representation,offset,replacement",
    [
        ("s16", 44, struct.pack("<I", 3) + bytes(12)),
        ("f64", 44, struct.pack("<I", 1) + bytes(12)),
    ],
)
def test_unsupported_wave_tag_precision_pairs_are_rejected(
    tmp_path: Path, representation: Representation, offset: int, replacement: bytes
) -> None:
    path = tmp_path / "source.pcmstore"
    WaveStorage().write(
        path,
        PCMFormat(8000, 1, representation, 2),
        [bytes(16 if representation == "f64" else 4)],
    )
    raw = bytearray(path.read_bytes())
    raw[offset : offset + len(replacement)] = replacement
    path.write_bytes(raw)

    with pytest.raises(ValueError):
        with WaveStorage().open(path):
            pass
