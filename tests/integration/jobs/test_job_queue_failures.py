"""Deterministic integration tests for queue failure handling."""

from __future__ import annotations

import threading
from threading import Event, Thread

import pytest

import muteinous.infrastructure.jobs.queue as queue_module
from muteinous.infrastructure.jobs.queue import (
    JobContext,
    JobPlan,
    JobQueue,
    JobState,
)
from tests.support.job_queue import (
    capture_thread_exceptions,
    plan,
)

pytestmark = pytest.mark.portable


def test_worker_start_runtime_error_releases_capacity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FailingWorkerThread(Thread):
        def start(self) -> None:
            if self.name.startswith("job-"):
                raise RuntimeError("injected start failure")
            super().start()

    monkeypatch.setattr(queue_module, "Thread", FailingWorkerThread)
    queue = JobQueue({"cpu": 1}, lambda _: None)
    try:
        job = queue.submit(plan("cpu"), lambda submitted, context: None)
        assert queue.drain(5)
        snapshot = queue.snapshot(job)
        assert snapshot.state == JobState.FAILED
        assert snapshot.detail == "Worker start failed: injected start failure"
        assert not snapshot.physical_running
        assert queue._used["cpu"] == 0
    finally:
        queue.close()


def test_worker_baseexception_fails_job_and_releases_capacity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class InjectedWorkerAbort(BaseException):
        pass

    thread_errors: list[BaseException] = []

    monkeypatch.setattr(
        threading, "excepthook", capture_thread_exceptions(thread_errors)
    )
    queue = JobQueue({"cpu": 1}, lambda _: None)
    later_entered = Event()
    later_calls = 0

    def abort_worker(submitted: JobPlan, context: JobContext) -> object:
        raise InjectedWorkerAbort("injected worker abort")

    def later_worker(submitted: JobPlan, context: JobContext) -> object:
        nonlocal later_calls
        later_calls += 1
        later_entered.set()
        return submitted.input_json

    try:
        failed = queue.submit(plan("cpu", source="failed"), abort_worker)
        assert queue.drain(5)
        snapshot = queue.snapshot(failed)
        assert snapshot.state == JobState.FAILED
        assert "InjectedWorkerAbort" in (snapshot.detail or "")

        later = queue.submit(plan("cpu", source="later"), later_worker)
        assert later_entered.wait(5)
        assert queue.drain(5)
        assert queue.snapshot(later).state == JobState.COMPLETED
        assert later_calls == 1
        assert thread_errors == []
    finally:
        queue.close()


def test_validator_failure_is_not_execution_failure_or_retry() -> None:
    called = Event()

    def validate(submitted: JobPlan) -> str | None:
        raise RuntimeError("provider unavailable")

    def worker(submitted: JobPlan, context: JobContext) -> object:
        called.set()
        return None

    queue = JobQueue({"cpu": 1}, validate)
    try:
        job = queue.submit(plan("cpu"), worker)
        assert queue.drain(5)
        snapshot = queue.snapshot(job)
        assert snapshot.state == JobState.NEEDS_ATTENTION
        assert snapshot.detail == (
            "Plan validation failed: RuntimeError: provider unavailable"
        )
        assert not called.is_set()
    finally:
        queue.close()


def test_validator_baseexception_needs_attention_and_dispatcher_survives(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class InjectedValidatorAbort(BaseException):
        pass

    thread_errors: list[BaseException] = []
    first_worker_called = Event()
    later_worker_called = Event()

    def validate(submitted: JobPlan) -> str | None:
        if submitted.input_json == '{"source":"validator-abort"}':
            raise InjectedValidatorAbort("injected validator abort")
        return None

    def first_worker(submitted: JobPlan, context: JobContext) -> object:
        first_worker_called.set()
        return None

    def later_worker(submitted: JobPlan, context: JobContext) -> object:
        later_worker_called.set()
        return submitted.input_json

    monkeypatch.setattr(
        threading, "excepthook", capture_thread_exceptions(thread_errors)
    )
    queue = JobQueue({"cpu": 1}, validate)
    try:
        failed = queue.submit(plan("cpu", source="validator-abort"), first_worker)
        assert queue.drain(5)
        snapshot = queue.snapshot(failed)
        assert snapshot.state == JobState.NEEDS_ATTENTION
        assert "Plan validation failed" in (snapshot.detail or "")
        assert "InjectedValidatorAbort" in (snapshot.detail or "")
        assert not first_worker_called.is_set()

        later = queue.submit(plan("cpu", source="valid"), later_worker)
        assert queue.drain(5)
        assert queue.snapshot(later).state == JobState.COMPLETED
        assert later_worker_called.is_set()
        assert thread_errors == []
    finally:
        queue.close()
