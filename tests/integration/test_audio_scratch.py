import errno
import os
import queue
import shutil
import struct
import subprocess
import sys
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any, BinaryIO

import pytest

import muteinous
from muteinous.core.audio.pcm import BLOCK_FRAMES, PCMFormat, Representation
from muteinous.core.audio.scratch import audio_scratch, cleanup_abandoned
from muteinous.core.audio.storage import Reader
from muteinous.core.audio.wav import WaveStorage
from tests.support.audio_storage import FAKE_STORAGE_MARKER as _FAKE_STORAGE_MARKER
from tests.support.audio_storage import FakeStorage as _FakeStorage

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


def test_scratch_edit_reads_and_writes_blocks_incrementally(tmp_path: Path) -> None:
    info = PCMFormat(BLOCK_FRAMES, 1, "s16", 2 * BLOCK_FRAMES + 3)
    frame = b"\x34\x12"
    events: list[str] = []
    storage = _FakeStorage(events=events)

    with audio_scratch(tmp_path, storage) as scratch:
        scratch.write_source(
            info,
            [frame * BLOCK_FRAMES, frame * BLOCK_FRAMES, frame * 3],
        )
        events.clear()

        scratch.edit([(4095 / BLOCK_FRAMES, 4097 / BLOCK_FRAMES)])

        assert events == [
            "read:0",
            "write:0",
            "read:1",
            "write:1",
            "read:2",
            "write:2",
        ]

    assert not list(tmp_path.iterdir())


def test_unsupported_injected_storage_refuses_source_without_writing(
    tmp_path: Path,
) -> None:
    info = PCMFormat(10, 1, "s16", 2)
    storage = _FakeStorage(supported=False)
    with audio_scratch(tmp_path, storage) as scratch:
        with pytest.raises(ValueError):
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


def test_preflight_space_failure_leaves_source_and_no_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    info = PCMFormat(10, 1, "s16", 2)
    with audio_scratch(tmp_path, WaveStorage()) as scratch:
        source = scratch.write_source(info, [b"1234"])
        monkeypatch.setattr(shutil, "disk_usage", lambda _: SimpleNamespace(free=0))
        with pytest.raises(OSError) as error:
            scratch.edit([(0, 0.1)])
        assert error.value.errno == errno.ENOSPC
        assert not (scratch.directory / "edited.pcmstore").exists()
        assert source.exists()
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


def test_scratch_cleanup_failure_does_not_mask_body_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original_unlink = Path.unlink
    source: Path | None = None
    body_error = ValueError("body failure")
    cleanup_error = PermissionError("simulated source cleanup failure")

    def failing_unlink(path: Path, *args: Any, **kwargs: Any) -> None:
        if path == source:
            raise cleanup_error
        original_unlink(path, *args, **kwargs)

    with pytest.raises(ValueError) as error:
        with audio_scratch(tmp_path, WaveStorage()) as scratch:
            source = scratch.write_source(PCMFormat(10, 1, "s16", 2), [b"1234"])
            monkeypatch.setattr(Path, "unlink", failing_unlink)
            raise body_error

    assert source is not None and source.exists()
    assert (source.parent / "ready").exists()
    assert error.value is body_error
    assert error.value.__notes__
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
            raise cleanup_error
        original_unlink(path, *args, **kwargs)

    cleanup_error = PermissionError("simulated source cleanup failure")
    with pytest.raises(PermissionError) as error:
        with audio_scratch(tmp_path, WaveStorage()) as scratch:
            source = scratch.write_source(PCMFormat(10, 1, "s16", 2), [b"1234"])
            monkeypatch.setattr(Path, "unlink", failing_unlink)

    assert error.value is cleanup_error
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
    body_error = ValueError("body failure")
    cleanup_error = PermissionError("simulated owner-lock cleanup failure")

    def failing_unlink(path: Path, *args: Any, **kwargs: Any) -> None:
        if directory is not None and path == directory / "owner.lock":
            raise cleanup_error
        original_unlink(path, *args, **kwargs)

    with pytest.raises(ValueError) as error:
        with audio_scratch(tmp_path, WaveStorage()) as scratch:
            directory = scratch.directory
            monkeypatch.setattr(Path, "unlink", failing_unlink)
            raise body_error

    assert error.value is body_error
    assert error.value.__notes__
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

    body_error = KeyboardInterrupt("body interrupt")
    with pytest.raises(KeyboardInterrupt) as error:
        with audio_scratch(tmp_path, WaveStorage()) as scratch:
            directory = scratch.directory
            monkeypatch.setattr(Path, "rmdir", failing_rmdir)
            raise body_error

    assert error.value is body_error
    assert error.value.__notes__
    monkeypatch.undo()
    assert directory is not None
    directory.rmdir()
    assert not list(tmp_path.iterdir())


def test_outer_scratch_cleanup_failure_propagates_without_body_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original_unlink = Path.unlink
    directory: Path | None = None
    cleanup_error = PermissionError("simulated owner-lock cleanup failure")

    def failing_unlink(path: Path, *args: Any, **kwargs: Any) -> None:
        if directory is not None and path == directory / "owner.lock":
            raise cleanup_error
        original_unlink(path, *args, **kwargs)

    with pytest.raises(PermissionError) as error:
        with audio_scratch(tmp_path, WaveStorage()) as scratch:
            directory = scratch.directory
            monkeypatch.setattr(Path, "unlink", failing_unlink)

    assert error.value is cleanup_error
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
    acquisition_error = ValueError("lock acquisition failure")
    cleanup_error = PermissionError("simulated owner-lock cleanup failure")

    def failing_unlink(path: Path, *args: Any, **kwargs: Any) -> None:
        if path.name == "owner.lock" and path.parent.parent == tmp_path:
            raise cleanup_error
        original_unlink(path, *args, **kwargs)

    def fail_lock_acquisition(_: BinaryIO) -> None:
        raise acquisition_error

    monkeypatch.setattr(Path, "unlink", failing_unlink)
    monkeypatch.setattr(scratch_module, "lock_exclusive", fail_lock_acquisition)
    with pytest.raises(ValueError) as error:
        with audio_scratch(tmp_path, WaveStorage()):
            pytest.fail("context body must not run when lock acquisition fails")

    assert error.value is acquisition_error
    assert error.value.__notes__
    monkeypatch.undo()
    directory = next(tmp_path.iterdir())
    (directory / "owner.lock").unlink(missing_ok=True)
    directory.rmdir()
    assert not list(tmp_path.iterdir())


def test_edit_cleanup_failure_does_not_mask_decoder_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    decoder_error = ValueError("decoder final validation failed")

    class FailingStorage(WaveStorage):
        fail_close = False

        @contextmanager
        def open(self, path: Path) -> Iterator[Reader]:
            with super().open(path) as reader:
                yield reader
            if path.name == "source.pcmstore" and self.fail_close:
                raise decoder_error

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
        with pytest.raises(ValueError) as error:
            scratch.edit([(0, 0.1)])
        assert error.value is decoder_error
        assert error.value.__notes__
        assert edited.exists()

    assert not list(tmp_path.iterdir())


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
    deadline = time.monotonic() + 5
    while directory.exists() and time.monotonic() < deadline:
        cleanup_abandoned(tmp_path)
        if directory.exists():
            threading.Event().wait(0.01)
    assert not directory.exists()


@pytest.mark.parametrize(
    "marker",
    [
        pytest.param(
            b"x" * len(b"muteinous-audio-v1\n"), id="wrong-content-same-length"
        ),
        pytest.param(b"muteinous-audio-v1", id="wrong-length"),
    ],
)
def test_abandoned_cleanup_preserves_invalid_ready_marker(
    tmp_path: Path, marker: bytes
) -> None:
    root = tmp_path / "scratch-root"
    root.mkdir()
    abandoned = root / "audio-invalid-marker"
    abandoned.mkdir()
    (abandoned / "owner.lock").write_bytes(b"1")
    (abandoned / "ready").write_bytes(marker)
    (abandoned / "source.pcmstore").write_bytes(b"old audio")

    cleanup_abandoned(root)

    assert abandoned.is_dir()
    assert (abandoned / "owner.lock").read_bytes() == b"1"
    assert (abandoned / "ready").read_bytes() == marker
    assert (abandoned / "source.pcmstore").read_bytes() == b"old audio"


def test_abandoned_cleanup_preserves_unexpected_entries(tmp_path: Path) -> None:
    root = tmp_path / "scratch-root"
    root.mkdir()
    abandoned = root / "audio-extra-entry"
    abandoned.mkdir()
    (abandoned / "owner.lock").write_bytes(b"1")
    (abandoned / "ready").write_bytes(b"muteinous-audio-v1\n")
    (abandoned / "source.pcmstore").write_bytes(b"old audio")
    (abandoned / "notes.txt").write_bytes(b"keep this")

    cleanup_abandoned(root)

    assert abandoned.is_dir()
    assert {path.name for path in abandoned.iterdir()} == {
        "owner.lock",
        "ready",
        "source.pcmstore",
        "notes.txt",
    }
    assert (abandoned / "owner.lock").read_bytes() == b"1"
    assert (abandoned / "ready").read_bytes() == b"muteinous-audio-v1\n"
    assert (abandoned / "source.pcmstore").read_bytes() == b"old audio"
    assert (abandoned / "notes.txt").read_bytes() == b"keep this"


def test_abandoned_cleanup_preserves_expected_entry_that_is_a_directory(
    tmp_path: Path,
) -> None:
    root = tmp_path / "scratch-root"
    root.mkdir()
    abandoned = root / "audio-directory-entry"
    abandoned.mkdir()
    (abandoned / "owner.lock").write_bytes(b"1")
    (abandoned / "ready").write_bytes(b"muteinous-audio-v1\n")
    source = abandoned / "source.pcmstore"
    source.mkdir()
    (source / "keep.txt").write_bytes(b"not a regular audio file")

    cleanup_abandoned(root)

    assert abandoned.is_dir()
    assert (abandoned / "owner.lock").read_bytes() == b"1"
    assert (abandoned / "ready").read_bytes() == b"muteinous-audio-v1\n"
    assert source.is_dir()
    assert (source / "keep.txt").read_bytes() == b"not a regular audio file"


def _create_test_link(link: Path, target: Path) -> None:
    """Create a directory junction on Windows or a plain symlink elsewhere."""
    if os.name == "nt":
        if not target.is_dir():
            raise AssertionError("Windows test links must target directories")
        subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(link), str(target)],
            check=True,
            capture_output=True,
            text=True,
        )
    else:
        os.symlink(target, link, target_is_directory=target.is_dir())


def _write_abandoned_scratch(directory: Path) -> None:
    directory.mkdir(parents=True)
    (directory / "owner.lock").write_bytes(b"1")
    (directory / "ready").write_bytes(b"muteinous-audio-v1\n")
    (directory / "source.pcmstore").write_bytes(b"old audio")


def test_abandoned_cleanup_does_not_follow_candidate_directory_links(
    tmp_path: Path,
) -> None:
    root = tmp_path / "scratch-root"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()

    # Exact layout ensures removing the candidate-link guard would reclaim this
    # target. The second target verifies that even an extra file stays intact.
    exact_target = outside / "exact-scratch"
    _write_abandoned_scratch(exact_target)
    keep_target = outside / "scratch-with-extra"
    _write_abandoned_scratch(keep_target)
    (keep_target / "keep.txt").write_bytes(b"outside data")
    exact_link = root / "audio-linked-exact"
    keep_link = root / "audio-linked-with-extra"
    _create_test_link(exact_link, exact_target)
    _create_test_link(keep_link, keep_target)

    cleanup_abandoned(root)

    assert exact_target.is_dir()
    assert (exact_target / "owner.lock").read_bytes() == b"1"
    assert (exact_target / "ready").read_bytes() == b"muteinous-audio-v1\n"
    assert (exact_target / "source.pcmstore").read_bytes() == b"old audio"
    assert keep_target.is_dir()
    assert (keep_target / "owner.lock").read_bytes() == b"1"
    assert (keep_target / "ready").read_bytes() == b"muteinous-audio-v1\n"
    assert (keep_target / "source.pcmstore").read_bytes() == b"old audio"
    assert (keep_target / "keep.txt").read_bytes() == b"outside data"
    assert exact_link.is_dir()
    assert keep_link.is_dir()


def test_scratch_root_links_are_refused_or_ignored(tmp_path: Path) -> None:
    target_root = tmp_path / "real-root"
    target_root.mkdir()
    abandoned = target_root / "audio-abandoned"
    _write_abandoned_scratch(abandoned)
    linked_root = tmp_path / "linked-root"
    _create_test_link(linked_root, target_root)

    cleanup_abandoned(linked_root)

    assert abandoned.is_dir()
    assert (abandoned / "owner.lock").read_bytes() == b"1"
    assert (abandoned / "ready").read_bytes() == b"muteinous-audio-v1\n"
    assert (abandoned / "source.pcmstore").read_bytes() == b"old audio"

    with pytest.raises(ValueError):
        with audio_scratch(linked_root, WaveStorage()):
            pytest.fail("audio_scratch must reject a linked root")

    assert abandoned.is_dir()
    assert (abandoned / "owner.lock").read_bytes() == b"1"
    assert (abandoned / "ready").read_bytes() == b"muteinous-audio-v1\n"
    assert (abandoned / "source.pcmstore").read_bytes() == b"old audio"


def test_abandoned_cleanup_preserves_entry_links_and_outside_data(
    tmp_path: Path,
) -> None:
    root = tmp_path / "scratch-root"
    root.mkdir()
    abandoned = root / "audio-linked-entry"
    abandoned.mkdir()
    (abandoned / "owner.lock").write_bytes(b"1")
    (abandoned / "ready").write_bytes(b"muteinous-audio-v1\n")

    if os.name == "nt":
        outside = tmp_path / "outside-directory"
        outside.mkdir()
        (outside / "keep.txt").write_bytes(b"outside data")
        (abandoned / "source.pcmstore").write_bytes(b"old audio")
        entry_link = abandoned / "edited.pcmstore"
    else:
        outside = tmp_path / "outside-file.pcmstore"
        outside.write_bytes(b"outside data")
        entry_link = abandoned / "source.pcmstore"

    _create_test_link(entry_link, outside)

    cleanup_abandoned(root)

    assert abandoned.is_dir()
    assert (abandoned / "owner.lock").read_bytes() == b"1"
    assert (abandoned / "ready").read_bytes() == b"muteinous-audio-v1\n"
    if os.name == "nt":
        assert (abandoned / "source.pcmstore").read_bytes() == b"old audio"
        assert entry_link.is_dir()
        assert (outside / "keep.txt").read_bytes() == b"outside data"
    else:
        assert entry_link.is_symlink()
        assert entry_link.read_bytes() == b"outside data"
        assert outside.read_bytes() == b"outside data"
