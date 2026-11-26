"""Opt-in synthetic Vorbis cross-decoder probe using SoX/libvorbisfile."""

import math
import shutil
import struct
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory

from muteinous.core.audio.pcm import PCMFormat
from muteinous.core.audio.wav import WaveStorage

from .ffmpeg_tools import OggFFmpegTools
from .manual_support import create_source_assets, snapshot
from .ogg_prepare import (
    INFO,
    measure_lossy_effects,
    prepare_ogg,
    verify_lossy_reconstruction,
)
from .shared_edit import QUALITY, _edits, _expected, _padded_ranges, _ranges


def run(args: list[str]) -> bytes:
    return subprocess.run(args, check=True, capture_output=True, timeout=30).stdout


def decode(sox: str, path: Path) -> bytes:
    for flag, expected in (("-r", INFO.rate), ("-c", INFO.channels), ("-s", INFO.frames)):
        if int(run([sox, "--i", flag, str(path)])) != expected:
            raise AssertionError(f"SoX {flag} mismatch for {path.name}")
    result = run([
        sox, "-D", str(path), "-t", "raw", "-e", "floating-point", "-b", "32", "-L", "-",
    ])
    if len(result) != INFO.frames * INFO.frame_bytes:
        raise AssertionError("independent decoded frame count mismatch")
    return result


def max_difference(first: bytes, second: bytes) -> float:
    if len(first) != len(second):
        raise AssertionError("cross-decoder frame count mismatch")
    differences = []
    for (a,), (b,) in zip(
        struct.iter_unpack("<f", first), struct.iter_unpack("<f", second), strict=True
    ):
        if not math.isfinite(a) or not math.isfinite(b):
            raise AssertionError("nonfinite decoded sample")
        differences.append(abs(a - b))
    return max(differences)


def ffmpeg_native(ffmpeg: str, path: Path) -> bytes:
    # Explicitly choose the native decoder, not the libvorbis wrapper.
    return run([
        ffmpeg, "-v", "error", "-xerror", "-c:a", "vorbis", "-i", str(path),
        "-map", "0:a:0", "-c:a", "pcm_f32le", "-f", "f32le", "-",
    ])


def main() -> None:
    sox = shutil.which("sox")
    ffmpeg = shutil.which("ffmpeg")
    if sox is None or ffmpeg is None:
        raise RuntimeError("SoX with Vorbis support and FFmpeg are required")
    print(run([sox, "--version"]).decode().strip())
    tools = OggFFmpegTools.discover()
    print(tools.version)
    with TemporaryDirectory(prefix="muteinous-independent-ogg-") as temporary:
        root = Path(temporary)
        assets, originals, metadata = create_source_assets(
            root, tools, ("a", "b", "start", "end", "untouched")
        )
        stage = root / "stage"
        stage.mkdir()
        before = snapshot(root)

        def encoder(asset: str, pcm: Path, native: Path, info: PCMFormat) -> None:
            source = metadata[asset]
            tools.encode_vorbis(
                asset, pcm, native, info,
                nominal_bitrate=source.nominal_bitrate, comments=source.comments,
            )

        staged = prepare_ogg(
            stage, assets, originals, _edits(), decoder=tools.decode, encoder=encoder,
            info=INFO, storage=WaveStorage(), quality=QUALITY,
        )
        if set(staged) != set(_ranges()) or snapshot(root) != before:
            raise AssertionError("grouping or scratch/source integrity mismatch")
        for asset, native in staged.items():
            source_path = root / f"{asset}.ogg"
            rebuilt_path = root / f"{asset}.independent.ogg"
            rebuilt_path.write_bytes(native)
            original = decode(sox, source_path)
            rebuilt = decode(sox, rebuilt_path)
            padded = _padded_ranges()[asset]
            requested = _ranges()[asset]
            verify_lossy_reconstruction(
                asset, original, _expected(original, padded), rebuilt, padded, INFO,
                policy=QUALITY, requested_ranges=requested,
            )
            metrics = measure_lossy_effects(
                original, rebuilt, padded, INFO, policy=QUALITY, requested_ranges=requested
            )
            ff_source = ffmpeg_native(ffmpeg, source_path)
            if ff_source != originals[asset]:
                raise AssertionError("FFmpeg source decode differs from explicit native decoder")
            ff_rebuilt = ffmpeg_native(ffmpeg, rebuilt_path)
            outside = metrics.outside_regions
            guard = metrics.guard_regions
            print(
                f"{asset}: peak={max(metrics.edited_region_peaks):.9g}; "
                f"outside SNR min={min(r.snr_db for r in outside):.6f}, "
                f"max error={max(r.maximum_absolute_error for r in outside):.9g}; "
                f"guard SNR min={min(r.snr_db for r in guard):.6f}, "
                f"max error={max(r.maximum_absolute_error for r in guard):.9g}; "
                f"cross-decoder max source={max_difference(original, ff_source):.9g}, "
                f"rebuilt={max_difference(rebuilt, ff_rebuilt):.9g}"
            )
            rebuilt_path.unlink()
        if snapshot(root) != before:
            raise AssertionError("independent probe changed original or scratch")
    print("PASS: independent decoder fidelity, grouping, and cleanup")


if __name__ == "__main__":
    main()
