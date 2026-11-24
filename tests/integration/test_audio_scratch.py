import errno
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock

import pytest

from muteinous.core.audio import wav
from muteinous.core.audio.pcm import BLOCK_FRAMES, PCMFormat, Representation
from muteinous.core.audio.scratch import audio_scratch, cleanup_abandoned
from muteinous.core.audio.storage import Reader
from muteinous.core.audio.wav import WaveStorage

pytestmark = pytest.mark.portable


@pytest.mark.parametrize(
    "representation,rate,channels,mask",
    [
        ("u8", 8000, 1, 4),
        ("s16", 16000, 1, 4),
        ("s24", 48000, 2, 3),
        ("s32", 96000, 6, 63),
        ("f32", 44100, 2, 3),
        ("f64", 192000, 1, 0),
    ],
)
def test_bit_exact_roundtrip(
    tmp_path: Path, representation: Representation, rate: int, channels: int, mask: int
) -> None:
    info = PCMFormat(rate, channels, representation, BLOCK_FRAMES + 1, mask)
    # Arbitrary sample bit patterns include noncanonical float values; no conversion.
    data = bytes(range(256)) * ((info.frames * info.frame_bytes + 255) // 256)
    data = data[: info.frames * info.frame_bytes]
    split = BLOCK_FRAMES * info.frame_bytes
    storage = WaveStorage()
    with audio_scratch(tmp_path, storage) as scratch:
        path = scratch.write_source(info, [data[:split], data[split:]])
        with storage.open(path) as reader:
            assert reader.info == info
            blocks = list(reader.blocks())
            assert [len(b) for b in blocks] == [split, info.frame_bytes]
            assert b"".join(blocks) == data
        edited = scratch.edit([(0, info.frames / rate)])
        with storage.open(edited) as reader:
            assert reader.info == info
            silence = b"\x80" if representation == "u8" else b"\x00"
            assert b"".join(reader.blocks()) == silence * len(data)
    assert not list(tmp_path.iterdir())


def test_edit_across_storage_block_boundary(tmp_path: Path) -> None:
    info = PCMFormat(4096, 2, "s24", BLOCK_FRAMES + 4, 3)
    frame = b"\x12\x34\x56\x78\x9a\xbc"
    storage = WaveStorage()
    with audio_scratch(tmp_path, storage) as scratch:
        source = scratch.write_source(info, [frame * BLOCK_FRAMES, frame * 4])
        edited = scratch.edit([(4095 / 4096, 4098 / 4096)])
        with storage.open(edited) as reader:
            assert b"".join(reader.blocks()) == frame * 4095 + bytes(18) + frame * 2
        with storage.open(source) as reader:
            assert b"".join(reader.blocks()) == frame * info.frames


def test_decode_failure_and_invalid_edit_leave_no_result(tmp_path: Path) -> None:
    info = PCMFormat(10, 1, "s16", 2)
    with audio_scratch(tmp_path, WaveStorage()) as scratch:
        path = scratch.write_source(info, [b"1234"])
        with pytest.raises(ValueError):
            scratch.edit([(0, 1)])
        assert not (scratch.directory / "edited.pcmstore").exists()
        path.write_bytes(path.read_bytes()[:-1])
        with pytest.raises(ValueError):
            scratch.edit([(0, 0.1)])
        assert not (scratch.directory / "edited.pcmstore").exists()
    assert not list(tmp_path.iterdir())


def test_decoder_close_failure_invalidates_completed_output(tmp_path: Path) -> None:
    class FailingStorage(WaveStorage):
        @contextmanager
        def open(self, path: Path) -> Iterator[Reader]:
            with super().open(path) as reader:
                yield reader
            if path.name == "source.pcmstore" and self.fail_close:
                raise ValueError("decoder final validation failed")

        fail_close = False

    storage = FailingStorage()
    with audio_scratch(tmp_path, storage) as scratch:
        scratch.write_source(PCMFormat(10, 1, "s16", 2), [b"1234"])
        storage.fail_close = True
        with pytest.raises(ValueError, match="final validation failed"):
            scratch.edit([(0, 0.1)])
        assert not (scratch.directory / "edited.pcmstore").exists()
    assert not list(tmp_path.iterdir())


def test_preflight_and_runtime_space_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    info = PCMFormat(10, 1, "s16", 2)
    with audio_scratch(tmp_path, WaveStorage()) as scratch:
        path = scratch.write_source(info, [b"1234"])
        monkeypatch.setattr(wav.shutil, "disk_usage", lambda _: SimpleNamespace(free=0))
        with pytest.raises(OSError) as error:
            scratch.edit([(0, 0.1)])
        assert error.value.errno == errno.ENOSPC
        assert not (scratch.directory / "edited.pcmstore").exists()
        monkeypatch.undo()

        def broken() -> Iterator[bytes]:
            yield b"12"
            raise OSError(errno.ENOSPC, "simulated runtime stream failure")

        output = scratch.directory / "edited.pcmstore"
        with pytest.raises(OSError) as error:
            WaveStorage().write(output, info, broken())
        assert error.value.errno == errno.ENOSPC
        assert not output.exists()
        assert path.exists()
    assert not list(tmp_path.iterdir())


def test_exclusive_write_and_abandoned_cleanup(tmp_path: Path) -> None:
    info = PCMFormat(10, 1, "s16", 2)
    unrelated = tmp_path / "audio-unrelated"
    unrelated.mkdir()
    (unrelated / "keep").write_bytes(b"keep")
    abandoned = tmp_path / "audio-abandoned"
    abandoned.mkdir()
    (abandoned / "owner.lock").write_bytes(b"1")
    (abandoned / "ready").write_bytes(b"muteinous-audio-v1\n")
    (abandoned / "source.pcmstore").write_bytes(b"old")
    with audio_scratch(tmp_path, WaveStorage()) as scratch:
        assert not abandoned.exists()
        path = scratch.write_source(info, [b"1234"])
        with pytest.raises(FileExistsError):
            scratch.write_source(info, [b"5678"])
        cleanup_abandoned(tmp_path)
        assert path.exists()
        with WaveStorage().open(path) as reader:
            assert b"".join(reader.blocks()) == b"1234"
    assert (unrelated / "keep").read_bytes() == b"keep"


def test_unsupported_riff_size(tmp_path: Path) -> None:
    info = PCMFormat(48000, 2, "f64", 1 << 30, 3)
    with audio_scratch(tmp_path, WaveStorage()) as scratch:
        assert not scratch.storage.supports(info)
        with pytest.raises(ValueError):
            scratch.write_source(info, [])
        assert not (scratch.directory / "source.pcmstore").exists()


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
            return stream.write(data)

        wrapped.write.side_effect = write
        wrapped.__enter__ = Mock(return_value=wrapped)
        wrapped.__exit__ = Mock(side_effect=lambda *_: stream.close())
        return wrapped

    monkeypatch.setattr(Path, "open", failing_open)
    with pytest.raises(OSError) as error:
        WaveStorage().write(output, info, [b"1234"])
    assert error.value.errno == errno.ENOSPC
    assert not output.exists()
