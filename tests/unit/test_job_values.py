"""Serializable plan and defensible progress value tests."""

import json
from dataclasses import asdict
from typing import cast

import pytest

from muteinous.infrastructure.jobs.queue import JobPlan, JobQueue, WorkCount

pytestmark = pytest.mark.portable


def test_plan_is_serializable_and_preserves_resolved_choices() -> None:
    plan = JobPlan("fake", "gpu", ("gpu", "provider"), '{"source":"v1"}')
    data = json.loads(json.dumps(asdict(plan)))
    restored = JobPlan(
        data["provider"], data["backend"], tuple(data["resources"]), data["input_json"]
    )
    assert restored == plan


@pytest.mark.parametrize("resources", [(), ("cpu", "cpu"), ("",)])
def test_reject_invalid_resource_declarations(resources: tuple[str, ...]) -> None:
    with pytest.raises(ValueError):
        JobPlan("fake", "cpu", resources, "{}")


@pytest.mark.parametrize(
    ("provider", "backend", "resources", "input_json"),
    [
        (1, "cpu", ("cpu",), "{}"),
        ("fake", object(), ("cpu",), "{}"),
        ("fake", "cpu", (7,), "{}"),
        ("fake", "cpu", ("cpu",), b"{}"),
    ],
)
def test_reject_wrong_job_plan_field_types(
    provider: object,
    backend: object,
    resources: object,
    input_json: object,
) -> None:
    with pytest.raises(ValueError, match="declared string types"):
        JobPlan(provider, backend, resources, input_json)  # type: ignore[arg-type]


def test_reject_list_job_plan_resources() -> None:
    with pytest.raises(ValueError, match="declared string types"):
        JobPlan("fake", "cpu", ["cpu"], "{}")  # type: ignore[arg-type]


@pytest.mark.parametrize(("provider", "backend"), [("", "cpu"), ("fake", "")])
def test_reject_empty_provider_or_backend(provider: str, backend: str) -> None:
    with pytest.raises(ValueError, match="Provider and backend"):
        JobPlan(provider, backend, ("cpu",), "{}")


@pytest.mark.parametrize("payload", ["not json", "[]", '{"value":NaN}'])
def test_reject_non_object_or_invalid_json(payload: str) -> None:
    with pytest.raises(ValueError):
        JobPlan("fake", "cpu", ("cpu",), payload)


@pytest.mark.parametrize("payload", ['{"n":1e999}', '{"n":-1e999}'])
def test_reject_non_finite_json_floats(payload: str) -> None:
    with pytest.raises(ValueError, match="non-finite"):
        JobPlan("fake", "cpu", ("cpu",), payload)


@pytest.mark.parametrize("depth", [20_000, 40_000])
def test_reject_pathologically_nested_json_as_value_error(depth: int) -> None:
    payload = "[" * depth + "0" + "]" * depth
    with pytest.raises(ValueError, match="too deeply nested"):
        JobPlan("fake", "cpu", ("cpu",), payload)


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
    "payload",
    [
        '{"source":"a","source":"b"}',
        '{"nested":{"source":"a","source":"b"}}',
    ],
)
def test_reject_duplicate_json_object_keys_at_every_level(payload: str) -> None:
    with pytest.raises(ValueError, match="Duplicate JSON object key"):
        JobPlan("fake", "cpu", ("cpu",), payload)


@pytest.mark.parametrize(
    "interval", [0.0, -1.0, float("inf"), float("-inf"), float("nan")]
)
def test_revalidation_interval_must_be_finite_and_positive(interval: float) -> None:
    with pytest.raises(ValueError, match="Revalidation interval"):
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


@pytest.mark.parametrize(
    ("count", "percentage"),
    [
        (WorkCount(3), None),
        (WorkCount(3, 4), None),
        (WorkCount(3, 10, True), 30.0),
        (WorkCount(1, 0, True), None),
        (WorkCount(5, 4, True), None),
        (WorkCount(-1, 4, True), None),
        (WorkCount(1.5, 2, True), None),  # type: ignore[arg-type]
        (WorkCount(True, 2, True), None),
        (WorkCount(1, True, True), None),
        (WorkCount(1, 2, 1), None),  # type: ignore[arg-type]
        (WorkCount(1, 2.5, True), None),  # type: ignore[arg-type]
        (WorkCount(1, 2.0, True), None),  # type: ignore[arg-type]
    ],
)
def test_percentage_requires_reliable_denominator(
    count: WorkCount, percentage: float | None
) -> None:
    assert count.percentage == percentage


def test_percentage_handles_zero_complete_and_fractional_totals() -> None:
    assert WorkCount(0, 0, True).percentage is None
    assert WorkCount(3, 3, True).percentage == 100.0
    assert WorkCount(1, 3, True).percentage == pytest.approx(100 / 3)
