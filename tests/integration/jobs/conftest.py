"""Shared integration fixtures for job-queue behavior tests."""

from __future__ import annotations

import sys
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

support_path = str(Path(__file__).parents[2] / "support")
if support_path not in sys.path:
    sys.path.insert(0, support_path)

from job_queue import ControlledWorker  # noqa: E402


@pytest.fixture
def workers() -> Iterator[Callable[..., ControlledWorker]]:
    created: list[ControlledWorker] = []

    def make(*, fail: bool = False) -> ControlledWorker:
        worker = ControlledWorker(fail=fail)
        created.append(worker)
        return worker

    yield make
    for worker in created:
        worker.release.set()
