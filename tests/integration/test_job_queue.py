"""Controlled thread/resource boundaries; deadlines are test guards only."""

import threading
import time
from collections.abc import Callable, Iterator
from threading import Event

import pytest

from muteinous.infrastructure.jobs.queue import (
    JobContext,
    JobPlan,
    JobQueue,
    JobState,
    Progress,
    WorkCount,
)

pytestmark = pytest.mark.portable


def plan(*resources: str, source: str = "v1") -> JobPlan:
    return JobPlan("fake", "fixed", resources, f'{{"source":"{source}"}}')


def eventually(predicate: Callable[[], bool]) -> None:
    deadline = time.monotonic() + 5
    while not predicate():
        assert time.monotonic() < deadline, "Condition did not become true"
        Event().wait(0.001)


class ControlledWorker:
    def __init__(self, *, fail: bool = False) -> None:
        self.entered = Event()
        self.release = Event()
        self.observed_cancel = Event()
        self.calls = 0
        self.fail = fail

    def __call__(self, submitted: JobPlan, context: JobContext) -> object:
        self.calls += 1
        self.entered.set()
        # No dependency on elapsed time for the intended ordering.
        assert self.release.wait(10), "Worker not released by test"
        if context.cancelled:
            self.observed_cancel.set()
        if self.fail:
            raise RuntimeError("controlled failure")
        return submitted.input_json


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


def test_fifo_eligibility_and_atomic_multi_resource_acquisition(
    workers: Callable[..., ControlledWorker],
) -> None:
    queue = JobQueue({"gpu": 1, "cpu": 1}, lambda _: None)
    owner, older, younger, independent = (workers() for _ in range(4))
    try:
        a = queue.submit(plan("gpu"), owner)
        assert owner.entered.wait(5)
        b = queue.submit(plan("gpu", "cpu"), older)
        c = queue.submit(plan("gpu"), younger)
        d = queue.submit(plan("cpu"), independent)
        assert independent.entered.wait(5)
        assert queue.snapshot(b).state == queue.snapshot(c).state == JobState.QUEUED
        assert "gpu" in (queue.snapshot(b).detail or "")
        assert queue.snapshot(a).physical_running and queue.snapshot(d).physical_running
        independent.release.set()
        eventually(lambda: queue.snapshot(d).state == JobState.COMPLETED)
        owner.release.set()
        assert older.entered.wait(5)
        assert queue.snapshot(c).state == JobState.QUEUED
        older.release.set()
        assert younger.entered.wait(5)
        younger.release.set()
        assert queue.drain(5)
        assert all(queue.snapshot(i).state == JobState.COMPLETED for i in (a, b, c, d))
        assert [w.calls for w in (owner, older, younger, independent)] == [1] * 4
    finally:
        for worker in (owner, older, younger, independent):
            worker.release.set()
        queue.close()


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


def test_failure_releases_capacity_without_retry_and_capacity_changes_apply(
    workers: Callable[..., ControlledWorker],
) -> None:
    queue = JobQueue({"cpu": 2}, lambda _: None)
    first, second, third = workers(fail=True), workers(), workers()
    try:
        a = queue.submit(plan("cpu"), first)
        b = queue.submit(plan("cpu"), second)
        assert first.entered.wait(5) and second.entered.wait(5)
        running_a = queue.snapshot(a)
        running_b = queue.snapshot(b)
        queue.set_capacity("cpu", 1)
        c = queue.submit(plan("cpu"), third)
        first.release.set()
        eventually(lambda: queue.snapshot(a).state == JobState.FAILED)
        assert queue.snapshot(a).detail == "RuntimeError: controlled failure"
        failed = queue.poll(a, running_a.revision)
        assert failed is not None and failed.state == JobState.FAILED
        assert queue.snapshot(c).state == JobState.QUEUED
        assert first.calls == 1
        second.release.set()
        assert third.entered.wait(5)
        third.release.set()
        assert queue.drain(5)
        assert queue.snapshot(b).state == queue.snapshot(c).state == JobState.COMPLETED
        completed = queue.poll(b, running_b.revision)
        assert completed is not None and completed.state == JobState.COMPLETED
        assert first.calls == 1
    finally:
        for worker in (first, second, third):
            worker.release.set()
        queue.close()


def test_stale_busy_plan_needs_attention_without_fallback(
    workers: Callable[..., ControlledWorker],
) -> None:
    stale = Event()

    def validate(submitted: JobPlan) -> str | None:
        if stale.is_set() and submitted.input_json == '{"source":"old"}':
            return "Source changed"
        return None

    queue = JobQueue({"gpu": 1}, validate)
    owner, obsolete, valid, unavailable = (workers() for _ in range(4))
    try:
        queue.submit(plan("gpu"), owner)
        assert owner.entered.wait(5)
        old = queue.submit(plan("gpu", source="old"), obsolete)
        fixed_plan = plan("gpu", source="fixed")
        good = queue.submit(fixed_plan, valid)
        missing = queue.submit(plan("missing"), unavailable)
        eventually(lambda: queue.snapshot(old).detail == "Waiting for: gpu")
        stale.set()
        eventually(lambda: queue.snapshot(old).state == JobState.NEEDS_ATTENTION)
        assert queue.snapshot(old).detail == "Source changed"
        assert queue.snapshot(missing).state == JobState.NEEDS_ATTENTION
        assert queue.snapshot(good).plan == fixed_plan
        assert queue.snapshot(good).state == JobState.QUEUED
        owner.release.set()
        assert valid.entered.wait(5)
        valid.release.set()
        assert queue.drain(5)
        assert obsolete.calls == unavailable.calls == 0
        assert queue.snapshot(good).result == fixed_plan.input_json
    finally:
        for worker in (owner, obsolete, valid, unavailable):
            worker.release.set()
        queue.close()


def test_progress_coalescing_and_terminal_snapshot() -> None:
    now = 0.0
    contexts: list[JobContext] = []
    entered, release = Event(), Event()

    def worker(submitted: JobPlan, context: JobContext) -> object:
        contexts.append(context)
        entered.set()
        assert release.wait(10)
        return submitted.input_json

    queue = JobQueue({"cpu": 1}, lambda _: None, progress_interval=1, clock=lambda: now)
    try:
        job = queue.submit(plan("cpu"), worker)
        assert entered.wait(5)
        context = contexts[0]
        context.report(Progress("discover", stage_count=WorkCount(1)), meaningful=True)
        initial = queue.poll(job)
        assert initial is not None and initial.last_progress_at == 0
        assert initial.progress.stage_count == WorkCount(1)
        now = 0.1
        for i in range(2, 1002):
            context.report(
                Progress("discover", stage_count=WorkCount(i, i + 10)), meaningful=True
            )
        latest = queue.snapshot(job)
        assert latest.progress.stage_count == WorkCount(1001, 1011)
        assert latest.last_progress_at == 0.1
        assert queue.poll(job, initial.revision) is None
        now = 0.2
        context.heartbeat()
        assert queue.snapshot(job).last_activity_at == 0.2
        assert queue.snapshot(job).last_progress_at == 0.1
        now = 1.0
        update = queue.poll(job, initial.revision)
        assert update is not None and update.progress == latest.progress
        context.report(Progress("process", stage_count=WorkCount(1, 4, True)))
        stage = queue.poll(job, update.revision)
        assert stage is not None and stage.progress.stage == "process"
        assert stage.progress.stage_count == WorkCount(1, 4, True)
        assert stage.progress.overall_count is None
        assert queue.cancel(job)
        terminal = queue.poll(job, stage.revision)
        assert terminal is not None and terminal.state == JobState.CANCELLED
        context.report(Progress("late"), meaningful=True)
        assert queue.snapshot(job) == terminal
        release.set()
        assert queue.drain(5)
        final = queue.poll(job, terminal.revision)
        assert final is not None and not final.physical_running
        assert final.result is None and final.progress == terminal.progress
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


def test_capacity_release_during_validation_restarts_fifo(
    workers: Callable[..., ControlledWorker],
) -> None:
    checking, release_check = Event(), Event()

    def validate(submitted: JobPlan) -> str | None:
        if submitted.input_json == '{"source":"younger"}':
            checking.set()
            assert release_check.wait(10)
        return None

    queue = JobQueue({"cpu": 1}, validate)
    owner, older, younger = (workers() for _ in range(3))
    try:
        a = queue.submit(plan("cpu"), owner)
        assert owner.entered.wait(5)
        b = queue.submit(plan("cpu"), older)
        eventually(lambda: queue.snapshot(b).detail == "Waiting for: cpu")
        c = queue.submit(plan("cpu", source="younger"), younger)
        assert checking.wait(5)
        owner.release.set()
        eventually(lambda: queue.snapshot(a).state == JobState.COMPLETED)
        release_check.set()
        assert older.entered.wait(5)
        assert queue.snapshot(c).state == JobState.QUEUED
        older.release.set()
        assert younger.entered.wait(5)
        younger.release.set()
        assert queue.drain(5)
    finally:
        release_check.set()
        for worker in (owner, older, younger):
            worker.release.set()
        queue.close()


def test_preference_changes_apply_only_to_new_submissions(
    workers: Callable[..., ControlledWorker],
) -> None:
    queue = JobQueue({"gpu": 1, "cpu": 1}, lambda _: None)
    owner, old_worker, new_worker = (workers() for _ in range(3))
    try:
        queue.submit(plan("gpu"), owner)
        assert owner.entered.wait(5)
        preference = "gpu"
        old_plan = JobPlan("fake", preference, (preference,), '{"config":"old"}')
        old = queue.submit(old_plan, old_worker)
        eventually(lambda: queue.snapshot(old).detail == "Waiting for: gpu")
        preference = "cpu"
        new_plan = JobPlan("fake", preference, (preference,), '{"config":"new"}')
        new = queue.submit(new_plan, new_worker)
        assert new_worker.entered.wait(5)
        assert queue.snapshot(old).plan == old_plan
        assert queue.snapshot(old).state == JobState.QUEUED
        assert queue.snapshot(new).plan == new_plan
        new_worker.release.set()
        owner.release.set()
        assert old_worker.entered.wait(5)
        old_worker.release.set()
        assert queue.drain(5)
        assert queue.snapshot(old).result == old_plan.input_json
        assert queue.snapshot(new).result == new_plan.input_json
    finally:
        for worker in (owner, old_worker, new_worker):
            worker.release.set()
        queue.close()
