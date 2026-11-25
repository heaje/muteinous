import math
import struct
from typing import cast

import pytest

from muteinous.core.audio.pcm import Curve, PCMFormat, Representation, censor_blocks
from muteinous.core.audio.wav import WaveStorage

pytestmark = pytest.mark.portable


@pytest.mark.parametrize("mask", [0x40000, 0x80000000])
def test_reserved_channel_mask_bits_are_rejected(mask: int) -> None:
    with pytest.raises(ValueError, match="layout"):
        PCMFormat(48000, 1, "s16", 1, mask)


@pytest.mark.parametrize(("channels", "mask"), [(2, 1), (1, 3)])
def test_channel_mask_bit_count_must_match_channels(channels: int, mask: int) -> None:
    with pytest.raises(ValueError, match="channel mask"):
        PCMFormat(48000, channels, "s16", 1, mask)


@pytest.mark.parametrize("mask", [0, 1, 0x20000, 3])
def test_valid_channel_masks_are_supported(mask: int) -> None:
    channels = mask.bit_count() if mask else 1
    info = PCMFormat(48000, channels, "s16", 1, mask)
    assert WaveStorage().supports(info)


@pytest.mark.parametrize(
    "representation",
    [cast(Representation, value) for value in ("s64", "u16", "f16", "")],
)
def test_unsupported_sample_representations_are_rejected(
    representation: Representation,
) -> None:
    with pytest.raises(ValueError, match="sample representation"):
        PCMFormat(48000, 1, representation, 1)


def test_outward_rounding_and_all_channels() -> None:
    info = PCMFormat(10, 2, "s16", 5, 3)
    original = bytes(range(20))
    edited = b"".join(censor_blocks(info, [original[:8], original[8:]], [(0.11, 0.29)]))
    assert edited == original[:4] + bytes(8) + original[12:]


@pytest.mark.parametrize(
    "start,end",
    [(-0.01, 0.1), (0.1, 0.1), (0.2, 0.1), (0, 1.01), (math.nan, 0.1), (0, math.inf)],
)
def test_invalid_interval(start: float, end: float) -> None:
    with pytest.raises(ValueError):
        list(
            censor_blocks(
                PCMFormat(10, 1, "s16", 10),
                [bytes(20)],
                [(start, end)],
                before=10,
                after=10,
            )
        )


def test_boundaries_and_merged_ranges() -> None:
    info = PCMFormat(10, 1, "u8", 10)
    # Padding joins the intervals; no internal fade, and boundary margin is clipped.
    out = b"".join(
        censor_blocks(
            info,
            [bytes([200] * 10)],
            [(0.1, 0.3), (0.5, 0.9)],
            before=0.2,
            after=0.2,
            fade=1,
        )
    )
    assert out == bytes([200] + [128] * 8 + [200])


@pytest.mark.parametrize(
    "ranges",
    [
        [(0.25, 0.5), (0.5, 0.75)],  # exactly touching in time
        [(0.26, 0.49), (0.51, 0.74)],  # touching only after frame rounding
        [(0.5, 0.75), (0.25, 0.625)],  # unsorted overlapping
    ],
)
def test_merge_touching_and_overlapping_ranges(
    ranges: list[tuple[float, float]],
) -> None:
    info = PCMFormat(8, 1, "s16", 8)
    data = b"\xff\x01" * 8
    assert b"".join(censor_blocks(info, [data], ranges)) == (
        data[:4] + bytes(8) + data[12:]
    )


@pytest.mark.parametrize("curve", [None, "linear", "cosine", "equal_power"])
def test_rounded_overlap_merges_fade_regions(curve: Curve | None) -> None:
    info = PCMFormat(10, 1, "s16", 10)
    frame = struct.pack("<h", 10000)
    original = frame * info.frames
    options = {} if curve is None else {"curve": curve}
    edited = b"".join(
        censor_blocks(
            info,
            [original],
            [(0.30, 0.36), (0.40, 0.47)],
            before=0.01,
            after=0.01,
            fade=0.1,
            **options,
        )
    )
    frames = [
        edited[index : index + info.frame_bytes]
        for index in range(0, len(edited), info.frame_bytes)
    ]
    # The rounded words cover frames 3 and 4; no internal fade may survive.
    assert frames[3:5] == [bytes(info.frame_bytes)] * 2
    # Only the outer margin is eligible for a fade; at its edge the gain is 1.
    assert frames[2] == frame
    assert frames[:2] == [frame] * 2
    assert frames[5:] == [frame] * 5


@pytest.mark.parametrize(
    "curve,gain",
    [
        ("linear", 0.25),
        ("cosine", (1 - math.cos(math.pi / 4)) / 2),
        ("equal_power", math.sin(math.pi / 8)),
    ],
)
def test_fades_only_in_margins(curve: Curve, gain: float) -> None:
    info = PCMFormat(16, 2, "f32", 16, 3)
    frame = struct.pack("<ff", 1.0, -0.5)
    data = frame * 16
    out = b"".join(
        censor_blocks(
            info,
            [data[:56], data[56:]],
            [(0.375, 0.625)],
            before=0.25,
            after=0.25,
            fade=0.5,
            curve=curve,
        )
    )
    values = list(struct.iter_unpack("<ff", out))
    assert out[:16] == data[:16] and out[-16:] == data[-16:]
    assert values[5] == pytest.approx((gain, -0.5 * gain))
    assert values[10] == pytest.approx((gain, -0.5 * gain))
    assert values[6:10] == [(0.0, 0.0)] * 4


def test_default_cosine_and_zero_margin() -> None:
    info = PCMFormat(16, 1, "s16", 16)
    data = struct.pack("<h", 10000) * 16
    ranges = [(0.375, 0.625)]
    default = list(
        censor_blocks(info, [data], ranges, before=0.25, after=0.25, fade=0.25)
    )
    cosine = list(
        censor_blocks(
            info, [data], ranges, before=0.25, after=0.25, fade=0.25, curve="cosine"
        )
    )
    assert default == cosine
    assert b"".join(censor_blocks(info, [data], ranges, fade=1)) == (
        data[:12] + bytes(8) + data[20:]
    )


@pytest.mark.parametrize("duration", [-1.0, math.nan, math.inf])
def test_invalid_margin_or_fade(duration: float) -> None:
    info = PCMFormat(16, 1, "s16", 16)
    data = bytes(32)
    with pytest.raises(ValueError):
        list(censor_blocks(info, [data], [], before=duration))
    with pytest.raises(ValueError):
        list(censor_blocks(info, [data], [], after=duration))
    with pytest.raises(ValueError):
        list(censor_blocks(info, [data], [], fade=duration))


@pytest.mark.parametrize(
    "blocks", [[b"\x00"], [bytes(6)], [bytes(2)], [bytes(8194)], [b"", bytes(4)]]
)
def test_invalid_blocks(blocks: list[bytes]) -> None:
    with pytest.raises(ValueError):
        list(censor_blocks(PCMFormat(10, 1, "s16", 2), blocks, []))


def test_unaffected_float_bit_patterns() -> None:
    info = PCMFormat(4, 1, "f32", 4)
    # Negative zero, payload-bearing NaN, finite sample and subnormal.
    original = struct.pack("<IIII", 0x80000000, 0x7FC01234, 0x3F800000, 1)
    edited = b"".join(censor_blocks(info, [original], [(0.5, 0.75)]))
    assert edited == original[:8] + bytes(4) + original[12:]
