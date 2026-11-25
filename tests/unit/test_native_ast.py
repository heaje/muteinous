import math
import struct

import pytest

from experiments.native_ast.ast_core import (
    NativeValidationError,
    frame_boundary_seconds,
    validate_fixture,
)
from muteinous.core.audio.pcm import PCMFormat

pytestmark = pytest.mark.portable


def test_every_frame_boundary_maps_exactly_at_supported_pcm_rates() -> None:
    frames = 8_192
    for rate in (32_000, 44_100, 48_000):
        for frame in range(frames + 1):
            start = frame_boundary_seconds(frame, rate, frames, "start")
            assert math.floor(start * rate) == frame

            end = frame_boundary_seconds(frame, rate, frames, "end")
            if frame == frames:
                assert end == frames / rate
            else:
                assert math.ceil(end * rate) == frame


def test_zero_frame_ast_fixture_is_refused() -> None:
    info = PCMFormat(32_000, 2, "s16", 0, 3)
    header = struct.pack(
        ">4sI4H5I",
        b"STRM",
        0,
        1,
        16,
        2,
        0xFFFF,
        info.rate,
        info.frames,
        0,
        0,
        0,
    )
    header += bytes(4) + struct.pack("<I", 0x7F) + bytes(20)

    with pytest.raises(NativeValidationError, match="zero-frame AST is unsupported"):
        validate_fixture(header, b"", info=info, loop_start=0, loop_end=0)
