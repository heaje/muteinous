"""Serializable plan and defensible progress value tests."""

import json
from dataclasses import asdict

import pytest

from muteinous.infrastructure.jobs.queue import JobPlan, WorkCount


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


@pytest.mark.parametrize("payload", ["not json", "[]", '{"value":NaN}'])
def test_reject_non_object_or_invalid_json(payload: str) -> None:
    with pytest.raises(ValueError):
        JobPlan("fake", "cpu", ("cpu",), payload)


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
