import os
import signal
import subprocess
import sys
from pathlib import Path

import pytest

from experiments.native_ast.ffmpeg_tools import (
    FFmpegToolError,
    FFmpegTools,
    has_named_capabilities,
    has_named_entry,
)


class _PythonFFmpegTools(FFmpegTools):
    def _command(self, args: list[str]) -> list[str]:
        return [str(self.executable), *args]


class _BoundedPythonFFmpegTools(_PythonFFmpegTools):
    output_tail_bytes = 1_024
    tail_observations: list[tuple[int, int]] = []

    @classmethod
    def _read_tail(cls, path: Path) -> str:
        text = super()._read_tail(path)
        cls.tail_observations.append((path.stat().st_size, len(text.encode("utf-8"))))
        return text


@pytest.mark.portable
def test_ffmpeg_capability_parser_requires_requested_codec_and_format_flags() -> None:
    formats = """
 D  matroska
 DE ogg
 E  ast
"""
    codecs = """
 D.AIL. pcm_s16be_planar
 .EAIL. libvorbis
 DEAIL. vorbis
"""
    encoders = """
 A..... libvorbis
 A..... vorbis
"""
    decoders = """
 A..... vorbis
 A..... libvorbis
"""
    assert has_named_capabilities(formats, "ogg", "DE")
    assert not has_named_capabilities(formats, "ogg", "DEI")
    assert not has_named_capabilities(formats, "matroska", "E")
    assert has_named_capabilities(
        " DEAIL. pcm_s16be_planar",
        "pcm_s16be_planar",
        "DE",
    )
    assert has_named_capabilities(codecs, "pcm_s16be_planar", "D")
    assert not has_named_capabilities(codecs, "pcm_s16be_planar", "DE")
    assert not has_named_capabilities(codecs, "pcm_s16be_planar", "E")
    assert not has_named_capabilities(codecs, "libvorbis", "D")
    assert has_named_capabilities(codecs, "libvorbis", "E")
    assert has_named_capabilities(codecs, "vorbis", "D")
    assert has_named_entry(encoders, "libvorbis")
    assert has_named_entry(decoders, "vorbis")
    assert not has_named_entry(encoders, "missing")


def _pid_exists(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _kill_orphaned_child(pid: int) -> None:
    if not _pid_exists(pid):
        return
    if os.name == "nt":
        taskkill = (
            Path(os.environ.get("SystemRoot", r"C:\Windows"))
            / "System32"
            / "taskkill.exe"
        )
        subprocess.run(
            [str(taskkill), "/PID", str(pid), "/T", "/F"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=5,
        )
    else:
        os.kill(pid, getattr(signal, "SIGKILL"))


def test_timeout_kills_fake_tool_and_its_child_process(tmp_path: Path) -> None:
    tools = _PythonFFmpegTools(Path(sys.executable), "")
    parent_pid_path = tmp_path / "parent.pid"
    child_pid_path = tmp_path / "child.pid"
    parent_code = (
        "import os, pathlib, subprocess, sys, time\n"
        "pathlib.Path(sys.argv[1]).write_text(str(os.getpid()), encoding='ascii')\n"
        "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'], "
        "stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, "
        "stderr=subprocess.DEVNULL)\n"
        "pathlib.Path(sys.argv[2]).write_text(str(child.pid), encoding='ascii')\n"
        "time.sleep(60)\n"
    )
    parent_pid: int | None = None
    child_pid: int | None = None
    try:
        with pytest.raises(FFmpegToolError, match="timed out after 1s"):
            tools._run(
                ["-c", parent_code, str(parent_pid_path), str(child_pid_path)],
                timeout=1,
            )
        parent_pid = int(parent_pid_path.read_text(encoding="ascii"))
        child_pid = int(child_pid_path.read_text(encoding="ascii"))
        assert not _pid_exists(parent_pid)
        assert not _pid_exists(child_pid)
    finally:
        if parent_pid is None and parent_pid_path.exists():
            parent_pid = int(parent_pid_path.read_text(encoding="ascii"))
        if child_pid is None and child_pid_path.exists():
            child_pid = int(child_pid_path.read_text(encoding="ascii"))
        if child_pid is not None:
            _kill_orphaned_child(child_pid)
        if parent_pid is not None:
            _kill_orphaned_child(parent_pid)


def test_large_stderr_has_a_bounded_utf8_diagnostic_tail() -> None:
    _BoundedPythonFFmpegTools.tail_observations = []
    tools = _BoundedPythonFFmpegTools(Path(sys.executable), "")
    code = "import sys; sys.stderr.buffer.write(b'x' * 2000000); sys.exit(7)"
    with pytest.raises(FFmpegToolError) as error:
        tools._run(["-c", code], timeout=10)
    assert len(str(error.value)) < 500
    assert _BoundedPythonFFmpegTools.tail_observations
    assert any(
        file_size > _BoundedPythonFFmpegTools.output_tail_bytes
        for file_size, _ in _BoundedPythonFFmpegTools.tail_observations
    )
    assert all(
        tail_size <= _BoundedPythonFFmpegTools.output_tail_bytes
        for _, tail_size in _BoundedPythonFFmpegTools.tail_observations
    )
