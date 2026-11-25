import errno
import os
import queue
import shutil
import struct
import subprocess
import sys
import tempfile
import threading
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any, BinaryIO
from unittest.mock import Mock

import pytest

import muteinous
from muteinous.core.audio.pcm import BLOCK_FRAMES, PCMFormat, Representation
from muteinous.core.audio.scratch import audio_scratch, cleanup_abandoned
from muteinous.core.audio.storage import Reader
from muteinous.core.audio.wav import WaveStorage

pytestmark = pytest.mark.portable


_FAKE_STORAGE_MARKER = b"fake-pcm-storage-v1\n"


class _FakeReader:
    def __init__(self, info: PCMFormat, data: bytes) -> None:
        self.info = info
        self._data = data

    def blocks(self) -> Iterator[bytes]:
        block_size = BLOCK_FRAMES * self.info.frame_bytes
        for offset in range(0, len(self._data), block_size):
            yield self._data[offset : offset + block_size]


class _FakeStorage:
    """Tiny marker-based backend that proves Scratch uses its injected Storage."""

    def __init__(self, supported: bool = True) -> None:
        self.supported = supported
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
            stream.write(_FAKE_STORAGE_MARKER)
            for block in blocks:
                stream.write(block)
        self._infos[path] = info

    @contextmanager
    def open(self, path: Path) -> Iterator[Reader]:
        self.open_paths.append(path)
        with path.open("rb") as stream:
            encoded = stream.read()
        if not encoded.startswith(_FAKE_STORAGE_MARKER):
            raise ValueError("not a fake-storage file")
        yield _FakeReader(self._infos[path], encoded[len(_FAKE_STORAGE_MARKER) :])


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


def test_scratch_uses_injected_storage_for_source_edit_and_read(
    tmp_path: Path,
) -> None:
    info = PCMFormat(4, 1, "s16", 4)
    frame = struct.pack("<h", 10000)
    original = frame * info.frames
    storage = _FakeStorage()

    with audio_scratch(tmp_path, storage) as scratch:
        source = scratch.write_source(info, [original])
        assert source.read_bytes().startswith(_FAKE_STORAGE_MARKER)
        edited = scratch.edit([(0.25, 0.75)])
        assert edited.read_bytes().startswith(_FAKE_STORAGE_MARKER)
        with storage.open(edited) as reader:
            assert reader.info == info
            assert b"".join(reader.blocks()) == frame + bytes(4) + frame

        assert storage.support_calls == [info]
        assert storage.write_paths == [source, edited]
        assert storage.open_paths == [source, edited]

    assert not list(tmp_path.iterdir())


def test_unsupported_injected_storage_refuses_source_without_writing(
    tmp_path: Path,
) -> None:
    info = PCMFormat(10, 1, "s16", 2)
    storage = _FakeStorage(supported=False)
    with audio_scratch(tmp_path, storage) as scratch:
        with pytest.raises(ValueError, match="unsupported"):
            scratch.write_source(info, [b"1234"])
        assert storage.support_calls == [info]
        assert storage.write_paths == []
        assert not (scratch.directory / "source.pcmstore").exists()
    assert not list(tmp_path.iterdir())


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
        monkeypatch.setattr(shutil, "disk_usage", lambda _: SimpleNamespace(free=0))
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


def test_scratch_cleanup_failure_does_not_mask_body_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original_unlink = Path.unlink
    source: Path | None = None

    def failing_unlink(path: Path, *args: Any, **kwargs: Any) -> None:
        if path == source:
            raise PermissionError("simulated source cleanup failure")
        original_unlink(path, *args, **kwargs)

    with pytest.raises(ValueError, match="body failure") as error:
        with audio_scratch(tmp_path, WaveStorage()) as scratch:
            source = scratch.write_source(PCMFormat(10, 1, "s16", 2), [b"1234"])
            monkeypatch.setattr(Path, "unlink", failing_unlink)
            raise ValueError("body failure")

    assert source is not None and source.exists()
    assert (source.parent / "ready").exists()
    assert any("source cleanup failure" in note for note in error.value.__notes__)
    monkeypatch.undo()
    cleanup_abandoned(tmp_path)
    assert not list(tmp_path.iterdir())


def test_scratch_cleanup_failure_propagates_without_body_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original_unlink = Path.unlink
    source: Path | None = None

    def failing_unlink(path: Path, *args: Any, **kwargs: Any) -> None:
        if path == source:
            raise PermissionError("simulated source cleanup failure")
        original_unlink(path, *args, **kwargs)

    with pytest.raises(PermissionError, match="source cleanup failure"):
        with audio_scratch(tmp_path, WaveStorage()) as scratch:
            source = scratch.write_source(PCMFormat(10, 1, "s16", 2), [b"1234"])
            monkeypatch.setattr(Path, "unlink", failing_unlink)

    assert source is not None and source.exists()
    assert (source.parent / "ready").exists()
    monkeypatch.undo()
    cleanup_abandoned(tmp_path)
    assert not list(tmp_path.iterdir())


def test_outer_scratch_cleanup_does_not_mask_value_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original_unlink = Path.unlink
    directory: Path | None = None

    def failing_unlink(path: Path, *args: Any, **kwargs: Any) -> None:
        if directory is not None and path == directory / "owner.lock":
            raise PermissionError("simulated owner-lock cleanup failure")
        original_unlink(path, *args, **kwargs)

    with pytest.raises(ValueError, match="body failure") as error:
        with audio_scratch(tmp_path, WaveStorage()) as scratch:
            directory = scratch.directory
            monkeypatch.setattr(Path, "unlink", failing_unlink)
            raise ValueError("body failure")

    assert any("owner-lock cleanup failure" in note for note in error.value.__notes__)
    monkeypatch.undo()
    assert directory is not None
    (directory / "owner.lock").unlink(missing_ok=True)
    directory.rmdir()
    assert not list(tmp_path.iterdir())


def test_outer_scratch_cleanup_does_not_mask_keyboard_interrupt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original_rmdir = Path.rmdir
    directory: Path | None = None

    def failing_rmdir(path: Path) -> None:
        if path == directory:
            raise PermissionError("simulated scratch-directory cleanup failure")
        original_rmdir(path)

    with pytest.raises(KeyboardInterrupt, match="body interrupt") as error:
        with audio_scratch(tmp_path, WaveStorage()) as scratch:
            directory = scratch.directory
            monkeypatch.setattr(Path, "rmdir", failing_rmdir)
            raise KeyboardInterrupt("body interrupt")

    assert any(
        "scratch-directory cleanup failure" in note for note in error.value.__notes__
    )
    monkeypatch.undo()
    assert directory is not None
    directory.rmdir()
    assert not list(tmp_path.iterdir())


def test_outer_scratch_cleanup_failure_propagates_without_body_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original_unlink = Path.unlink
    directory: Path | None = None

    def failing_unlink(path: Path, *args: Any, **kwargs: Any) -> None:
        if directory is not None and path == directory / "owner.lock":
            raise PermissionError("simulated owner-lock cleanup failure")
        original_unlink(path, *args, **kwargs)

    with pytest.raises(PermissionError, match="owner-lock cleanup failure"):
        with audio_scratch(tmp_path, WaveStorage()) as scratch:
            directory = scratch.directory
            monkeypatch.setattr(Path, "unlink", failing_unlink)

    monkeypatch.undo()
    assert directory is not None
    (directory / "owner.lock").unlink(missing_ok=True)
    directory.rmdir()
    assert not list(tmp_path.iterdir())


def test_lock_acquisition_error_is_preserved_when_outer_cleanup_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import muteinous.core.audio.scratch as scratch_module

    original_unlink = Path.unlink
    directory: Path | None = None
    original_mkdtemp = tempfile.mkdtemp

    def fail_lock_acquisition(_: BinaryIO) -> None:
        raise ValueError("lock acquisition failure")

    def captured_mkdtemp(*, prefix: str, dir: Path) -> str:
        nonlocal directory
        result = original_mkdtemp(prefix=prefix, dir=dir)
        directory = Path(result)
        return result

    def failing_unlink(path: Path, *args: Any, **kwargs: Any) -> None:
        if directory is not None and path == directory / "owner.lock":
            raise PermissionError("simulated owner-lock cleanup failure")
        original_unlink(path, *args, **kwargs)

    monkeypatch.setattr(scratch_module, "lock_exclusive", fail_lock_acquisition)
    monkeypatch.setattr(tempfile, "mkdtemp", captured_mkdtemp)
    monkeypatch.setattr(Path, "unlink", failing_unlink)
    with pytest.raises(ValueError, match="lock acquisition failure") as error:
        with audio_scratch(tmp_path, WaveStorage()):
            pytest.fail("context body must not run when lock acquisition fails")

    assert any("owner-lock cleanup failure" in note for note in error.value.__notes__)
    monkeypatch.undo()
    assert directory is not None
    (directory / "owner.lock").unlink(missing_ok=True)
    directory.rmdir()
    assert not list(tmp_path.iterdir())


def test_edit_cleanup_failure_does_not_mask_decoder_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class FailingStorage(WaveStorage):
        fail_close = False

        @contextmanager
        def open(self, path: Path) -> Iterator[Reader]:
            with super().open(path) as reader:
                yield reader
            if path.name == "source.pcmstore" and self.fail_close:
                raise ValueError("decoder final validation failed")

    original_unlink = Path.unlink
    edited: Path | None = None
    fail_once = True

    def failing_unlink(path: Path, *args: Any, **kwargs: Any) -> None:
        nonlocal fail_once
        if path == edited and fail_once:
            fail_once = False
            raise PermissionError("simulated edited-file cleanup failure")
        original_unlink(path, *args, **kwargs)

    storage = FailingStorage()
    with audio_scratch(tmp_path, storage) as scratch:
        scratch.write_source(PCMFormat(10, 1, "s16", 2), [b"1234"])
        storage.fail_close = True
        edited = scratch.directory / "edited.pcmstore"
        monkeypatch.setattr(Path, "unlink", failing_unlink)
        with pytest.raises(
            ValueError, match="decoder final validation failed"
        ) as error:
            scratch.edit([(0, 0.1)])
        assert any(
            "edited-file cleanup failure" in note for note in error.value.__notes__
        )
        assert edited.exists()

    assert not list(tmp_path.iterdir())


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


def test_corrupt_source_does_not_create_edited_scratch(tmp_path: Path) -> None:
    with audio_scratch(tmp_path, WaveStorage()) as scratch:
        source = scratch.write_source(PCMFormat(10, 1, "s16", 2), [b"1234"])
        raw = bytearray(source.read_bytes())
        raw[0:4] = b"JUNK"
        source.write_bytes(raw)

        with pytest.raises(ValueError):
            scratch.edit([(0, 0.1)])
        assert not (scratch.directory / "edited.pcmstore").exists()

    assert not list(tmp_path.iterdir())


def test_cleanup_abandoned_respects_a_live_process_lock(tmp_path: Path) -> None:
    child_code = """
import sys
from pathlib import Path
from muteinous.core.audio.pcm import PCMFormat
from muteinous.core.audio.scratch import audio_scratch
from muteinous.core.audio.wav import WaveStorage

with audio_scratch(Path(sys.argv[1]), WaveStorage()) as scratch:
    scratch.write_source(PCMFormat(10, 1, "s16", 2), [b"1234"])
    print(f"READY {scratch.directory}", flush=True)
    sys.stdin.readline()
"""
    source_dir = str(Path(muteinous.__file__).resolve().parent.parent)
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join(
        part for part in (source_dir, env.get("PYTHONPATH")) if part
    )
    process = subprocess.Popen(
        [sys.executable, "-c", child_code, str(tmp_path)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        env=env,
    )
    stdout = process.stdout
    assert stdout is not None
    lines: queue.Queue[str] = queue.Queue()
    reader = threading.Thread(target=lambda: lines.put(stdout.readline()), daemon=True)
    reader.start()
    directory: Path | None = None
    try:
        ready = lines.get(timeout=15)
        assert ready.startswith("READY "), ready
        directory = Path(ready.removeprefix("READY ").strip())
        source = directory / "source.pcmstore"
        assert source.read_bytes() != b""
        assert (directory / "ready").exists()

        cleanup_abandoned(tmp_path)
        assert directory.is_dir()
        assert source.exists()
        assert (directory / "ready").exists()
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        if process.stdin is not None:
            process.stdin.close()
        reader.join(timeout=5)

    assert directory is not None
    assert directory.is_dir()
    assert (directory / "source.pcmstore").exists()
    cleanup_abandoned(tmp_path)
    assert not directory.exists()
