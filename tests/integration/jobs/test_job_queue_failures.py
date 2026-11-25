"""Deterministic integration tests for the in-process job queue.

`_dispatch` starts a thread while holding the queue lock. A launched child may
begin running, but its first action in `_run` takes that same lock, so it cannot
inspect or mutate queue state until the dispatcher's except-branch records
`start_aborted`.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from threading import Event, Thread, current_thread

import pytest

import muteinous.infrastructure.jobs.queue as queue_module
from muteinous.infrastructure.jobs.queue import (
    JobContext,
    JobPlan,
    JobQueue,
    JobState,
)
from tests.support.job_queue import (
    FakeClock,
    capture_thread_exceptions,
    eventually,
    plan,
)

pytestmark = pytest.mark.portable


def test_dispatcher_native_start_error_closes_queue_and_exits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class InjectedDispatcherStartFailure(BaseException):
        pass

    launched: list[Thread] = []
    queue_instances: list[JobQueue] = []
    schedule_entered = Event()
    original_schedule = JobQueue._schedule

    def capture_schedule(queue: JobQueue) -> None:
        queue_instances.append(queue)
        schedule_entered.set()
        original_schedule(queue)

    class LaunchThenRaiseThread(Thread):
        def start(self) -> None:
            if self.name == "muteinous-jobs":
                launched.append(self)
                super().start()
                raise InjectedDispatcherStartFailure("launched then failed")
            super().start()

    monkeypatch.setattr(JobQueue, "_schedule", capture_schedule)
    monkeypatch.setattr(queue_module, "Thread", LaunchThenRaiseThread)
    try:
        with pytest.raises(InjectedDispatcherStartFailure):
            JobQueue({"cpu": 1}, lambda _: None)

        assert schedule_entered.wait(5)
        eventually(lambda: not launched[0].is_alive())
        assert queue_instances[0]._closed
    finally:
        if queue_instances:
            with queue_instances[0]._condition:
                queue_instances[0]._closed = True
                queue_instances[0]._wake()
        for thread in launched:
            if thread.ident is not None:
                thread.join(5)


def test_dispatcher_prelaunch_start_error_does_not_leak_thread(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class InjectedDispatcherStartFailure(BaseException):
        pass

    launched: list[Thread] = []

    class FailBeforeLaunchThread(Thread):
        def start(self) -> None:
            if self.name == "muteinous-jobs":
                launched.append(self)
                raise InjectedDispatcherStartFailure("failed before launch")
            super().start()

    monkeypatch.setattr(queue_module, "Thread", FailBeforeLaunchThread)
    with pytest.raises(InjectedDispatcherStartFailure):
        JobQueue({"cpu": 1}, lambda _: None)

    assert len(launched) == 1
    assert not launched[0].is_alive()
    assert launched[0].ident is None
    assert launched[0] not in threading.enumerate()


def test_worker_start_prelaunch_baseexception_releases_slot_and_scheduler_continues(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class InjectedPreLaunchFailure(BaseException):
        pass

    original_thread = getattr(queue_module, "Thread")
    thread_errors: list[BaseException] = []

    class FailingBeforeLaunchThread(Thread):
        def start(self) -> None:
            if self.name.startswith("job-"):
                raise InjectedPreLaunchFailure("injected pre-launch failure")
            super().start()

    monkeypatch.setattr(
        threading, "excepthook", capture_thread_exceptions(thread_errors)
    )
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


def _launch_then_raise_thread_class(
    run_entered: Event, start_failure_raised: Event, launched: list[Thread]
) -> type[Thread]:
    class InjectedStartFailure(BaseException):
        pass

    class LaunchThenRaiseThread(Thread):
        def start(self) -> None:
            super().start()
            if self.name.startswith("job-") and not launched:
                launched.append(self)
                assert run_entered.wait(5)
                start_failure_raised.set()
                raise InjectedStartFailure("native launch followed by start error")

    return LaunchThenRaiseThread


def test_native_launch_start_error_aborts_worker_and_releases_slot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_entered, release_run, run_finished, start_failure_raised = (
        Event(),
        Event(),
        Event(),
        Event(),
    )
    launched: list[Thread] = []
    thread_errors: list[BaseException] = []
    original_run = JobQueue._run

    def observe_run(
        queue: JobQueue, job_id: str, worker: Callable[[JobPlan, JobContext], object]
    ) -> None:
        run_entered.set()
        try:
            assert release_run.wait(10)
            original_run(queue, job_id, worker)
        finally:
            run_finished.set()

    monkeypatch.setattr(JobQueue, "_run", observe_run)
    monkeypatch.setattr(
        queue_module,
        "Thread",
        _launch_then_raise_thread_class(run_entered, start_failure_raised, launched),
    )
    monkeypatch.setattr(
        threading, "excepthook", capture_thread_exceptions(thread_errors)
    )
    queue = JobQueue({"cpu": 1}, lambda _: None)
    first_entered, release_first = Event(), Event()
    replacement_entered, release_replacement = Event(), Event()
    invocation_lock = threading.Lock()
    active_invocations = 0
    maximum_active_invocations = 0
    first_calls = 0

    def enter_invocation() -> None:
        nonlocal active_invocations, maximum_active_invocations
        with invocation_lock:
            active_invocations += 1
            maximum_active_invocations = max(
                maximum_active_invocations, active_invocations
            )

    def leave_invocation() -> None:
        nonlocal active_invocations
        with invocation_lock:
            active_invocations -= 1

    def first_worker(submitted: JobPlan, context: JobContext) -> object:
        nonlocal active_invocations, first_calls, maximum_active_invocations
        with invocation_lock:
            first_calls += 1
            active_invocations += 1
            maximum_active_invocations = max(
                maximum_active_invocations, active_invocations
            )
        first_entered.set()
        try:
            assert release_first.wait(10)
            return submitted.input_json
        finally:
            leave_invocation()

    def replacement_worker(submitted: JobPlan, context: JobContext) -> object:
        enter_invocation()
        replacement_entered.set()
        try:
            assert release_replacement.wait(10)
            return submitted.input_json
        finally:
            leave_invocation()

    try:
        failed = queue.submit(plan("cpu", source="gated-start"), first_worker)
        assert start_failure_raised.wait(5)
        eventually(lambda: queue.snapshot(failed).state == JobState.FAILED)
        assert queue._used["cpu"] == 0
        assert all(used >= 0 for used in queue._used.values())
        assert first_calls == 0

        release_run.set()
        assert run_finished.wait(5)
        launched[0].join(5)
        assert not launched[0].is_alive()
        assert first_calls == 0

        replacement = queue.submit(
            plan("cpu", source="replacement"), replacement_worker
        )
        assert replacement_entered.wait(5)
        assert queue.snapshot(replacement).state == JobState.RUNNING
        assert queue._used["cpu"] == 1
        assert queue._used["cpu"] >= 0
        assert not first_entered.is_set()
        assert maximum_active_invocations <= 1

        release_replacement.set()
        assert queue.drain(5)
        assert queue._used["cpu"] == 0
        assert all(used >= 0 for used in queue._used.values())
        assert active_invocations == 0
        assert maximum_active_invocations <= 1
        assert thread_errors == []
    finally:
        release_run.set()
        release_first.set()
        release_replacement.set()
        queue.close()
        for thread in launched:
            thread.join(5)


def test_close_joins_native_launch_aborted_before_worker_entry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_entered, release_run, run_finished = Event(), Event(), Event()
    start_failure_raised = Event()
    launched: list[Thread] = []
    thread_errors: list[BaseException] = []
    original_run = JobQueue._run

    def gated_run(
        queue: JobQueue, job_id: str, worker: Callable[[JobPlan, JobContext], object]
    ) -> None:
        run_entered.set()
        try:
            assert release_run.wait(10)
            original_run(queue, job_id, worker)
        finally:
            run_finished.set()

    monkeypatch.setattr(JobQueue, "_run", gated_run)
    monkeypatch.setattr(
        queue_module,
        "Thread",
        _launch_then_raise_thread_class(run_entered, start_failure_raised, launched),
    )
    monkeypatch.setattr(
        threading, "excepthook", capture_thread_exceptions(thread_errors)
    )
    queue = JobQueue({"cpu": 1}, lambda _: None)
    worker_calls = 0

    def worker(submitted: JobPlan, context: JobContext) -> object:
        nonlocal worker_calls
        worker_calls += 1
        return submitted.input_json

    try:
        job_id = queue.submit(plan("cpu", source="gated-close"), worker)
        assert start_failure_raised.wait(5)
        eventually(lambda: queue.snapshot(job_id).state == JobState.FAILED)
        assert queue._used["cpu"] == 0
        assert all(used >= 0 for used in queue._used.values())
        assert worker_calls == 0

        queue.close()
        assert launched[0].is_alive()
        assert worker_calls == 0

        release_run.set()
        assert run_finished.wait(5)
        launched[0].join(5)
        assert not launched[0].is_alive()
        assert worker_calls == 0
        assert queue._used["cpu"] == 0
        assert all(used >= 0 for used in queue._used.values())
        assert thread_errors == []
    finally:
        release_run.set()
        queue.close()
        for thread in launched:
            thread.join(5)


def test_worker_start_baseexception_releases_slot_and_scheduler_continues(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class InjectedPostLaunchFailure(BaseException):
        pass

    failure_raised = Event()
    launched_threads: list[Thread] = []
    thread_errors: list[BaseException] = []

    class FailingWorkerThread(Thread):
        def start(self) -> None:
            super().start()
            if self.name.startswith("job-"):
                launched_threads.append(self)
                if not failure_raised.is_set():
                    failure_raised.set()
                    raise InjectedPostLaunchFailure("injected post-launch failure")

    monkeypatch.setattr(
        threading, "excepthook", capture_thread_exceptions(thread_errors)
    )
    monkeypatch.setattr(queue_module, "Thread", FailingWorkerThread)
    queue = JobQueue({"cpu": 1}, lambda _: None)
    first_calls = 0
    later_calls = 0
    later_entered = Event()

    def first_worker(submitted: JobPlan, context: JobContext) -> object:
        nonlocal first_calls
        first_calls += 1
        return submitted.input_json

    def later_worker(submitted: JobPlan, context: JobContext) -> object:
        nonlocal later_calls
        later_calls += 1
        later_entered.set()
        return submitted.input_json

    try:
        failed = queue.submit(plan("cpu", source="first"), first_worker)
        assert failure_raised.wait(5)
        eventually(lambda: queue.snapshot(failed).state == JobState.FAILED)
        launched_threads[0].join(5)
        assert not launched_threads[0].is_alive()
        assert first_calls == 0
        assert queue._used["cpu"] == 0
        assert all(used >= 0 for used in queue._used.values())

        later = queue.submit(plan("cpu", source="later"), later_worker)
        assert later_entered.wait(5)
        assert queue.drain(5)
        assert queue.snapshot(later).state == JobState.COMPLETED
        assert later_calls == 1
        assert first_calls == 0
        assert queue._used["cpu"] == 0
        assert all(used >= 0 for used in queue._used.values())
        assert thread_errors == []
    finally:
        queue.close()
        for thread in launched_threads:
            thread.join(5)


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


def test_worker_exception_with_broken_string_fails_and_releases_capacity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class UnprintableWorkerError(Exception):
        def __str__(self) -> str:
            raise RuntimeError("cannot format worker exception")

    thread_errors: list[BaseException] = []
    following_entered = Event()
    following_calls = 0

    monkeypatch.setattr(
        threading, "excepthook", capture_thread_exceptions(thread_errors)
    )
    queue = JobQueue({"cpu": 1}, lambda _: None)

    def failed_worker(submitted: JobPlan, context: JobContext) -> object:
        raise UnprintableWorkerError

    def following_worker(submitted: JobPlan, context: JobContext) -> object:
        nonlocal following_calls
        following_calls += 1
        following_entered.set()
        return submitted.input_json

    try:
        failed = queue.submit(plan("cpu", source="unprintable"), failed_worker)
        following = queue.submit(plan("cpu", source="following"), following_worker)
        assert queue.drain(5)
        assert following_entered.is_set()
        assert following_calls == 1
        assert queue.snapshot(failed).state == JobState.FAILED
        assert queue.snapshot(failed).detail == "UnprintableWorkerError"
        assert queue.snapshot(following).state == JobState.COMPLETED
        assert queue._used["cpu"] == 0
        assert all(used >= 0 for used in queue._used.values())
        queue.close()
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
    "reason",
    [
        pytest.param("", id="empty"),
        pytest.param("   ", id="whitespace"),
    ],
)
def test_empty_validator_reason_needs_attention_without_running_worker(
    reason: str,
) -> None:
    worker_calls = 0

    def validate(submitted: JobPlan) -> str | None:
        return reason

    def worker(submitted: JobPlan, context: JobContext) -> object:
        nonlocal worker_calls
        worker_calls += 1
        return None

    queue = JobQueue({"cpu": 1}, validate)
    try:
        job = queue.submit(plan("cpu"), worker)
        assert queue.drain(5)
        snapshot = queue.snapshot(job)
        assert snapshot.state == JobState.NEEDS_ATTENTION
        assert snapshot.detail == "Plan validation returned an empty reason"
        assert snapshot.detail.strip()
        assert worker_calls == 0
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


@pytest.mark.parametrize("target_length", [4096, 4097], ids=["at-limit", "over-limit"])
def test_worker_and_validator_details_preserve_exact_truncation_boundary(
    target_length: int,
) -> None:
    worker_prefix = "RuntimeError: "
    worker_message = "w" * (target_length - len(worker_prefix))
    validator_reason = "v" * target_length
    validator_worker_called = Event()

    def validate(submitted: JobPlan) -> str | None:
        if submitted.input_json == '{"source":"validator-boundary"}':
            return validator_reason
        return None

    def worker_failure(submitted: JobPlan, context: JobContext) -> object:
        raise RuntimeError(worker_message)

    def validator_worker(submitted: JobPlan, context: JobContext) -> object:
        validator_worker_called.set()
        return submitted.input_json

    queue = JobQueue({"worker": 1, "validator": 1}, validate)
    try:
        worker_job = queue.submit(
            plan("worker", source="worker-boundary"), worker_failure
        )
        validator_job = queue.submit(
            plan("validator", source="validator-boundary"), validator_worker
        )
        assert queue.drain(5)

        expected_worker_detail = f"{worker_prefix}{worker_message}"
        expected_validator_detail = validator_reason
        if target_length > queue_module._MAX_DETAIL:
            suffix = queue_module._DETAIL_TRUNCATION_SUFFIX
            expected_worker_detail = (
                expected_worker_detail[: queue_module._MAX_DETAIL - len(suffix)]
                + suffix
            )
            expected_validator_detail = (
                expected_validator_detail[: queue_module._MAX_DETAIL - len(suffix)]
                + suffix
            )

        worker_detail = queue.snapshot(worker_job).detail
        validator_detail = queue.snapshot(validator_job).detail
        assert queue.snapshot(worker_job).state == JobState.FAILED
        assert queue.snapshot(validator_job).state == JobState.NEEDS_ATTENTION
        assert worker_detail == expected_worker_detail
        assert validator_detail == expected_validator_detail
        assert len(worker_detail) == len(validator_detail) == queue_module._MAX_DETAIL
        assert worker_detail.endswith(queue_module._DETAIL_TRUNCATION_SUFFIX) is (
            target_length > queue_module._MAX_DETAIL
        )
        assert validator_detail.endswith(queue_module._DETAIL_TRUNCATION_SUFFIX) is (
            target_length > queue_module._MAX_DETAIL
        )
        assert not validator_worker_called.is_set()
    finally:
        queue.close()
