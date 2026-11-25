"""Bounded FFmpeg/libvorbis wrapper for manual synthetic Ogg experiments."""

import shutil
from pathlib import Path

from experiments.native_ast.ffmpeg_tools import FFmpegToolError, FFmpegTools
from muteinous.core.audio.pcm import PCMFormat


class OggFFmpegTools(FFmpegTools):
    """Reuse the AST experiment's absolute-path, timeout and stderr safeguards."""

    @classmethod
    def discover(cls) -> OggFFmpegTools:
        candidate = shutil.which("ffmpeg")
        if candidate is None:
            raise FFmpegToolError("FFmpeg was not found on PATH")
        tools = cls(Path(candidate).resolve(strict=True), "")
        tools._preflight()
        return tools

    def _preflight(self) -> None:
        version = self._run(["-version"], timeout=10)
        lines = (version.stdout or version.stderr).splitlines()
        if not lines or not lines[0].startswith("ffmpeg version "):
            raise FFmpegToolError("FFmpeg -version returned no recognizable version")
        self.version = lines[0]

        formats = self._run(["-formats"], timeout=10)
        format_lines = (formats.stdout or "") + "\n" + (formats.stderr or "")
        ogg_flags = next(
            (
                line.split()[0]
                for line in format_lines.splitlines()
                if len(line.split()) >= 2 and line.split()[1] == "ogg"
            ),
            "",
        )
        if "D" not in ogg_flags or "E" not in ogg_flags:
            raise FFmpegToolError("FFmpeg Ogg demuxer and muxer are required")

        encoders = self._run(["-encoders"], timeout=10)
        encoder_lines = (encoders.stdout or "") + "\n" + (encoders.stderr or "")
        if not any(
            len(fields := line.split()) >= 2 and fields[1] == "libvorbis"
            for line in encoder_lines.splitlines()
        ):
            raise FFmpegToolError("FFmpeg libvorbis encoder is required")

        decoders = self._run(["-decoders"], timeout=10)
        decoder_lines = (decoders.stdout or "") + "\n" + (decoders.stderr or "")
        if not any(
            len(fields := line.split()) >= 2 and fields[1] == "vorbis"
            for line in decoder_lines.splitlines()
        ):
            raise FFmpegToolError("FFmpeg Vorbis decoder is required")

    def decode(
        self, asset_id: str, native_path: Path, pcm_path: Path, info: PCMFormat
    ) -> None:
        del asset_id
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
                "pcm_f32le",
                "-ar",
                str(info.rate),
                "-ac",
                str(info.channels),
                "-f",
                "f32le",
                str(pcm_path),
            ],
            fail_on_stderr=True,
        )

    def encode_vorbis(
        self,
        asset_id: str,
        pcm_path: Path,
        native_path: Path,
        info: PCMFormat,
        *,
        nominal_bitrate: int,
        comments: tuple[tuple[str, str], ...],
    ) -> None:
        del asset_id
        if info.representation != "f32" or nominal_bitrate <= 0:
            raise FFmpegToolError(
                "libvorbis requires f32 PCM and a positive source bitrate"
            )
        args = [
            "-v",
            "error",
            "-xerror",
            "-n",
            "-f",
            "f32le",
            "-ar",
            str(info.rate),
            "-ac",
            str(info.channels),
            "-i",
            str(pcm_path),
            "-map",
            "0:a:0",
            "-c:a",
            "libvorbis",
            "-b:a",
            str(nominal_bitrate),
        ]
        for name, value in comments:
            args.extend(["-metadata", f"{name}={value}"])
        args.extend(["-f", "ogg", str(native_path)])
        self._run(args, fail_on_stderr=True)
