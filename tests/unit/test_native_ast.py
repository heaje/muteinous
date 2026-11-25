import math

import pytest

from experiments.native_ast.ast_core import frame_boundary_seconds

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
