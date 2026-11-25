"""Unit tests for job queue construction and input validation."""

from __future__ import annotations

from typing import cast

import pytest

from muteinous.infrastructure.jobs.queue import JobPlan, JobQueue

pytestmark = pytest.mark.portable


@pytest.mark.parametrize("reason", [7, True])
def test_non_string_validator_reasons_are_coerced_to_text(reason: object) -> None:
    called = False

    def validate(submitted: JobPlan) -> str | None:
        return cast(str | None, reason)

    def worker(submitted: JobPlan, context: object) -> object:
        nonlocal called
        called = True
        return None

    queue = JobQueue({"cpu": 1}, validate)
    try:
        job = queue.submit(JobPlan("fake", "cpu", ("cpu",), "{}"), worker)
        assert queue.drain(5)
        snapshot = queue.snapshot(job)
        assert snapshot.state.value == "Needs attention"
        assert isinstance(snapshot.detail, str)
        assert snapshot.detail == (
            f"Plan validation returned {type(reason).__name__}, expected str or None"
        )
        assert not called
    finally:
        queue.close()


@pytest.mark.parametrize(
    "interval",
    [
        0.0,
        -1.0,
        1e-300,
        0.0005,
        float("inf"),
        float("-inf"),
        float("nan"),
    ],
)
def test_revalidation_interval_must_be_finite_and_at_least_minimum(
    interval: float,
) -> None:
    queue: JobQueue | None = None
    try:
        with pytest.raises(ValueError, match=r"Revalidation interval.*0\.001"):
            queue = JobQueue({}, lambda _: None, revalidate_interval=interval)
    finally:
        if queue is not None:
            queue.close()


def test_revalidation_interval_accepts_exact_minimum() -> None:
    queue = JobQueue({}, lambda _: None, revalidate_interval=0.001)
    queue.close()


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


@pytest.mark.parametrize("name", [7, ""])
def test_reject_invalid_resource_names_at_construction(name: object) -> None:
    queue: JobQueue | None = None
    try:
        with pytest.raises(ValueError, match="Resource names"):
            queue = JobQueue(cast(dict[str, int], {name: 1}), lambda _: None)
    finally:
        if queue is not None:
            queue.close()


@pytest.mark.parametrize("name", [7, ""])
def test_reject_invalid_resource_names_in_set_capacity(name: object) -> None:
    queue = JobQueue({}, lambda _: None)
    try:
        with pytest.raises(ValueError, match="Resource names"):
            queue.set_capacity(name, 1)  # type: ignore[arg-type]
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
