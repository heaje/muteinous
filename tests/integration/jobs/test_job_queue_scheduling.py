"""Deterministic integration tests for the in-process job queue."""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Callable
from threading import Event

import pytest

from muteinous.infrastructure.jobs.queue import (
    JobContext,
    JobPlan,
    JobQueue,
    JobState,
)
from tests.support.job_queue import (
    ControlledWorker,
    FakeClock,
    eventually,
    plan,
)

pytestmark = pytest.mark.portable


def test_job_plan_factory_json_escapes_source_text() -> None:
    source = 'a"b\\c'
    submitted = plan("cpu", source=source)
    assert plan("cpu").input_json == '{"source":"v1"}'
    assert json.loads(submitted.input_json) == {"source": source}


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


def test_busy_later_resource_does_not_reserve_free_gpu(
    workers: Callable[..., ControlledWorker],
) -> None:
    queue = JobQueue({"cpu": 1, "gpu": 1}, lambda _: None)
    cpu_owner, waiting, gpu_only = (workers() for _ in range(3))
    try:
        queue.submit(plan("cpu", source="cpu-owner"), cpu_owner)
        assert cpu_owner.entered.wait(5)

        waiting_id = queue.submit(plan("gpu", "cpu", source="both"), waiting)
        eventually(
            lambda: (
                queue.snapshot(waiting_id).state == JobState.QUEUED
                and queue.snapshot(waiting_id).detail == "Waiting for: cpu"
            )
        )
        assert queue._used["gpu"] == 0

        gpu_id = queue.submit(plan("gpu", source="gpu-only"), gpu_only)
        assert gpu_only.entered.wait(5)
        assert queue.snapshot(gpu_id).state == JobState.RUNNING
        assert queue._used["gpu"] == 1
        assert not waiting.entered.is_set()
        assert waiting.calls == 0

        gpu_only.release.set()
        eventually(lambda: queue.snapshot(gpu_id).state == JobState.COMPLETED)
        assert not waiting.entered.is_set()

        cpu_owner.release.set()
        assert waiting.entered.wait(5)
        assert waiting.calls == 1
        assert queue._used["gpu"] == queue._used["cpu"] == 1
        waiting.release.set()
        assert queue.drain(5)
        assert waiting.calls == gpu_only.calls == 1
        assert queue._used["gpu"] == queue._used["cpu"] == 0
    finally:
        for worker in (cpu_owner, waiting, gpu_only):
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


def test_multi_resource_reservation_blocks_cpu_only_job_until_release() -> None:
    queue = JobQueue({"gpu": 1, "cpu": 1}, lambda _: None)
    multi_entered, release_multi, cpu_entered = Event(), Event(), Event()
    multi_calls = 0
    cpu_calls = 0

    def multi_worker(submitted: JobPlan, context: JobContext) -> object:
        nonlocal multi_calls
        multi_calls += 1
        multi_entered.set()
        assert release_multi.wait(10)
        return submitted.input_json

    def cpu_worker(submitted: JobPlan, context: JobContext) -> object:
        nonlocal cpu_calls
        cpu_calls += 1
        cpu_entered.set()
        return submitted.input_json

    try:
        multi_id = queue.submit(plan("gpu", "cpu", source="multi"), multi_worker)
        assert multi_entered.wait(5)
        cpu_id = queue.submit(plan("cpu", source="cpu-only"), cpu_worker)
        eventually(lambda: queue.snapshot(cpu_id).detail == "Waiting for: cpu")
        assert not cpu_entered.is_set()
        assert queue._used["gpu"] == queue._used["cpu"] == 1

        release_multi.set()
        assert cpu_entered.wait(5)
        assert queue.drain(5)
        assert queue.snapshot(multi_id).state == JobState.COMPLETED
        assert queue.snapshot(cpu_id).state == JobState.COMPLETED
        assert multi_calls == cpu_calls == 1
        assert queue._used["gpu"] == queue._used["cpu"] == 0
    finally:
        release_multi.set()
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
