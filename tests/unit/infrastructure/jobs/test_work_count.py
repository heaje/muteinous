"""Unit tests for defensible work-count percentages."""

from __future__ import annotations

import pytest

from muteinous.infrastructure.jobs.queue import WorkCount

pytestmark = pytest.mark.portable


@pytest.mark.parametrize(
    ("count", "percentage"),
    [
        (WorkCount(3), None),
        (WorkCount(3, 4), None),
        (WorkCount(3, 10, True), 30.0),
        (WorkCount(1, 0, True), None),
        (WorkCount(5, 4, True), None),
        (WorkCount(-1, 4, True), None),
    ],
)
def test_percentage_requires_reliable_denominator(
    count: WorkCount, percentage: float | None
) -> None:
    assert count.percentage == percentage


def test_percentage_handles_zero_complete_and_fractional_totals() -> None:
    assert WorkCount(0, 0, True).percentage is None
    assert WorkCount(0, 3, True).percentage == 0.0
    assert WorkCount(3, 3, True).percentage == 100.0
    assert WorkCount(1, 3, True).percentage == pytest.approx(100 / 3)
