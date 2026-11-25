"""Synthetic-only helpers shared by the two opt-in FFmpeg scripts."""

import math
import struct
from collections import Counter
from pathlib import Path

from .ffmpeg_tools import OggFFmpegTools
from .ogg_core import VorbisInfo, parse_ogg_vorbis
from .ogg_prepare import INFO

BITRATE = 128_000


def synthetic_pcm(seed: int) -> bytes:
    """Deterministic 1.5-second stereo tone plus low-level LCG noise."""
    state = (0x13579BDF + seed * 0x10203) & 0xFFFFFFFF
    output = bytearray()
    for frame in range(INFO.frames):
        state = (1664525 * state + 1013904223) & 0xFFFFFFFF
        left_noise = ((state >> 8) / 0xFFFFFF) * 2.0 - 1.0
        state = (1664525 * state + 1013904223) & 0xFFFFFFFF
        right_noise = ((state >> 8) / 0xFFFFFF) * 2.0 - 1.0
        time = frame / INFO.rate
        left = 0.18 * math.sin(2 * math.pi * 440.0 * time) + 0.012 * left_noise
        right = 0.16 * math.sin(2 * math.pi * 660.0 * time + 0.3) + 0.012 * right_noise
        output.extend(struct.pack("<ff", left, right))
    return bytes(output)


def comments_for(asset_id: str) -> tuple[tuple[str, str], ...]:
    return (
        ("LOOPSTART", "11025"),
        ("LOOPLENGTH", "22050"),
        ("EXPERIMENT", "synthetic-vorbis"),
        ("ASSET", asset_id),
    )


def create_source_assets(
    root: Path, tools: OggFFmpegTools, asset_ids: tuple[str, ...]
) -> tuple[dict[str, bytes], dict[str, bytes], dict[str, VorbisInfo]]:
    assets: dict[str, bytes] = {}
    originals: dict[str, bytes] = {}
    metadata: dict[str, VorbisInfo] = {}
    for index, asset_id in enumerate(asset_ids):
        source_pcm = synthetic_pcm(index)
        raw_path = root / f"{asset_id}.source.f32le"
        native_path = root / f"{asset_id}.ogg"
        decoded_path = root / f"{asset_id}.source-decoded.f32le"
        raw_path.write_bytes(source_pcm)
        tools.encode_vorbis(
            asset_id,
            raw_path,
            native_path,
            INFO,
            nominal_bitrate=BITRATE,
            comments=comments_for(asset_id),
        )
        native = native_path.read_bytes()
        parsed = parse_ogg_vorbis(native, expected_frames=INFO.frames)
        if parsed.channels != INFO.channels or parsed.rate != INFO.rate:
            raise AssertionError("FFmpeg Ogg source profile mismatch")
        expected_comments = Counter(
            (name.casefold(), value) for name, value in comments_for(asset_id)
        )
        if not expected_comments <= parsed.comment_multiset:
            raise AssertionError("FFmpeg Ogg source comment tags did not round-trip")
        tools.decode(asset_id, native_path, decoded_path, INFO)
        decoded = decoded_path.read_bytes()
        if len(decoded) != INFO.frames * INFO.frame_bytes:
            raise AssertionError("FFmpeg source decode frame count mismatch")
        assets[asset_id] = native
        originals[asset_id] = decoded
        metadata[asset_id] = parsed
    return assets, originals, metadata


def snapshot(root: Path) -> tuple[dict[str, bytes], tuple[str, ...]]:
    files = {
        str(path.relative_to(root)): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }
    directories = tuple(
        sorted(str(path.relative_to(root)) for path in root.rglob("*") if path.is_dir())
    )
    return files, directories
