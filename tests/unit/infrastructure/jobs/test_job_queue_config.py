"""Unit tests for job queue construction and input validation."""

from __future__ import annotations

from typing import cast

import pytest

from muteinous.infrastructure.jobs.queue import JobQueue

pytestmark = pytest.mark.portable


@pytest.mark.parametrize(
    "interval",
    [0.0, -1.0, float("inf"), float("-inf"), float("nan")],
)
def test_revalidation_interval_must_be_finite_and_positive(interval: float) -> None:
    with pytest.raises(ValueError, match="Revalidation interval.*finite and positive"):
        JobQueue({}, lambda _: None, revalidate_interval=interval)


@pytest.mark.parametrize(
    "interval",
    [0.0, -1.0, float("inf"), float("-inf"), float("nan")],
)
def test_progress_interval_must_be_finite_and_positive(interval: float) -> None:
    queue: JobQueue | None = None
    try:
        with pytest.raises(ValueError, match="Progress interval"):
            queue = JobQueue({}, lambda _: None, progress_interval=interval)
    finally:
        if queue is not None:
            queue.close()


def test_reject_empty_resource_name_at_construction() -> None:
    queue: JobQueue | None = None
    try:
        with pytest.raises(ValueError, match="Resource capacities"):
            queue = JobQueue({"": 1}, lambda _: None)
    finally:
        if queue is not None:
            queue.close()


def test_reject_empty_resource_name_in_set_capacity() -> None:
    queue = JobQueue({}, lambda _: None)
    try:
        with pytest.raises(ValueError, match="Resource capacities"):
            queue.set_capacity("", 1)
    finally:
        queue.close()


@pytest.mark.parametrize("capacity", [-1, True, False])
def test_reject_invalid_capacity_at_construction(capacity: object) -> None:
    queue: JobQueue | None = None
    try:
        with pytest.raises(ValueError, match="Resource capacities"):
            queue = JobQueue(
                cast(dict[str, int], {"cpu": capacity}),
                lambda _: None,
            )
    finally:
        if queue is not None:
            queue.close()


@pytest.mark.parametrize("capacity", [-1, True, False])
def test_reject_invalid_capacity_in_set_capacity(capacity: object) -> None:
    queue = JobQueue({}, lambda _: None)
    try:
        with pytest.raises(ValueError, match="Resource capacities"):
            queue.set_capacity("cpu", capacity)  # type: ignore[arg-type]
    finally:
        queue.close()
