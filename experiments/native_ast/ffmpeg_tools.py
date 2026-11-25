"""Trusted, bounded subprocess wrapper used only by manual AST experiments."""

import os
import shutil
import signal
import subprocess
import tempfile
from pathlib import Path
from typing import ClassVar

from muteinous.core.audio.pcm import PCMFormat


class FFmpegToolError(RuntimeError):
    """A native-tool preflight or subprocess failed with bounded diagnostics."""


def has_named_capabilities(output: str, name: str, required: str) -> bool:
    """Check FFmpeg -formats/-codecs flags for a named entry."""
    for line in output.splitlines():
        fields = line.split()
        if len(fields) >= 2 and fields[1] == name:
            return all(flag in fields[0] for flag in required)
    return False


def has_named_entry(output: str, name: str) -> bool:
    """Check an FFmpeg -encoders/-decoders listing for a named entry."""
    return any(
        len(fields := line.split()) >= 2 and fields[1] == name
        for line in output.splitlines()
    )


class FFmpegTools:
    timeout_seconds: ClassVar[int] = 30
    output_tail_bytes: ClassVar[int] = 65_536

    def __init__(self, executable: Path, version: str) -> None:
        self.executable = executable.resolve(strict=True)
        self.version = version

    @classmethod
    def discover(cls) -> FFmpegTools:
        candidate = shutil.which("ffmpeg")
        if candidate is None:
            raise FFmpegToolError("FFmpeg was not found on PATH")
        executable = Path(candidate).resolve(strict=True)
        tools = cls(executable, "")
        tools._preflight()
        return tools

    @staticmethod
    def _excerpt(output: str | bytes | None) -> str:
        if output is None:
            return ""
        if isinstance(output, bytes):
            text = output.decode("utf-8", errors="replace")
        else:
            text = output
        return text.strip()[-400:]

    def _command(self, args: list[str]) -> list[str]:
        return [str(self.executable), "-nostdin", "-hide_banner", *args]

    @classmethod
    def _read_tail(cls, path: Path) -> str:
        with path.open("rb") as stream:
            stream.seek(0, os.SEEK_END)
            size = stream.tell()
            stream.seek(max(0, size - cls.output_tail_bytes))
            return stream.read(cls.output_tail_bytes).decode("utf-8", errors="replace")

    @staticmethod
    def _kill_process_tree(process: subprocess.Popen[bytes]) -> None:
        if os.name == "nt":
            system_root = Path(os.environ.get("SystemRoot", r"C:\Windows"))
            taskkill = system_root / "System32" / "taskkill.exe"
            if taskkill.is_file():
                try:
                    subprocess.run(
                        [
                            str(taskkill),
                            "/PID",
                            str(process.pid),
                            "/T",
                            "/F",
                        ],
                        stdin=subprocess.DEVNULL,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        check=False,
                        timeout=10,
                        creationflags=subprocess.CREATE_NO_WINDOW,
                    )
                except OSError, subprocess.TimeoutExpired:
                    pass
            if process.poll() is None:
                process.kill()
            return
        try:
            getattr(os, "killpg")(process.pid, getattr(signal, "SIGKILL"))
        except ProcessLookupError:
            pass

    def _run(
        self,
        args: list[str],
        *,
        timeout: int | None = None,
        fail_on_stderr: bool = False,
    ) -> subprocess.CompletedProcess[str]:
        command = self._command(args)
        duration = self.timeout_seconds if timeout is None else timeout
        try:
            with tempfile.TemporaryDirectory(prefix="native-ffmpeg-") as private:
                stdout_path = Path(private) / "stdout"
                stderr_path = Path(private) / "stderr"
                with (
                    stdout_path.open("wb") as stdout_file,
                    stderr_path.open("wb") as stderr_file,
                ):
                    process = subprocess.Popen(
                        command,
                        stdin=subprocess.DEVNULL,
                        stdout=stdout_file,
                        stderr=stderr_file,
                        creationflags=(
                            subprocess.CREATE_NEW_PROCESS_GROUP
                            if os.name == "nt"
                            else 0
                        ),
                        start_new_session=os.name != "nt",
                    )
                    try:
                        returncode = process.wait(timeout=duration)
                    except subprocess.TimeoutExpired as exc:
                        self._kill_process_tree(process)
                        process.wait()
                        stdout_file.flush()
                        stderr_file.flush()
                        excerpt = self._excerpt(self._read_tail(stderr_path))
                        suffix = f"; stderr: {excerpt}" if excerpt else ""
                        raise FFmpegToolError(
                            f"FFmpeg timed out after {duration}s{suffix}"
                        ) from exc
                    stdout_file.flush()
                    stderr_file.flush()
                    stderr_present = stderr_path.stat().st_size > 0
                    result = subprocess.CompletedProcess(
                        command,
                        returncode,
                        self._read_tail(stdout_path),
                        self._read_tail(stderr_path),
                    )
        except OSError as exc:
            raise FFmpegToolError(f"could not execute FFmpeg: {exc}") from exc

        if result.returncode or (fail_on_stderr and stderr_present):
            excerpt = self._excerpt(result.stderr)
            suffix = f"; stderr: {excerpt}" if excerpt else ""
            status = (
                f"status {result.returncode}"
                if result.returncode
                else "reported an error"
            )
            raise FFmpegToolError(f"FFmpeg {status}{suffix}")
        return result

    def _preflight(self) -> None:
        version_result = self._run(["-version"], timeout=10)
        version_lines = (version_result.stdout or version_result.stderr).splitlines()
        if not version_lines or not version_lines[0].startswith("ffmpeg version "):
            raise FFmpegToolError("FFmpeg -version returned no recognizable version")
        self.version = version_lines[0]

        formats = self._run(["-formats"], timeout=10)
        format_lines = (formats.stdout or "") + "\n" + (formats.stderr or "")
        flags = ""
        for line in format_lines.splitlines():
            fields = line.split()
            if len(fields) >= 2 and fields[1] == "ast":
                flags = fields[0]
                break
        if "E" not in flags or "D" not in flags:
            raise FFmpegToolError("FFmpeg AST muxer and demuxer are required")

        codecs = self._run(["-codecs"], timeout=10)
        codec_lines = (codecs.stdout or "") + "\n" + (codecs.stderr or "")
        if not has_named_capabilities(codec_lines, "pcm_s16be_planar", "DE"):
            raise FFmpegToolError(
                "FFmpeg pcm_s16be_planar decoder and encoder are required"
            )

    def encode(
        self, asset_id: str, pcm_path: Path, native_path: Path, info: PCMFormat
    ) -> None:
        del asset_id
        loop_start_ms, loop_end_ms = 32, 192
        if (
            loop_start_ms * info.rate // 1_000 != 1_024
            or loop_end_ms * info.rate // 1_000 != 6_144
        ):
            raise ValueError("FFmpeg fixture loop settings require 32 kHz PCM")
        self._run(
            [
                "-v",
                "error",
                "-xerror",
                "-n",
                "-f",
                "s16le",
                "-ar",
                str(info.rate),
                "-ac",
                str(info.channels),
                "-i",
                str(pcm_path),
                "-map",
                "0:a:0",
                "-c:a",
                "pcm_s16be_planar",
                "-f",
                "ast",
                "-loopstart",
                str(loop_start_ms),
                "-loopend",
                str(loop_end_ms),
                str(native_path),
            ],
            fail_on_stderr=True,
        )

    def decode(
        self, asset_id: str, native_path: Path, pcm_path: Path, info: PCMFormat
    ) -> None:
        del asset_id, info
        self._run(
            [
                "-v",
                "error",
                "-xerror",
                "-n",
                "-i",
                str(native_path),
                "-map",
                "0:a:0",
                "-c:a",
                "pcm_s16le",
                "-f",
                "s16le",
                str(pcm_path),
            ],
            fail_on_stderr=True,
        )

    def assert_stereo(self, native_path: Path) -> None:
        result = self._run(
            [
                "-v",
                "info",
                "-i",
                str(native_path),
                "-map",
                "0:a:0",
                "-f",
                "null",
                "-",
            ]
        )
        stream_info = (result.stdout or "") + "\n" + (result.stderr or "")
        if "stereo" not in stream_info.lower():
            excerpt = self._excerpt(stream_info)
            raise FFmpegToolError(
                f"rebuilt AST did not decode as stereo; stream info: {excerpt}"
            )
