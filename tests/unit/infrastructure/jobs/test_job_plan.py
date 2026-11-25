"""Unit tests for resolved job plan values."""

from __future__ import annotations

import json
from dataclasses import asdict

import pytest

from muteinous.infrastructure.jobs.queue import JobPlan

pytestmark = pytest.mark.portable


def test_plan_is_serializable_and_preserves_resolved_choices() -> None:
    plan = JobPlan("fake", "gpu", ("gpu", "provider"), '{"source":"v1"}')
    data = json.loads(json.dumps(asdict(plan)))
    restored = JobPlan(
        data["provider"], data["backend"], tuple(data["resources"]), data["input_json"]
    )
    assert restored == plan


@pytest.mark.parametrize(
    "resources",
    [(), ("cpu", "cpu"), ("",)],
)
def test_reject_invalid_resource_declarations(resources: tuple[str, ...]) -> None:
    with pytest.raises(ValueError):
        JobPlan("fake", "cpu", resources, "{}")


@pytest.mark.parametrize(("provider", "backend"), [("", "cpu"), ("fake", "")])
def test_reject_empty_provider_or_backend(provider: str, backend: str) -> None:
    with pytest.raises(ValueError):
        JobPlan(provider, backend, ("cpu",), "{}")


@pytest.mark.parametrize("payload", ["not json", "[]"])
def test_reject_non_object_or_invalid_json(payload: str) -> None:
    with pytest.raises(ValueError):
        JobPlan("fake", "cpu", ("cpu",), payload)
