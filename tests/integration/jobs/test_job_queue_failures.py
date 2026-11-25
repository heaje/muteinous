"""Deterministic integration tests for queue failure handling."""

from __future__ import annotations

from threading import Event, Thread

import pytest

import muteinous.infrastructure.jobs.queue as queue_module
from muteinous.infrastructure.jobs.queue import JobContext, JobPlan, JobQueue, JobState
from tests.support.job_queue import plan

pytestmark = pytest.mark.portable


def test_worker_start_runtime_error_releases_capacity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fail_next_start = Event()
    called = Event()

    class FailingWorkerThread(Thread):
        def start(self) -> None:
            if fail_next_start.is_set():
                fail_next_start.clear()
                raise RuntimeError("injected start failure")
            super().start()

    def worker(submitted: JobPlan, context: JobContext) -> object:
        called.set()
        return submitted.input_json

    monkeypatch.setattr(queue_module, "Thread", FailingWorkerThread)
    queue = JobQueue({"cpu": 1}, lambda _: None)
    try:
        fail_next_start.set()
        job = queue.submit(plan("cpu"), worker)
        assert queue.drain(5)
        snapshot = queue.snapshot(job)
        assert snapshot.state == JobState.FAILED
        assert "injected start failure" in (snapshot.detail or "")
        assert not snapshot.physical_running
        assert not called.is_set()

        later = queue.submit(plan("cpu"), worker)
        assert queue.drain(5)
        assert queue.snapshot(later).state == JobState.COMPLETED
        assert called.is_set()
    finally:
        queue.close()


def test_validator_failure_needs_attention_and_dispatcher_survives() -> None:
    called = Event()
    invalid = plan("cpu", source="unavailable")

    def validate(submitted: JobPlan) -> str | None:
        if submitted == invalid:
            raise RuntimeError("provider unavailable")
        return None

    def worker(submitted: JobPlan, context: JobContext) -> object:
        called.set()
        return submitted.input_json

    queue = JobQueue({"cpu": 1}, validate)
    try:
        job = queue.submit(invalid, worker)
        assert queue.drain(5)
        snapshot = queue.snapshot(job)
        assert snapshot.state == JobState.NEEDS_ATTENTION
        assert "provider unavailable" in (snapshot.detail or "")
        assert not called.is_set()

        later = queue.submit(plan("cpu"), worker)
        assert queue.drain(5)
        assert queue.snapshot(later).state == JobState.COMPLETED
        assert called.is_set()
    finally:
        queue.close()
