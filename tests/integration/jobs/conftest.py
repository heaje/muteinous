"""Shared integration fixtures for job-queue behavior tests."""

from __future__ import annotations

from collections.abc import Callable, Iterator

import pytest

from tests.support.job_queue import ControlledWorker


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
