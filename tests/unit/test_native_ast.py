import math
import struct
from typing import Literal

import pytest

from experiments.native_ast.ast_core import (
    FRAMES,
    INFO,
    Edit,
    NativeValidationError,
    build_canonical_ast,
    frame_boundary_seconds,
    group_edits,
    parse_ast,
    validate_fixture,
)
from muteinous.core.audio.pcm import PCMFormat

pytestmark = pytest.mark.portable


def _fixture_pcm() -> bytes:
    return b"".join(
        struct.pack(
            "<hh",
            (frame * 67) % 65_536 - 32_768,
            32_767 - (frame * 137) % 65_536,
        )
        for frame in range(FRAMES)
    )


def _partitioned_ast(pcm: bytes, widths: tuple[int, ...]) -> bytes:
    if sum(widths) != FRAMES * 2 or any(width % 2 for width in widths):
        raise AssertionError("test partition must account for every stereo frame")
    body_size = sum(32 + 2 * width for width in widths)
    output = bytearray(
        struct.pack(
            ">4sI4H5I",
            b"STRM",
            body_size,
            1,
            16,
            2,
            0xFFFF,
            INFO.rate,
            INFO.frames,
            1024,
            6144,
            widths[0],
        )
    )
    output.extend(bytes(4) + struct.pack("<I", 0x7F) + bytes(20))
    frame_offset = 0
    for width in widths:
        packet_frames = width // 2
        left = bytearray()
        right = bytearray()
        for frame in range(frame_offset, frame_offset + packet_frames):
            left_sample, right_sample = struct.unpack_from("<hh", pcm, frame * 4)
            left.extend(struct.pack(">h", left_sample))
            right.extend(struct.pack(">h", right_sample))
        output.extend(struct.pack(">4sI", b"BLCK", width))
        output.extend(bytes(24))
        output.extend(left)
        output.extend(right)
        frame_offset += packet_frames
    return bytes(output)


def _malformed(native: bytes, case: str) -> bytes:
    result = bytearray(native)
    if case == "truncated header":
        return bytes(result[:32])
    if case == "truncated block header":
        del result[80:]
        struct.pack_into(">I", result, 4, len(result) - 64)
        return bytes(result)
    if case == "truncated file":
        return bytes(result[:-1])
    if case == "truncated payload":
        del result[-2:]
        struct.pack_into(">I", result, 4, len(result) - 64)
        return bytes(result)
    if case == "bad magic":
        result[:4] = b"NOPE"
    elif case == "wrong codec":
        struct.pack_into(">H", result, 8, 0)
    elif case == "wrong bits":
        struct.pack_into(">H", result, 10, 24)
    elif case == "wrong channels":
        struct.pack_into(">H", result, 12, 1)
    elif case == "wrong loop flag":
        struct.pack_into(">H", result, 14, 0)
    elif case == "wrong rate":
        struct.pack_into(">I", result, 16, INFO.rate + 1)
    elif case == "wrong frame count":
        struct.pack_into(">I", result, 20, INFO.frames - 1)
    elif case == "wrong loop start":
        struct.pack_into(">I", result, 24, 1025)
    elif case == "wrong loop end":
        struct.pack_into(">I", result, 28, 6143)
    elif case == "wrong first block size":
        struct.pack_into(">I", result, 32, 8192)
    elif case == "reserved header":
        result[36] = 1
    elif case == "bad block tag":
        result[64:68] = b"NOPE"
    elif case == "even but wrong block size":
        struct.pack_into(">I", result, 68, 4098)
    elif case == "odd block size":
        struct.pack_into(">I", result, 68, 4097)
    elif case == "block padding":
        result[72] = 1
    elif case == "trailing bytes":
        result.extend(b"\x00")
        struct.pack_into(">I", result, 4, len(result) - 64)
    elif case == "sample mismatch":
        result[96] ^= 1
    else:
        raise AssertionError(f"unknown malformed fixture: {case}")
    return bytes(result)


@pytest.mark.parametrize(
    ("case", "reason"),
    [
        ("truncated header", "truncated STRM header"),
        ("truncated block header", "truncated BLCK header"),
        ("truncated file", "STRM file size mismatch"),
        ("truncated payload", "truncated BLCK payload"),
        ("bad magic", "invalid STRM magic"),
        ("wrong codec", "unsupported AST codec"),
        ("wrong bits", "unsupported AST bit depth"),
        ("wrong channels", "unsupported AST channel count"),
        ("wrong loop flag", "AST loop flag mismatch"),
        ("wrong rate", "AST sample rate mismatch"),
        ("wrong frame count", "AST frame count mismatch"),
        ("wrong loop start", "AST loop bounds mismatch"),
        ("wrong loop end", "AST loop bounds mismatch"),
        ("wrong first block size", "noncanonical STRM first block size/partition"),
        ("reserved header", "noncanonical STRM reserved/header bytes"),
        ("bad block tag", "invalid BLCK tag"),
        ("even but wrong block size", "noncanonical AST block size/partition"),
        ("odd block size", "odd AST block size"),
        ("block padding", "nonzero BLCK padding"),
        ("trailing bytes", "unexpected trailing AST bytes"),
        ("sample mismatch", "PCM mismatch"),
    ],
)
def test_validator_refuses_malformed_or_noncanonical_ast(
    case: str, reason: str
) -> None:
    pcm = _fixture_pcm()
    with pytest.raises(NativeValidationError) as error:
        validate_fixture(
            _malformed(build_canonical_ast(pcm), case),
            pcm,
            asset_id="fixture-a",
        )
    assert str(error.value) == f"required asset fixture-a: native validation: {reason}"
    assert error.value.asset_id == "fixture-a"


@pytest.mark.parametrize(
    "widths",
    [
        (8192, 8192),
        (4096, 4096, 4096, 4094, 2),
    ],
)
def test_validator_rejects_alternate_block_partitions(
    widths: tuple[int, ...],
) -> None:
    pcm = _fixture_pcm()
    native = _partitioned_ast(pcm, widths)
    with pytest.raises(NativeValidationError) as error:
        validate_fixture(native, pcm, asset_id="partitioned")
    assert error.value.asset_id == "partitioned"
    assert error.value.detail in {
        "noncanonical STRM first block size/partition",
        "noncanonical AST block size/partition",
    }


def test_pure_python_writer_matches_its_strict_reader() -> None:
    pcm = _fixture_pcm()
    native = build_canonical_ast(pcm)
    parsed = parse_ast(native)
    assert parsed.pcm == pcm
    assert parsed.block_widths == (4096, 4096, 4096, 4096)
    assert validate_fixture(native, pcm) == 4
    assert native[36:40] == bytes(4)
    assert native[40:44] == struct.pack("<I", 0x7F)
    assert all(
        native[offset + 8 : offset + 32] == bytes(24)
        for offset in (64, 8288, 16512, 24736)
    )


@pytest.mark.parametrize("rate", [32_000, 44_100, 48_000])
@pytest.mark.parametrize("side", ["start", "end"])
def test_every_frame_boundary_rounds_to_exact_frame(
    rate: int, side: Literal["start", "end"]
) -> None:
    for frame in range(FRAMES + 1):
        seconds = frame_boundary_seconds(frame, rate, FRAMES, side)
        if side == "start":
            assert math.floor(seconds * rate) == frame
        elif seconds == FRAMES / rate:
            assert frame == FRAMES
        else:
            assert math.ceil(seconds * rate) == frame


def test_exact_duration_end_boundary_is_unchanged_for_2007_frames() -> None:
    assert frame_boundary_seconds(2007, 32_000, 2007, "end") == 2007 / 32_000


def test_frame_mapping_keeps_upstream_stereo_mask_and_merges_touching_edits() -> None:
    assert INFO == PCMFormat(32_000, 2, "s16", FRAMES, 3)
    assets = {"a": b"fixture", "b": b"fixture"}
    assert group_edits(
        assets,
        (
            Edit("a", 0, 4096, 1001, 1080),
            Edit("a", 1040, 2048, 40, 120),
            Edit("a", 1100, 2048, 30, 157),
        ),
    ) == {"a": [(1001, 1257)]}
