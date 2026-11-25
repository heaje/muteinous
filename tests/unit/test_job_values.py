"""Serializable plan and defensible progress value tests."""

import json
from dataclasses import asdict

import pytest

from muteinous.infrastructure.jobs.queue import JobPlan, JobQueue, WorkCount


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
