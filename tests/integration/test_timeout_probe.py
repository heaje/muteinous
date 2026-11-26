"""Deliberate D161 timeout negative-control probe; this test must never be merged."""

import time


def test_required_check_step_timeout_negative_control() -> None:
    """Sleep past the required pytest step's ten-minute timeout."""
    time.sleep(900)
