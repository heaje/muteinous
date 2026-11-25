"""Unit tests for job queue construction and input validation."""

from __future__ import annotations

import pytest

from muteinous.infrastructure.jobs.queue import JobQueue

pytestmark = pytest.mark.portable


@pytest.mark.parametrize(
    ("progress_interval", "revalidate_interval"),
    [(0.0, 1.0), (1.0, float("inf"))],
)
def test_intervals_must_be_finite_and_positive(
    progress_interval: float, revalidate_interval: float
) -> None:
    queue: JobQueue | None = None
    try:
        with pytest.raises(ValueError):
            queue = JobQueue(
                {"cpu": 1},
                lambda _: None,
                progress_interval=progress_interval,
                revalidate_interval=revalidate_interval,
            )
    finally:
        if queue is not None:
            queue.close()


@pytest.mark.parametrize("capacities", [{"cpu": -1}, {"": 1}])
def test_reject_invalid_resource_configuration(capacities: dict[str, int]) -> None:
    queue: JobQueue | None = None
    try:
        with pytest.raises(ValueError):
            queue = JobQueue(capacities, lambda _: None)
    finally:
        if queue is not None:
            queue.close()


def test_reject_negative_capacity_change() -> None:
    queue = JobQueue({"cpu": 1}, lambda _: None)
    try:
        with pytest.raises(ValueError):
            queue.set_capacity("cpu", -1)
    finally:
        queue.close()
