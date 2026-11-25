"""Deterministic integration tests for the in-process job queue."""

from __future__ import annotations

import gc
from collections import Counter
from collections.abc import Callable
from threading import Event
from weakref import ReferenceType, ref

import pytest

from muteinous.infrastructure.jobs.queue import (
    JobContext,
    JobPlan,
    JobQueue,
    JobState,
    Progress,
    WorkCount,
)
from tests.support.job_queue import (
    ControlledWorker,
    FakeClock,
    eventually,
    plan,
)

pytestmark = pytest.mark.portable


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


def test_poll_does_not_repeat_a_delivered_routine_update_after_interval() -> None:
    clock = FakeClock()
    contexts: list[JobContext] = []
    entered, release = Event(), Event()

    def worker(submitted: JobPlan, context: JobContext) -> object:
        contexts.append(context)
        entered.set()
        assert release.wait(10)
        return submitted.input_json

    queue = JobQueue({"cpu": 1}, lambda _: None, progress_interval=1.0, clock=clock)
    try:
        job = queue.submit(plan("cpu"), worker)
        assert entered.wait(5)
        context = contexts[0]
        running = queue.snapshot(job)
        context.report(Progress("scan", stage_count=WorkCount(0)), meaningful=True)
        transition = queue.poll(job, running.revision)
        assert transition is not None and transition.progress.stage == "scan"

        clock.now = 0.5
        context.report(Progress("scan", stage_count=WorkCount(1)), meaningful=True)
        assert queue.poll(job, transition.revision) is None

        clock.now = 1.0
        routine_update = queue.poll(job, transition.revision)
        assert routine_update is not None
        assert routine_update.progress.stage_count == WorkCount(1)

        # Once delivered, polling that current revision must not replay it,
        # even after another full presentation interval.
        clock.now = 2.0
        assert queue.poll(job, routine_update.revision) is None
    finally:
        release.set()
        queue.close()


def test_poll_coalesces_second_routine_update_from_last_delivery() -> None:
    clock = FakeClock()
    contexts: list[JobContext] = []
    entered, release = Event(), Event()

    def worker(submitted: JobPlan, context: JobContext) -> object:
        contexts.append(context)
        entered.set()
        assert release.wait(10)
        return submitted.input_json

    queue = JobQueue({"cpu": 1}, lambda _: None, progress_interval=1.0, clock=clock)
    try:
        job = queue.submit(plan("cpu"), worker)
        assert entered.wait(5)
        context = contexts[0]
        running = queue.snapshot(job)
        context.report(Progress("scan", stage_count=WorkCount(0)), meaningful=True)
        transition = queue.poll(job, running.revision)
        assert transition is not None

        clock.now = 0.5
        context.report(Progress("scan", stage_count=WorkCount(1)), meaningful=True)
        assert queue.poll(job, transition.revision) is None

        clock.now = 1.0
        first_update = queue.poll(job, transition.revision)
        assert first_update is not None
        assert first_update.progress.stage_count == WorkCount(1)

        clock.now = 1.1
        context.report(Progress("scan", stage_count=WorkCount(2)), meaningful=True)
        assert queue.poll(job, first_update.revision) is None

        clock.now = 2.0
        second_update = queue.poll(job, first_update.revision)
        assert second_update is not None
        assert second_update.progress.stage_count == WorkCount(2)
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
