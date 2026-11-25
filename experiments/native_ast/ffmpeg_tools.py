"""Trusted, bounded subprocess wrapper used only by manual AST experiments."""

import shutil
import subprocess
from pathlib import Path
from typing import ClassVar

from muteinous.core.audio.pcm import PCMFormat


class FFmpegToolError(RuntimeError):
    """A native-tool preflight or subprocess failed with bounded diagnostics."""


class FFmpegTools:
    timeout_seconds: ClassVar[int] = 30

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

    def _run(
        self,
        args: list[str],
        *,
        timeout: int | None = None,
        fail_on_stderr: bool = False,
    ) -> subprocess.CompletedProcess[str]:
        try:
            result = subprocess.run(
                [str(self.executable), "-nostdin", "-hide_banner", *args],
                capture_output=True,
                check=False,
                text=True,
                timeout=timeout or self.timeout_seconds,
            )
        except subprocess.TimeoutExpired as exc:
            excerpt = self._excerpt(exc.stderr)
            suffix = f"; stderr: {excerpt}" if excerpt else ""
            raise FFmpegToolError(
                f"FFmpeg timed out after {timeout or self.timeout_seconds}s{suffix}"
            ) from exc
        except OSError as exc:
            raise FFmpegToolError(f"could not execute FFmpeg: {exc}") from exc

        if result.returncode or (fail_on_stderr and result.stderr.strip()):
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
        if not any(
            len(fields := line.split()) >= 2
            and "E" in fields[0]
            and fields[1] == "pcm_s16be_planar"
            for line in codec_lines.splitlines()
        ):
            raise FFmpegToolError("FFmpeg pcm_s16be_planar encoder is required")

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
