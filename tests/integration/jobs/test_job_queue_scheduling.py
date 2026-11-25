"""Deterministic integration tests for the in-process job queue."""

from __future__ import annotations

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
                and "cpu" in (queue.snapshot(waiting_id).detail or "")
            )
        )

        gpu_id = queue.submit(plan("gpu", source="gpu-only"), gpu_only)
        assert gpu_only.entered.wait(5)
        assert queue.snapshot(gpu_id).state == JobState.RUNNING
        assert not waiting.entered.is_set()
        assert waiting.calls == 0

        gpu_only.release.set()
        eventually(lambda: queue.snapshot(gpu_id).state == JobState.COMPLETED)
        assert not waiting.entered.is_set()

        cpu_owner.release.set()
        assert waiting.entered.wait(5)
        assert waiting.calls == 1
        waiting.release.set()
        assert queue.drain(5)
        assert waiting.calls == gpu_only.calls == 1
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
        assert "controlled failure" in (queue.snapshot(a).detail or "")
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
        eventually(lambda: "gpu" in (queue.snapshot(old).detail or ""))
        stale.set()
        clock.now += 1.1
        queue.set_capacity("other", 1)
        eventually(lambda: queue.snapshot(old).state == JobState.NEEDS_ATTENTION)
        assert "Source changed" in (queue.snapshot(old).detail or "")
        eventually(lambda: queue.snapshot(missing).state == JobState.NEEDS_ATTENTION)
        assert "missing" in (queue.snapshot(missing).detail or "")
        eventually(lambda: "gpu" in (queue.snapshot(good).detail or ""))
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

    def validate(submitted: JobPlan) -> str | None:
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
        eventually(lambda: "cpu" in (queue.snapshot(waiting_id).detail or ""))
        assert queue.snapshot(waiting_id).state == JobState.QUEUED

        stale.set()
        # No queue operation after this flag change may wake the dispatcher.
        assert stale_revalidated.wait(5)
        eventually(lambda: queue.snapshot(waiting_id).state == JobState.NEEDS_ATTENTION)
        assert "Source changed" in (queue.snapshot(waiting_id).detail or "")
        owner.release.set()
        assert queue.drain(5)
        assert queue.snapshot(waiting_id).state == JobState.NEEDS_ATTENTION
        assert waiting.calls == 0
    finally:
        owner.release.set()
        waiting.release.set()
        queue.close()


def test_busy_plans_revalidate_on_interval_and_eligible_plans_before_dispatch(
    workers: Callable[..., ControlledWorker],
) -> None:
    clock = FakeClock()
    calls: Counter[str] = Counter()
    worker_calls: Counter[str] = Counter()
    dispatch_validation_counts: dict[str, int] = {}

    def validate(submitted: JobPlan) -> str | None:
        calls[submitted.input_json] += 1
        return None

    def quick_worker(submitted: JobPlan, context: JobContext) -> object:
        worker_calls[submitted.input_json] += 1
        dispatch_validation_counts[submitted.input_json] = calls[submitted.input_json]
        return submitted.input_json

    queue = JobQueue(
        {"provider": 1, "aux": 1, "other": 1},
        validate,
        revalidate_interval=1.0,
        clock=clock,
    )
    owner = workers()
    try:
        queue.submit(plan("provider", source="owner"), owner)
        assert owner.entered.wait(5)
        pending = [
            plan("provider", source="busy"),
            plan("provider", "aux", source="partially-blocked"),
        ]
        jobs = [queue.submit(submitted, quick_worker) for submitted in pending]
        eventually(
            lambda: all(
                "provider" in (queue.snapshot(job_id).detail or "")
                and calls[submitted.input_json] >= 1
                for job_id, submitted in zip(jobs, pending, strict=True)
            )
        )
        initial_counts = {
            submitted.input_json: calls[submitted.input_json] for submitted in pending
        }

        for capacity in (2, 1, 2, 1, 2):
            queue.set_capacity("other", capacity)

        canary = queue.submit(plan("other", source="canary"), quick_worker)
        eventually(lambda: queue.snapshot(canary).state == JobState.COMPLETED)
        assert all(
            calls[submitted.input_json] == initial_counts[submitted.input_json]
            for submitted in pending
        )

        clock.now += 1.1
        queue.set_capacity("other", 1)
        # The independent job is scanned after the blocked plans, so its
        # completion confirms their validation has been processed.
        canary = queue.submit(plan("other", source="revalidation-canary"), quick_worker)
        eventually(lambda: queue.snapshot(canary).state == JobState.COMPLETED)
        busy_counts = {
            submitted.input_json: calls[submitted.input_json] for submitted in pending
        }
        assert all(busy_counts[key] > initial_counts[key] for key in busy_counts)
        assert all(queue.snapshot(job_id).state == JobState.QUEUED for job_id in jobs)

        owner.release.set()
        assert queue.drain(5)
        assert all(
            dispatch_validation_counts[key] > busy_counts[key] for key in busy_counts
        )
        assert all(worker_calls[submitted.input_json] == 1 for submitted in pending)
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
    queue = JobQueue({"provider": 1, "other": 1}, lambda _: None, clock=clock)
    owner, waiting = workers(), workers()
    try:
        owner_id = queue.submit(plan("provider", source="owner"), owner)
        assert owner.entered.wait(5)
        waiting_id = queue.submit(plan("provider", source="waiting"), waiting)
        eventually(lambda: "provider" in (queue.snapshot(waiting_id).detail or ""))

        clock.now += 365 * 24 * 60 * 60
        # A younger independent job confirms the scheduler has scanned the waiter.
        canary = queue.submit(plan("other"), lambda submitted, context: None)
        eventually(lambda: queue.snapshot(canary).state == JobState.COMPLETED)
        assert queue.snapshot(owner_id).state == JobState.RUNNING
        waiting_snapshot = queue.snapshot(waiting_id)
        assert waiting_snapshot.state == JobState.QUEUED
        assert "provider" in (waiting_snapshot.detail or "")

        owner.release.set()
        assert waiting.entered.wait(5)
        waiting.release.set()
        assert queue.drain(5)
        assert waiting.calls == 1
        assert queue.snapshot(waiting_id).state == JobState.COMPLETED
        assert queue.snapshot(owner_id).state == JobState.COMPLETED
    finally:
        owner.release.set()
        waiting.release.set()
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
        eventually(lambda: "cpu" in (queue.snapshot(waiting_id).detail or ""))

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


def test_multi_resource_reservation_blocks_both_resources_until_release(
    workers: Callable[..., ControlledWorker],
) -> None:
    queue = JobQueue({"gpu": 1, "cpu": 1}, lambda _: None)
    multi, cpu, gpu = workers(), workers(), workers()
    try:
        multi_id = queue.submit(plan("gpu", "cpu"), multi)
        assert multi.entered.wait(5)
        cpu_id = queue.submit(plan("cpu"), cpu)
        gpu_id = queue.submit(plan("gpu"), gpu)
        eventually(lambda: "cpu" in (queue.snapshot(cpu_id).detail or ""))
        eventually(lambda: "gpu" in (queue.snapshot(gpu_id).detail or ""))
        assert queue.snapshot(cpu_id).state == JobState.QUEUED
        assert queue.snapshot(gpu_id).state == JobState.QUEUED
        assert not cpu.entered.is_set() and not gpu.entered.is_set()

        multi.release.set()
        assert cpu.entered.wait(5) and gpu.entered.wait(5)
        cpu.release.set()
        gpu.release.set()
        assert queue.drain(5)
        assert all(
            queue.snapshot(job).state == JobState.COMPLETED
            for job in (multi_id, cpu_id, gpu_id)
        )
        assert multi.calls == cpu.calls == gpu.calls == 1
    finally:
        for worker in (multi, cpu, gpu):
            worker.release.set()
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
        eventually(lambda: "cpu" in (queue.snapshot(waiting_id).detail or ""))

        queue.set_capacity("cpu", 0)
        eventually(lambda: queue.snapshot(waiting_id).state == JobState.NEEDS_ATTENTION)
        unavailable = queue.snapshot(waiting_id)
        assert "cpu" in (unavailable.detail or "")
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
        eventually(lambda: "cpu" in (queue.snapshot(b).detail or ""))
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
        eventually(lambda: "gpu" in (queue.snapshot(old).detail or ""))
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
