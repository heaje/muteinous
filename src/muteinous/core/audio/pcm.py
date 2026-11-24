"""Segment-local, codec-independent PCM censorship (D22, D32–D39)."""

import math
import struct
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from itertools import chain
from typing import Literal

BLOCK_FRAMES = 4096
Curve = Literal["linear", "cosine", "equal_power"]
Representation = Literal["u8", "s16", "s24", "s32", "f32", "f64"]


@dataclass(frozen=True)
class PCMFormat:
    rate: int
    channels: int
    representation: Representation
    frames: int
    channel_mask: int = 0  # WAVE speaker order; zero means unspecified, not stereo.

    def __post_init__(self) -> None:
        if not (0 < self.rate <= 0xFFFFFFFF and 0 < self.channels <= 32):
            raise ValueError("unsupported rate or channel count")
        if self.frames < 0 or not 0 <= self.channel_mask <= 0xFFFFFFFF:
            raise ValueError("invalid frame count or layout")
        if self.channel_mask and self.channel_mask.bit_count() != self.channels:
            raise ValueError("channel mask does not match channel count")
        if self.representation not in ("u8", "s16", "s24", "s32", "f32", "f64"):
            raise ValueError("unsupported sample representation")

    @property
    def width(self) -> int:
        return int(self.representation[1:]) // 8

    @property
    def frame_bytes(self) -> int:
        return self.channels * self.width


@dataclass(frozen=True)
class _Region:
    start: int
    end: int
    word_start: int
    word_end: int


def _regions(
    info: PCMFormat, ranges: Iterable[tuple[float, float]], before: float, after: float
) -> list[_Region]:
    duration = info.frames / info.rate
    padded = []
    for start, end in ranges:
        if not (
            math.isfinite(start)
            and math.isfinite(end)
            and 0 <= start < end <= duration
        ):
            raise ValueError("invalid segment-relative interval")
        padded.append((max(0.0, start - before), min(duration, end + after), start, end))
    merged: list[tuple[float, float, float, float]] = []
    for start, end, first, last in sorted(padded):
        if merged and start <= merged[-1][1]:
            a, b, c, d = merged.pop()
            merged.append((a, max(b, end), min(c, first), max(d, last)))
        else:
            merged.append((start, end, first, last))

    def upper(seconds: float) -> int:
        return info.frames if seconds == duration else math.ceil(seconds * info.rate)

    result: list[_Region] = []
    for start, end, first, last in merged:
        region = _Region(
            math.floor(start * info.rate),
            upper(end),
            math.floor(first * info.rate),
            upper(last),
        )
        if not (
            0 <= region.start <= region.word_start < region.word_end
            <= region.end <= info.frames
        ):
            raise ValueError("interval cannot be represented safely")
        # Distinct time ranges can touch or overlap after outward frame rounding.
        if result and region.start <= result[-1].end:
            old = result.pop()
            region = _Region(
                old.start,
                max(old.end, region.end),
                min(old.word_start, region.word_start),
                max(old.word_end, region.word_end),
            )
        result.append(region)
    return result


def _gain(fraction: float, curve: Curve) -> float:
    if curve == "linear":
        return fraction
    if curve == "cosine":
        return (1 - math.cos(math.pi * fraction)) / 2
    return math.sin(math.pi * fraction / 2)


def _scale(sample: bytes, representation: Representation, gain: float) -> bytes:
    if gain == 1:
        return sample
    if representation.startswith("f"):
        code = "<f" if representation == "f32" else "<d"
        value = float(struct.unpack(code, sample)[0])
        if not math.isfinite(value):
            raise ValueError("non-finite sample in fade")
        return struct.pack(code, value * gain)
    unsigned = representation == "u8"
    bias = 128 if unsigned else 0
    value_int = int.from_bytes(sample, "little", signed=not unsigned) - bias
    return (round(value_int * gain) + bias).to_bytes(
        len(sample), "little", signed=not unsigned
    )


def checked_blocks(info: PCMFormat, blocks: Iterable[bytes]) -> Iterator[bytes]:
    """Reject malformed, oversized, short or excess streams; do not buffer the asset."""
    count = 0
    for block in blocks:
        if (
            not block
            or len(block) % info.frame_bytes
            or len(block) > BLOCK_FRAMES * info.frame_bytes
        ):
            raise ValueError("invalid PCM block")
        count += len(block) // info.frame_bytes
        if count > info.frames:
            raise ValueError("excess PCM frames")
        yield block
    if count != info.frames:
        raise ValueError("missing PCM frames")


def censor_blocks(
    info: PCMFormat,
    blocks: Iterable[bytes],
    ranges: Iterable[tuple[float, float]],
    *,
    before: float = 0,
    after: float = 0,
    fade: float = 0,
    curve: Curve = "cosine",
) -> Iterator[bytes]:
    """Consume original-quality interleaved little-endian PCM in bounded blocks.

    The caller must exhaust and validate the stream before accepting its output.
    """
    if any(not math.isfinite(v) or v < 0 for v in (before, after, fade)):
        raise ValueError("invalid margin or fade duration")
    if curve not in ("linear", "cosine", "equal_power"):
        raise ValueError("unknown fade curve")
    regions = _regions(info, ranges, before, after)
    fade_frames = math.floor(min(fade, info.frames / info.rate) * info.rate)
    silence = (
        b"\x80" if info.representation == "u8" else bytes(info.width)
    ) * info.channels
    index = offset = 0
    for block in checked_blocks(info, blocks):
        end = offset + len(block) // info.frame_bytes
        if index == len(regions) or regions[index].start >= end:
            yield block
            offset = end
            continue
        edited = bytearray(block)
        while index < len(regions) and regions[index].start < end:
            region = regions[index]
            down = min(fade_frames, region.word_start - region.start)
            up = min(fade_frames, region.end - region.word_end)
            a, b = max(offset, region.start), min(end, region.end)
            mute_a = max(a, region.start + down)
            mute_b = min(b, region.end - up)
            if mute_a < mute_b:
                lo = (mute_a - offset) * info.frame_bytes
                hi = (mute_b - offset) * info.frame_bytes
                edited[lo:hi] = silence * (mute_b - mute_a)
            for frame in chain(
                range(a, min(b, region.start + down)),
                range(max(a, region.end - up), b),
            ):
                pos = (frame - offset) * info.frame_bytes
                if frame < region.start + down:
                    gain = _gain((region.start + down - frame) / down, curve)
                else:
                    gain = _gain((frame - (region.end - up) + 1) / up, curve)
                for channel in range(info.channels):
                    sample = pos + channel * info.width
                    edited[sample : sample + info.width] = _scale(
                        block[sample : sample + info.width], info.representation, gain
                    )
            if region.end > end:
                break
            index += 1
        yield bytes(edited)
        offset = end
