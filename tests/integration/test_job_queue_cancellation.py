"""Deterministic integration tests for the in-process job queue."""

from __future__ import annotations

import gc
import threading
from collections.abc import Callable
from threading import Event, Thread
from weakref import ref

import pytest
from job_queue import (
    ControlledWorker,
    eventually,
    plan,
)

from muteinous.infrastructure.jobs.queue import (
    JobContext,
    JobPlan,
    JobQueue,
    JobState,
    Progress,
)

pytestmark = pytest.mark.portable


def test_running_and_queued_cancellation_hold_slots_and_reject_late_results(
    workers: Callable[..., ControlledWorker],
) -> None:
    queue = JobQueue({"provider": 1}, lambda _: None)
    running, cancelled, replacement = (workers() for _ in range(3))
    try:
        a = queue.submit(plan("provider"), running)
        assert running.entered.wait(5)
        b = queue.submit(plan("provider"), cancelled)
        assert queue.cancel(b)
        assert queue.cancel(a)
        assert not queue.cancel(a)
        assert queue.snapshot(a).state == JobState.CANCELLED
        assert queue.snapshot(a).physical_running
        assert queue.snapshot(b).state == JobState.CANCELLED
        assert not queue.snapshot(b).physical_running
        c = queue.submit(plan("provider"), replacement)
        eventually(lambda: queue.snapshot(c).detail == "Waiting for: provider")
        assert not queue.drain(0)
        assert queue.snapshot(c).state == JobState.QUEUED
        running.release.set()
        assert replacement.entered.wait(5)
        assert running.observed_cancel.is_set()
        assert queue.snapshot(a).result is None
        assert not queue.snapshot(a).physical_running
        assert cancelled.calls == 0
        replacement.release.set()
        assert queue.drain(5)
        assert queue.snapshot(c).state == JobState.COMPLETED
        assert len({a, b, c}) == 3
    finally:
        for worker in (running, cancelled, replacement):
            worker.release.set()
        queue.close()


def test_cancel_rejects_completed_failed_and_already_cancelled_jobs() -> None:
    started, release = Event(), Event()

    def completed_worker(submitted: JobPlan, context: JobContext) -> object:
        return submitted.input_json

    def failed_worker(submitted: JobPlan, context: JobContext) -> object:
        raise RuntimeError("terminal-cancel test failure")

    def cancelled_worker(submitted: JobPlan, context: JobContext) -> object:
        started.set()
        assert release.wait(10)
        return submitted.input_json

    queue = JobQueue({"completed": 1, "failed": 1, "cancelled": 1}, lambda _: None)
    try:
        completed = queue.submit(plan("completed"), completed_worker)
        failed = queue.submit(plan("failed"), failed_worker)
        cancelled = queue.submit(plan("cancelled"), cancelled_worker)
        assert started.wait(5)
        assert queue.cancel(cancelled)
        cancelled_state = queue.snapshot(cancelled).state
        assert cancelled_state == JobState.CANCELLED
        assert not queue.cancel(cancelled)
        assert queue.snapshot(cancelled).state == cancelled_state

        release.set()
        assert queue.drain(5)
        for job_id, expected_state in (
            (completed, JobState.COMPLETED),
            (failed, JobState.FAILED),
            (cancelled, JobState.CANCELLED),
        ):
            before = queue.snapshot(job_id)
            assert before.state == expected_state
            assert not queue.cancel(job_id)
            assert queue.snapshot(job_id).state == before.state
    finally:
        release.set()
        queue.close()


def test_discard_terminal_jobs_releases_results_and_ignores_late_reports() -> None:
    class RetainedResult:
        pass

    result_refs = []
    contexts: list[JobContext] = []
    entered, release = Event(), Event()

    def running_worker(submitted: JobPlan, context: JobContext) -> object:
        entered.set()
        assert release.wait(10)
        return submitted.input_json

    def result_worker(submitted: JobPlan, context: JobContext) -> object:
        contexts.append(context)
        result = RetainedResult()
        result_refs.append(ref(result))
        return result

    def failed_worker(submitted: JobPlan, context: JobContext) -> object:
        raise RuntimeError("discard test failure")

    queue = JobQueue({"cpu": 1, "other": 3}, lambda _: None)
    try:
        running = queue.submit(plan("cpu", source="running"), running_worker)
        assert entered.wait(5)
        queued = queue.submit(plan("cpu", source="queued"), result_worker)
        assert not queue.discard(running)
        assert not queue.discard(queued)
        assert queue.cancel(queued)
        assert queue.snapshot(queued).state == JobState.CANCELLED
        assert not queue.snapshot(queued).physical_running
        assert queue.discard(queued)

        assert queue.cancel(running)
        assert queue.snapshot(running).state == JobState.CANCELLED
        assert queue.snapshot(running).physical_running
        assert not queue.discard(running)
        release.set()

        completed = queue.submit(plan("other", source="completed"), result_worker)
        failed = queue.submit(plan("other", source="failed"), failed_worker)
        attention = queue.submit(plan("missing", source="attention"), result_worker)
        assert queue.drain(5)
        queue.close()

        assert not queue.snapshot(running).physical_running
        assert queue.snapshot(completed).state == JobState.COMPLETED
        assert queue.snapshot(failed).state == JobState.FAILED
        assert queue.snapshot(attention).state == JobState.NEEDS_ATTENTION
        assert len(result_refs) == 1

        completed_snapshot = queue.snapshot(completed)
        assert completed_snapshot.result is result_refs[0]()
        del completed_snapshot
        for job_id in (running, completed, failed, attention):
            assert queue.discard(job_id)
            with pytest.raises(KeyError):
                queue.snapshot(job_id)
            with pytest.raises(KeyError):
                queue.poll(job_id)
            with pytest.raises(KeyError):
                queue.cancel(job_id)
        contexts[0].report(Progress("late"), meaningful=True)
        contexts[0].heartbeat()
        gc.collect()
        assert result_refs[0]() is None
    finally:
        release.set()
        queue.close()


def test_close_requests_cooperative_stop_and_joins_threads() -> None:
    entered = Event()

    def worker(submitted: JobPlan, context: JobContext) -> object:
        entered.set()
        assert context.wait_cancelled(10)
        return submitted.input_json

    before = set(threading.enumerate())
    queue = JobQueue({"cpu": 1}, lambda _: None)
    try:
        a = queue.submit(plan("cpu"), worker)
        assert entered.wait(5)
        b = queue.submit(plan("cpu"), worker)
    finally:
        queue.close()
    assert queue.snapshot(a).state == queue.snapshot(b).state == JobState.CANCELLED
    assert not queue.snapshot(a).physical_running
    assert queue.drain(0)
    assert not set(threading.enumerate()) - before
    with pytest.raises(RuntimeError, match="closed"):
        queue.submit(plan("cpu"), worker)


def test_close_waits_for_physical_worker_after_cancellation() -> None:
    entered, cancellation_observed, release = Event(), Event(), Event()
    close_started, close_returned = Event(), Event()

    def worker(submitted: JobPlan, context: JobContext) -> object:
        entered.set()
        assert context.wait_cancelled(10)
        cancellation_observed.set()
        assert release.wait(10)
        return submitted.input_json

    before = set(threading.enumerate())
    queue = JobQueue({"cpu": 1}, lambda _: None)

    def close_queue() -> None:
        close_started.set()
        queue.close()
        close_returned.set()

    closer = Thread(target=close_queue, name="job-queue-close-test")
    try:
        job = queue.submit(plan("cpu"), worker)
        assert entered.wait(5)
        closer.start()
        assert close_started.wait(5)
        assert cancellation_observed.wait(5)
        queue._dispatcher.join(5)
        assert not queue._dispatcher.is_alive()
        closer.join(0.25)
        assert closer.is_alive()
        assert not close_returned.is_set()
        snapshot = queue.snapshot(job)
        assert snapshot.state == JobState.CANCELLED
        assert snapshot.physical_running

        release.set()
        assert close_returned.wait(5)
        closer.join(5)
        assert not closer.is_alive()
        assert not queue.snapshot(job).physical_running
        assert queue.drain(0)
        assert not any(
            thread.name == "muteinous-jobs" or thread.name.startswith("job-")
            for thread in set(threading.enumerate()) - before
        )
    finally:
        release.set()
        queue.drain(5)
        if closer.ident is None:
            queue.close()
        else:
            closer.join(5)
            if closer.is_alive():
                queue.close()
                closer.join(5)
            assert not closer.is_alive()
        for thread in queue._threads:
            if thread.ident is not None:
                thread.join(5)
                assert not thread.is_alive()


def test_cancellation_during_dispatch_validation_never_invokes_worker() -> None:
    checking, release = Event(), Event()
    called = Event()

    def validate(submitted: JobPlan) -> str | None:
        checking.set()
        assert release.wait(10)
        return None

    def worker(submitted: JobPlan, context: JobContext) -> object:
        called.set()
        return None

    queue = JobQueue({"cpu": 1}, validate)
    try:
        job = queue.submit(plan("cpu"), worker)
        assert checking.wait(5)
        assert queue.cancel(job)
        release.set()
        assert queue.drain(5)
    finally:
        release.set()
        queue.close()
    assert not called.is_set()
    assert queue.snapshot(job).state == JobState.CANCELLED
