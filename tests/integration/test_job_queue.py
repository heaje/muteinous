"""Controlled thread/resource boundaries; deadlines are test guards only."""

import gc
import threading
import time
from collections import Counter
from collections.abc import Callable, Iterator
from threading import Event, Thread, current_thread
from weakref import ReferenceType, ref

import pytest

import muteinous.infrastructure.jobs.queue as queue_module
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


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


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
    clock = FakeClock()

    def validate(submitted: JobPlan) -> str | None:
        if stale.is_set() and submitted.input_json == '{"source":"old"}':
            return "Source changed"
        return None

    queue = JobQueue(
        {"gpu": 1, "other": 1},
        validate,
        revalidate_interval=1.0,
        clock=clock,
    )
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
        clock.now += 1.1
        queue.set_capacity("other", 1)
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


def test_busy_plan_becomes_stale_on_timer_without_other_wakes(
    workers: Callable[..., ControlledWorker],
) -> None:
    stale = Event()
    stale_revalidated = Event()
    calls: Counter[str] = Counter()

    def validate(submitted: JobPlan) -> str | None:
        calls[submitted.input_json] += 1
        if submitted.input_json == '{"source":"waiting"}' and stale.is_set():
            stale_revalidated.set()
            return "Source changed"
        return None

    queue = JobQueue({"cpu": 1}, validate, revalidate_interval=0.05)
    owner, waiting = workers(), workers()
    try:
        queue.submit(plan("cpu", source="owner"), owner)
        assert owner.entered.wait(5)
        waiting_id = queue.submit(plan("cpu", source="waiting"), waiting)
        eventually(
            lambda: (
                queue.snapshot(waiting_id).detail == "Waiting for: cpu"
                and calls['{"source":"waiting"}'] == 1
            )
        )

        stale.set()
        # No queue operation after this flag change may wake the dispatcher.
        assert stale_revalidated.wait(5)
        eventually(lambda: queue.snapshot(waiting_id).state == JobState.NEEDS_ATTENTION)
        assert queue.snapshot(waiting_id).detail == "Source changed"
        assert calls['{"source":"waiting"}'] == 2
    finally:
        owner.release.set()
        waiting.release.set()
        queue.close()


def test_busy_plans_revalidate_on_interval_and_eligible_plans_before_dispatch(
    workers: Callable[..., ControlledWorker],
) -> None:
    clock = FakeClock()
    calls: Counter[str] = Counter()
    dispatch_validation_counts: dict[str, int] = {}
    queued_count = 6

    def validate(submitted: JobPlan) -> str | None:
        calls[submitted.input_json] += 1
        return None

    def quick_worker(submitted: JobPlan, context: JobContext) -> object:
        dispatch_validation_counts[submitted.input_json] = calls[submitted.input_json]
        return submitted.input_json

    queue = JobQueue(
        {"provider": 1, "other": 1},
        validate,
        revalidate_interval=1.0,
        clock=clock,
    )
    owner = workers()
    try:
        queue.submit(plan("provider", source="owner"), owner)
        assert owner.entered.wait(5)
        pending = [
            plan("provider", source=f"busy-{index}") for index in range(queued_count)
        ]
        jobs = [queue.submit(submitted, quick_worker) for submitted in pending]
        eventually(
            lambda: all(
                queue.snapshot(job_id).detail == "Waiting for: provider"
                and calls[submitted.input_json] == 1
                for job_id, submitted in zip(jobs, pending, strict=True)
            )
        )

        for capacity in (2, 1, 2, 1, 2):
            queue.set_capacity("other", capacity)

        canary = queue.submit(plan("other", source="canary"), quick_worker)
        eventually(lambda: queue.snapshot(canary).state == JobState.COMPLETED)
        assert all(calls[submitted.input_json] == 1 for submitted in pending)

        clock.now += 1.1
        queue.set_capacity("other", 1)
        eventually(
            lambda: all(calls[submitted.input_json] == 2 for submitted in pending)
        )
        owner.release.set()
        assert queue.drain(5)
        assert all(calls[submitted.input_json] == 3 for submitted in pending)
        assert all(
            dispatch_validation_counts[submitted.input_json] == 3
            for submitted in pending
        )
        assert all(
            queue.snapshot(job_id).state == JobState.COMPLETED for job_id in jobs
        )
    finally:
        owner.release.set()
        queue.close()


def test_busy_wait_does_not_expire_after_large_clock_advance(
    workers: Callable[..., ControlledWorker],
) -> None:
    clock = FakeClock()
    calls: Counter[str] = Counter()

    def validate(submitted: JobPlan) -> str | None:
        calls[submitted.input_json] += 1
        return None

    queue = JobQueue(
        {"provider": 1, "other": 1},
        validate,
        revalidate_interval=1.0,
        clock=clock,
    )
    owner, waiting = workers(), workers()
    try:
        queue.submit(plan("provider", source="owner"), owner)
        assert owner.entered.wait(5)
        waiting_id = queue.submit(plan("provider", source="waiting"), waiting)
        eventually(
            lambda: (
                queue.snapshot(waiting_id).detail == "Waiting for: provider"
                and calls['{"source":"waiting"}'] == 1
            )
        )

        clock.now += 365 * 24 * 60 * 60
        queue.set_capacity("other", 1)
        eventually(lambda: calls['{"source":"waiting"}'] == 2)
        waiting_snapshot = queue.snapshot(waiting_id)
        assert waiting_snapshot.state == JobState.QUEUED
        assert waiting_snapshot.detail == "Waiting for: provider"

        owner.release.set()
        assert waiting.entered.wait(5)
        waiting.release.set()
        assert queue.drain(5)
        assert waiting.calls == 1
        assert queue.snapshot(waiting_id).state == JobState.COMPLETED
    finally:
        owner.release.set()
        waiting.release.set()
        queue.close()


def test_partially_blocked_multiresource_plan_ignores_unrelated_wakes(
    workers: Callable[..., ControlledWorker],
) -> None:
    clock = FakeClock()
    calls: Counter[str] = Counter()

    def validate(submitted: JobPlan) -> str | None:
        calls[submitted.input_json] += 1
        return None

    def quick_worker(submitted: JobPlan, context: JobContext) -> object:
        return submitted.input_json

    queue = JobQueue(
        {"x": 1, "y": 1, "z": 1},
        validate,
        revalidate_interval=3600,
        clock=clock,
    )
    owner, partial = workers(), workers()
    try:
        queue.submit(plan("x", source="owner"), owner)
        assert owner.entered.wait(5)
        partial_plan = plan("x", "y", source="partial")
        partial_id = queue.submit(partial_plan, partial)
        eventually(
            lambda: (
                queue.snapshot(partial_id).detail == "Waiting for: x"
                and calls[partial_plan.input_json] == 1
            )
        )

        for capacity in (2, 3, 4):
            queue.set_capacity("z", capacity)
        canary = queue.submit(plan("z", source="canary"), quick_worker)
        eventually(lambda: queue.snapshot(canary).state == JobState.COMPLETED)

        assert calls[partial_plan.input_json] == 1
        assert clock.now == 0
        assert queue.snapshot(partial_id).state == JobState.QUEUED
    finally:
        owner.release.set()
        partial.release.set()
        queue.close()


def test_capacity_increase_wakes_waiting_job_without_clock_advance(
    workers: Callable[..., ControlledWorker],
) -> None:
    clock = FakeClock()
    queue = JobQueue(
        {"cpu": 1},
        lambda _: None,
        revalidate_interval=3600,
        clock=clock,
    )
    owner, waiting = workers(), workers()
    try:
        queue.submit(plan("cpu", source="owner"), owner)
        assert owner.entered.wait(5)
        waiting_id = queue.submit(plan("cpu", source="waiting"), waiting)
        eventually(lambda: queue.snapshot(waiting_id).detail == "Waiting for: cpu")

        queue.set_capacity("cpu", 2)
        assert waiting.entered.wait(5)
        assert clock.now == 0
        assert queue.snapshot(waiting_id).state == JobState.RUNNING

        owner.release.set()
        waiting.release.set()
        assert queue.drain(5)
        assert waiting.calls == 1
    finally:
        owner.release.set()
        waiting.release.set()
        queue.close()


def test_zero_capacity_makes_queued_job_needs_attention_without_revival(
    workers: Callable[..., ControlledWorker],
) -> None:
    queue = JobQueue({"cpu": 1}, lambda _: None)
    owner, waiting = workers(), workers()
    try:
        queue.submit(plan("cpu", source="owner"), owner)
        assert owner.entered.wait(5)
        waiting_id = queue.submit(plan("cpu", source="waiting"), waiting)
        eventually(lambda: queue.snapshot(waiting_id).detail == "Waiting for: cpu")

        queue.set_capacity("cpu", 0)
        eventually(lambda: queue.snapshot(waiting_id).state == JobState.NEEDS_ATTENTION)
        unavailable = queue.snapshot(waiting_id)
        assert unavailable.detail == "Unavailable: cpu"
        assert waiting.calls == 0

        queue.set_capacity("cpu", 1)
        assert queue.snapshot(waiting_id).state == JobState.NEEDS_ATTENTION
        assert waiting.calls == 0
        owner.release.set()
        assert queue.drain(5)
        assert queue.snapshot(waiting_id).state == JobState.NEEDS_ATTENTION
        assert waiting.calls == 0
    finally:
        owner.release.set()
        waiting.release.set()
        queue.close()


def test_worker_start_prelaunch_baseexception_releases_slot_and_scheduler_continues(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class InjectedPreLaunchFailure(BaseException):
        pass

    original_thread = getattr(queue_module, "Thread")
    thread_errors: list[BaseException] = []

    def capture_thread_exception(args: object) -> None:
        error = getattr(args, "exc_value", None)
        if isinstance(error, BaseException):
            thread_errors.append(error)

    class FailingBeforeLaunchThread(Thread):
        def start(self) -> None:
            if self.name.startswith("job-"):
                raise InjectedPreLaunchFailure("injected pre-launch failure")
            super().start()

    monkeypatch.setattr(threading, "excepthook", capture_thread_exception)
    monkeypatch.setattr(queue_module, "Thread", FailingBeforeLaunchThread)
    before = set(threading.enumerate())
    queue = JobQueue({"cpu": 1}, lambda _: None)
    first_calls = 0
    later_calls = 0
    later_entered = Event()

    def first_worker(submitted: JobPlan, context: JobContext) -> object:
        nonlocal first_calls
        first_calls += 1
        return None

    def later_worker(submitted: JobPlan, context: JobContext) -> object:
        nonlocal later_calls
        later_calls += 1
        later_entered.set()
        return submitted.input_json

    try:
        failed = queue.submit(plan("cpu", source="first"), first_worker)
        eventually(lambda: queue.snapshot(failed).state == JobState.FAILED)
        failed_snapshot = queue.snapshot(failed)
        assert "InjectedPreLaunchFailure" in (failed_snapshot.detail or "")
        assert not failed_snapshot.physical_running
        assert first_calls == 0
        assert queue.drain(5)

        monkeypatch.setattr(queue_module, "Thread", original_thread)
        later = queue.submit(plan("cpu", source="later"), later_worker)
        assert later_entered.wait(5)
        assert queue.drain(5)
        queue.close()
        assert later_calls == 1
        assert queue._used["cpu"] == 0
        assert thread_errors == []
        assert not any(
            thread.name == "muteinous-jobs" or thread.name.startswith("job-")
            for thread in set(threading.enumerate()) - before
        )
        assert queue.snapshot(later).state == JobState.COMPLETED
    finally:
        queue.close()


def test_prelaunch_failure_publishes_terminal_revision_without_clock_advance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class InjectedPreLaunchFailure(BaseException):
        pass

    start_entered, fail_start = Event(), Event()
    worker_called = Event()
    clock = FakeClock()

    class FailingBeforeLaunchThread(Thread):
        def start(self) -> None:
            if self.name.startswith("job-"):
                start_entered.set()
                assert fail_start.wait(5)
                raise InjectedPreLaunchFailure("injected publication failure")
            super().start()

    monkeypatch.setattr(queue_module, "Thread", FailingBeforeLaunchThread)
    queue = JobQueue(
        {"cpu": 1},
        lambda _: None,
        progress_interval=3600,
        clock=clock,
    )

    def worker(submitted: JobPlan, context: JobContext) -> object:
        worker_called.set()
        return submitted.input_json

    try:
        job = queue.submit(plan("cpu"), worker)
        assert start_entered.wait(5)
        # start() is called under the queue lock; inspect the already-published
        # running snapshot directly while the injected start failure is held.
        before = queue._records[job].snapshot
        assert before.state == JobState.RUNNING
        fail_start.set()
        assert queue.drain(5)

        failed = queue.snapshot(job)
        published = queue.poll(job, before.revision)
        assert failed.state == JobState.FAILED
        assert failed.revision > before.revision
        assert published is not None
        assert published.state == JobState.FAILED
        assert published.revision > before.revision
        assert clock.now == 0
        assert not worker_called.is_set()
    finally:
        fail_start.set()
        queue.close()


def test_worker_start_baseexception_releases_slot_and_scheduler_continues(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class InjectedPostLaunchFailure(BaseException):
        pass

    failure_raised = Event()
    launched_threads: list[Thread] = []
    thread_errors: list[BaseException] = []

    def capture_thread_exception(args: object) -> None:
        error = getattr(args, "exc_value", None)
        if isinstance(error, BaseException):
            thread_errors.append(error)

    class FailingWorkerThread(Thread):
        def start(self) -> None:
            super().start()
            if self.name.startswith("job-"):
                launched_threads.append(self)
                if not failure_raised.is_set():
                    failure_raised.set()
                    raise InjectedPostLaunchFailure("injected post-launch failure")

    monkeypatch.setattr(threading, "excepthook", capture_thread_exception)
    monkeypatch.setattr(queue_module, "Thread", FailingWorkerThread)
    before = set(threading.enumerate())
    queue = JobQueue({"cpu": 1}, lambda _: None)
    first_calls = 0
    later_calls = 0
    first_entered, first_release = Event(), Event()
    later_entered = Event()

    def first_worker(submitted: JobPlan, context: JobContext) -> object:
        nonlocal first_calls
        first_calls += 1
        first_entered.set()
        assert first_release.wait(10)
        return None

    def later_worker(submitted: JobPlan, context: JobContext) -> object:
        nonlocal later_calls
        later_calls += 1
        later_entered.set()
        return submitted.input_json

    try:
        first = queue.submit(plan("cpu", source="first"), first_worker)
        assert first_entered.wait(5)
        first_snapshot = queue.snapshot(first)
        assert first_snapshot.state == JobState.RUNNING
        assert first_snapshot.physical_running
        assert failure_raised.is_set()

        later = queue.submit(plan("cpu", source="later"), later_worker)
        eventually(lambda: queue.snapshot(later).detail == "Waiting for: cpu")
        assert not later_entered.is_set()
        assert queue._used["cpu"] == 1

        first_release.set()
        assert later_entered.wait(5)
        assert queue.drain(5)
        queue.close()
        for thread in launched_threads:
            thread.join(5)
            assert not thread.is_alive()
        assert first_calls == later_calls == 1
        assert queue._used["cpu"] == 0
        assert thread_errors == []
        assert not any(
            thread.name == "muteinous-jobs" or thread.name.startswith("job-")
            for thread in set(threading.enumerate()) - before
        )
        assert queue.snapshot(first).state == JobState.COMPLETED
        assert queue.snapshot(later).state == JobState.COMPLETED
    finally:
        first_release.set()
        queue.close()
        for thread in launched_threads:
            thread.join(5)


def test_worker_baseexception_fails_job_and_releases_capacity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class InjectedWorkerAbort(BaseException):
        pass

    thread_errors: list[BaseException] = []

    def capture_thread_exception(args: object) -> None:
        error = getattr(args, "exc_value", None)
        if isinstance(error, BaseException):
            thread_errors.append(error)

    monkeypatch.setattr(threading, "excepthook", capture_thread_exception)
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


def test_scheduler_pass_baseexception_marks_job_and_dispatcher_survives() -> None:
    class InjectedSchedulerClockFailure(BaseException):
        pass

    armed = Event()
    raised = Event()

    def clock() -> float:
        if armed.is_set() and current_thread().name == "muteinous-jobs":
            armed.clear()
            raised.set()
            raise InjectedSchedulerClockFailure("injected scheduler-pass failure")
        return time.monotonic()

    queue = JobQueue({"cpu": 1}, lambda _: None, clock=clock)
    first_calls = 0
    later_calls = 0

    def first_worker(submitted: JobPlan, context: JobContext) -> object:
        nonlocal first_calls
        first_calls += 1
        return None

    def later_worker(submitted: JobPlan, context: JobContext) -> object:
        nonlocal later_calls
        later_calls += 1
        return submitted.input_json

    try:
        armed.set()
        failed = queue.submit(plan("cpu", source="first"), first_worker)
        assert raised.wait(5)
        eventually(lambda: queue.snapshot(failed).state == JobState.FAILED)
        failed_snapshot = queue.snapshot(failed)
        assert "InjectedSchedulerClockFailure" in (failed_snapshot.detail or "")
        assert not failed_snapshot.physical_running
        assert first_calls == 0
        assert queue.drain(5)

        later = queue.submit(plan("cpu", source="later"), later_worker)
        assert queue.drain(5)
        assert later_calls == 1
        assert queue.snapshot(later).state == JobState.COMPLETED
    finally:
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


def test_poll_returns_material_queue_details_without_waiting_for_progress_interval(
    workers: Callable[..., ControlledWorker],
) -> None:
    clock = FakeClock()
    stale = Event()
    initial_validation_entered, release_initial_validation = Event(), Event()
    stale_revalidated = Event()
    calls: Counter[str] = Counter()

    def validate(submitted: JobPlan) -> str | None:
        calls[submitted.input_json] += 1
        if submitted.input_json == '{"source":"waiting"}':
            if calls[submitted.input_json] == 1:
                initial_validation_entered.set()
                assert release_initial_validation.wait(10)
            if stale.is_set():
                stale_revalidated.set()
                return "Source changed"
        return None

    queue = JobQueue(
        {"cpu": 1},
        validate,
        progress_interval=3600,
        revalidate_interval=3600,
        clock=clock,
    )
    owner, waiting = workers(), workers()
    try:
        queue.submit(plan("cpu", source="owner"), owner)
        assert owner.entered.wait(5)
        waiting_id = queue.submit(plan("cpu", source="waiting"), waiting)
        assert initial_validation_entered.wait(5)
        queued = queue.snapshot(waiting_id)
        assert queued.state == JobState.QUEUED
        assert queue.poll(waiting_id, queued.revision) is None

        release_initial_validation.set()
        eventually(lambda: queue.snapshot(waiting_id).detail == "Waiting for: cpu")
        waiting_detail = queue.snapshot(waiting_id)
        waiting_update = queue.poll(waiting_id, queued.revision)
        assert waiting_update is not None
        assert waiting_update.detail == "Waiting for: cpu"

        stale.set()
        owner.release.set()
        assert stale_revalidated.wait(5)
        assert queue.drain(5)
        attention = queue.snapshot(waiting_id)
        attention_update = queue.poll(waiting_id, waiting_detail.revision)
        assert attention.state == JobState.NEEDS_ATTENTION
        assert attention_update is not None
        assert attention_update.state == JobState.NEEDS_ATTENTION
        assert attention_update.detail == "Source changed"
        assert clock.now == 0
        assert waiting.calls == 0
    finally:
        release_initial_validation.set()
        owner.release.set()
        waiting.release.set()
        queue.close()


def test_progress_retains_only_the_latest_weakrefable_activity() -> None:
    class WeakActivity(str):
        pass

    contexts: list[JobContext] = []
    entered, release = Event(), Event()
    activity_refs: list[ReferenceType[WeakActivity]] = []
    latest_ref: ReferenceType[WeakActivity] | None = None
    latest_text = "activity-127"

    def worker(submitted: JobPlan, context: JobContext) -> object:
        contexts.append(context)
        entered.set()
        assert release.wait(10)
        return submitted.input_json

    queue = JobQueue({"cpu": 1}, lambda _: None)
    try:
        job = queue.submit(plan("cpu"), worker)
        assert entered.wait(5)
        context = contexts[0]
        for index in range(128):
            activity = WeakActivity(f"activity-{index}")
            if index < 127:
                activity_refs.append(ref(activity))
            else:
                latest_ref = ref(activity)
            context.report(Progress("scan", activity=activity), meaningful=True)
        del activity

        gc.collect()
        assert all(activity_ref() is None for activity_ref in activity_refs)
        snapshot = queue.snapshot(job)
        assert latest_ref is not None
        assert latest_ref() is snapshot.progress.activity
        assert snapshot.progress.activity == latest_text
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


@pytest.mark.parametrize(
    ("reason", "truncated"),
    [
        pytest.param("validation-prefix:" + "x" * 5000, True, id="ascii"),
        pytest.param("validation-prefix:" + "😀" * 5000, True, id="astral"),
        pytest.param("validation-prefix:short", False, id="short"),
    ],
)
def test_long_validator_reasons_are_safely_truncated(
    reason: str, truncated: bool
) -> None:
    def validate(submitted: JobPlan) -> str | None:
        return reason

    queue = JobQueue({"cpu": 1}, validate)
    try:
        job = queue.submit(plan("cpu"), lambda submitted, context: None)
        assert queue.drain(5)
        snapshot = queue.snapshot(job)
        assert snapshot.state == JobState.NEEDS_ATTENTION
        assert snapshot.detail is not None
        if truncated:
            assert len(snapshot.detail) <= queue_module._MAX_DETAIL
            assert snapshot.detail.startswith("validation-prefix:")
            assert snapshot.detail.endswith(queue_module._DETAIL_TRUNCATION_SUFFIX)
            snapshot.detail.encode("utf-8")
        else:
            assert snapshot.detail == reason
    finally:
        queue.close()


def test_worker_and_validator_failure_details_are_bounded() -> None:
    large_message = "x" * 1_000_000
    validator_worker_called = Event()
    assert queue_module._error_detail(RuntimeError("short")) == "RuntimeError: short"

    def validate(submitted: JobPlan) -> str | None:
        if submitted.input_json == '{"source":"validator-failure"}':
            raise RuntimeError(f"validator-prefix:{large_message}")
        return None

    def failed_worker(submitted: JobPlan, context: JobContext) -> object:
        raise RuntimeError(f"worker-prefix:{large_message}")

    def validator_worker(submitted: JobPlan, context: JobContext) -> object:
        validator_worker_called.set()
        return None

    queue = JobQueue({"worker": 1, "validator": 1}, validate)
    try:
        worker_failure = queue.submit(
            plan("worker", source="worker-failure"), failed_worker
        )
        validator_failure = queue.submit(
            plan("validator", source="validator-failure"), validator_worker
        )
        assert queue.drain(5)

        worker_detail = queue.snapshot(worker_failure).detail
        validator_detail = queue.snapshot(validator_failure).detail
        assert queue.snapshot(worker_failure).state == JobState.FAILED
        assert queue.snapshot(validator_failure).state == JobState.NEEDS_ATTENTION
        assert worker_detail is not None and validator_detail is not None
        assert len(worker_detail) <= queue_module._MAX_DETAIL
        assert len(validator_detail) <= queue_module._MAX_DETAIL
        assert worker_detail.startswith("RuntimeError: worker-prefix:")
        assert validator_detail.startswith(
            "Plan validation failed: RuntimeError: validator-prefix:"
        )
        assert worker_detail.endswith(queue_module._DETAIL_TRUNCATION_SUFFIX)
        assert validator_detail.endswith(queue_module._DETAIL_TRUNCATION_SUFFIX)
        assert not validator_worker_called.is_set()
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


def test_capacity_increase_during_younger_validation_preserves_fifo(
    monkeypatch: pytest.MonkeyPatch,
    workers: Callable[..., ControlledWorker],
) -> None:
    younger_validation_entered, release_validation = Event(), Event()
    start_lock = threading.Lock()
    launch_order: list[str] = []

    class RecordingThread(Thread):
        def start(self) -> None:
            if self.name.startswith("job-"):
                with start_lock:
                    launch_order.append(self.name)
            super().start()

    monkeypatch.setattr(queue_module, "Thread", RecordingThread)

    def validate(submitted: JobPlan) -> str | None:
        if submitted.input_json == '{"source":"younger"}':
            if not younger_validation_entered.is_set():
                younger_validation_entered.set()
                assert release_validation.wait(10)
        return None

    queue = JobQueue({"x": 1, "y": 1}, validate)
    owner, older, younger = (workers() for _ in range(3))
    try:
        queue.submit(plan("x", source="owner"), owner)
        assert owner.entered.wait(5)
        older_id = queue.submit(plan("x", source="older"), older)
        eventually(lambda: queue.snapshot(older_id).detail == "Waiting for: x")
        younger_id = queue.submit(plan("y", source="younger"), younger)
        assert younger_validation_entered.wait(5)

        queue.set_capacity("x", 2)
        release_validation.set()
        assert older.entered.wait(5)
        assert younger.entered.wait(5)
        with start_lock:
            launches = list(launch_order)
        assert launches.index(f"job-{older_id}") < launches.index(f"job-{younger_id}")

        owner.release.set()
        older.release.set()
        younger.release.set()
        assert queue.drain(5)
    finally:
        release_validation.set()
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
