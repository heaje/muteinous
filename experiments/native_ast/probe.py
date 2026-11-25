"""Manual FFmpeg identity/canonical-byte check; not a production adapter."""

import csv
import io
import os
import struct
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import ClassVar

from .ast_core import (
    FRAMES,
    INFO,
    NativeValidationError,
    build_canonical_ast,
    validate_fixture,
)
from .ffmpeg_tools import FFmpegToolError, FFmpegTools


class _PythonToolWrapper(FFmpegTools):
    tail_observations: ClassVar[list[tuple[int, int]]] = []

    def _command(self, args: list[str]) -> list[str]:
        return [sys.executable, *args]

    @classmethod
    def _read_tail(cls, path: Path) -> str:
        text = super()._read_tail(path)
        cls.tail_observations.append((path.stat().st_size, len(text.encode("utf-8"))))
        return text


def _windows_pid_exists(pid: int) -> bool:
    tasklist = (
        Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "tasklist.exe"
    )
    result = subprocess.run(
        [str(tasklist), "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        check=False,
        timeout=5,
        text=True,
    )
    return any(
        len(row) > 1 and row[1].strip() == str(pid)
        for row in csv.reader(io.StringIO(result.stdout))
    )


def _windows_kill_tree(pid: int) -> None:
    taskkill = (
        Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "taskkill.exe"
    )
    try:
        subprocess.run(
            [str(taskkill), "/PID", str(pid), "/T", "/F"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=5,
        )
    except OSError, subprocess.TimeoutExpired:
        pass


def _probe_wrapper_limits() -> None:
    tools = _PythonToolWrapper(Path(sys.executable), "Python wrapper control")
    _PythonToolWrapper.tail_observations.clear()
    try:
        tools._run(
            [
                "-c",
                "import sys; sys.stderr.buffer.write(b'x' * 2000000); sys.exit(7)",
            ],
            timeout=10,
        )
    except FFmpegToolError as exc:
        if len(str(exc)) >= 500:
            raise AssertionError("wrapper failure diagnostic was not bounded") from exc
    else:
        raise AssertionError("large-stderr negative control unexpectedly succeeded")
    if not any(size > tools.output_tail_bytes for size, _ in tools.tail_observations):
        raise AssertionError(
            "large-stderr negative control did not exceed the tail cap"
        )
    if any(size > tools.output_tail_bytes for _, size in tools.tail_observations):
        raise AssertionError("wrapper read more than its configured output tail")
    print("PASS: wrapper reads bounded stderr tails and emits bounded diagnostics")

    if os.name != "nt":
        print("NOTE: Windows process-tree timeout control was not run on this host")
        return

    with TemporaryDirectory(prefix="muteinous-wrapper-control-") as private:
        root = Path(private)
        parent_pid_file = root / "parent.pid"
        child_pid_file = root / "child.pid"
        parent_code = (
            "import pathlib, subprocess, sys, time\n"
            "pathlib.Path(sys.argv[1]).write_text(str(__import__('os').getpid()))\n"
            "child = subprocess.Popen([sys.executable, '-c', "
            "'import time; time.sleep(60)'], stdin=subprocess.DEVNULL, "
            "stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)\n"
            "pathlib.Path(sys.argv[2]).write_text(str(child.pid))\n"
            "time.sleep(60)\n"
        )
        pids: list[int] = []
        try:
            try:
                tools._run(
                    [
                        "-c",
                        parent_code,
                        str(parent_pid_file),
                        str(child_pid_file),
                    ],
                    timeout=1,
                )
            except FFmpegToolError as exc:
                if "timed out after 1s" not in str(exc):
                    raise AssertionError("wrapper reported the wrong timeout") from exc
            else:
                raise AssertionError("timeout negative control unexpectedly succeeded")

            if not parent_pid_file.is_file() or not child_pid_file.is_file():
                raise AssertionError("timeout fixture did not start both processes")
            pids = [
                int(parent_pid_file.read_text()),
                int(child_pid_file.read_text()),
            ]
            if any(_windows_pid_exists(pid) for pid in pids):
                raise AssertionError("timeout left a process in the wrapper tree")
        finally:
            for pid_file in (parent_pid_file, child_pid_file):
                if pid_file.is_file():
                    pid = int(pid_file.read_text())
                    if pid not in pids:
                        pids.append(pid)
            for pid in pids:
                if _windows_pid_exists(pid):
                    _windows_kill_tree(pid)
    print(
        "PASS: best-effort Windows taskkill timeout control terminated this "
        "test process tree"
    )


def _pcm_fixture() -> bytes:
    return b"".join(
        struct.pack(
            "<hh",
            (frame * 67) % 65_536 - 32_768,
            32_767 - (frame * 137) % 65_536,
        )
        for frame in range(FRAMES)
    )


def _expect_refusal(operation: object, reason: str) -> None:
    try:
        validate_fixture(operation, _pcm_fixture())  # type: ignore[arg-type]
    except NativeValidationError as exc:
        if reason not in str(exc):
            raise AssertionError(f"wrong refusal for {reason}: {exc}") from exc
    else:
        raise AssertionError(f"unexpected acceptance: {reason}")


def main() -> None:
    tools = FFmpegTools.discover()
    print(f"PASS: {tools.version}")
    print(
        "PASS: FFmpeg AST muxer/demuxer and pcm_s16be_planar "
        "decoder/encoder are available"
    )
    _probe_wrapper_limits()
    expected = _pcm_fixture()

    with TemporaryDirectory(prefix="muteinous-ast-probe-") as scratch:
        root = Path(scratch)
        raw = root / "input.pcm"
        source = root / "source.ast"
        extracted = root / "extracted.pcm"
        rebuilt = root / "rebuilt.ast"
        raw.write_bytes(expected)

        tools.encode("probe", raw, source, INFO)
        original = source.read_bytes()
        blocks = validate_fixture(original, expected, asset_id="probe")
        oracle = build_canonical_ast(expected, INFO)
        if original != oracle:
            raise AssertionError("FFmpeg bytes differ from pure-Python canonical AST")

        tools.decode("probe", source, extracted, INFO)
        if extracted.read_bytes() != expected:
            raise AssertionError("FFmpeg decode differs from synthetic PCM")
        tools.encode("probe", extracted, rebuilt, INFO)
        output = rebuilt.read_bytes()
        validate_fixture(output, expected, asset_id="probe")
        if output != original:
            raise AssertionError("native bytes changed during identity round trip")
        tools.assert_stereo(rebuilt)
        if source.read_bytes() != original:
            raise AssertionError("source AST changed")

        _expect_refusal(original[:-1], "STRM file size mismatch")
        unsupported = bytearray(original)
        struct.pack_into(">H", unsupported, 8, 0)
        _expect_refusal(bytes(unsupported), "unsupported AST codec")
        reserved = bytearray(original)
        reserved[36] = 1
        _expect_refusal(bytes(reserved), "noncanonical STRM reserved/header bytes")
        print(
            f"PASS: {FRAMES} stereo PCM16 frames, {blocks} canonical blocks, "
            f"{len(output)} native bytes"
        )
        print("PASS: FFmpeg output equals the pure-Python writer and identity rebuild")
        print("PASS: malformed, unsupported, and noncanonical AST inputs refused")

    if root.exists():
        raise AssertionError("probe scratch was not removed")
    print("PASS: disposable scratch removed")


if __name__ == "__main__":
    main()
