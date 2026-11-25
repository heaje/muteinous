"""In-process scheduling; providers retain ownership of domain validity and effects."""

from __future__ import annotations

import json
import math
import time
from collections import Counter
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from enum import StrEnum
from threading import Condition, Event, Thread
from uuid import uuid4


class JobState(StrEnum):
    QUEUED = "Queued"
    RUNNING = "Running"
    COMPLETED = "Completed"
    FAILED = "Failed"
    CANCELLED = "Cancelled"
    NEEDS_ATTENTION = "Needs attention"


def _error_detail(error: BaseException) -> str:
    try:
        return f"{type(error).__name__}: {error}"
    except BaseException:
        return type(error).__name__


def _reject_constant(value: str) -> None:
    raise ValueError(f"Invalid JSON constant: {value}")


def _reject_nonfinite_float(value: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed):
        raise ValueError(f"Invalid non-finite JSON number: {value}")
    return parsed


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON object key: {key}")
        result[key] = value
    return result


@dataclass(frozen=True, slots=True)
class JobPlan:
    """Resolved execution choices and JSON input (including source/config context)."""

    provider: str
    backend: str
    resources: tuple[str, ...]
    input_json: str

    def __post_init__(self) -> None:
        if (
            not isinstance(self.provider, str)
            or not isinstance(self.backend, str)
            or not isinstance(self.resources, tuple)
            or not all(isinstance(resource, str) for resource in self.resources)
            or not isinstance(self.input_json, str)
        ):
            raise ValueError("Job plan fields must use their declared string types")
        if not self.provider or not self.backend:
            raise ValueError("Provider and backend must be resolved")
        if (
            not self.resources
            or not all(self.resources)
            or len(set(self.resources)) != len(self.resources)
        ):
            raise ValueError("Declare distinct, nonempty resource names")
        try:
            parsed_input = json.loads(
                self.input_json,
                parse_constant=_reject_constant,
                parse_float=_reject_nonfinite_float,
                object_pairs_hook=_reject_duplicate_keys,
            )
        except RecursionError as error:
            raise ValueError("Job input is too deeply nested") from error
        if not isinstance(parsed_input, dict):
            raise ValueError("Job input must be a JSON object")


@dataclass(frozen=True, slots=True)
class WorkCount:
    completed: int
    total: int | None = None
    reliable: bool = False

    @property
    def percentage(self) -> float | None:
        if (
            self.reliable is True
            and type(self.completed) is int
            and self.total is not None
            and type(self.total) is int
            and self.total > 0
            and 0 <= self.completed <= self.total
        ):
            return 100 * (self.completed / self.total)
        return None


@dataclass(frozen=True, slots=True)
class Progress:
    stage: str | None = None
    activity: str | None = None
    stage_count: WorkCount | None = None
    overall_count: WorkCount | None = None


@dataclass(frozen=True, slots=True)
class JobSnapshot:
    job_id: str
    plan: JobPlan
    state: JobState = JobState.QUEUED
    physical_running: bool = False
    detail: str | None = None
    result: object = None
    progress: Progress = field(default_factory=Progress)
    last_progress_at: float | None = None
    last_activity_at: float | None = None
    revision: int = 1


class JobContext:
    """Optional reporting and cooperative cancellation for a single invocation."""

    def __init__(self, queue: JobQueue, job_id: str, cancelled: Event) -> None:
        self._queue = queue
        self._job_id = job_id
        self._cancelled = cancelled

    @property
    def cancelled(self) -> bool:
        return self._cancelled.is_set()

    def wait_cancelled(self, timeout: float | None = None) -> bool:
        return self._cancelled.wait(timeout)

    def report(self, progress: Progress, *, meaningful: bool = False) -> None:
        self._queue._report(self._job_id, progress, meaningful)

    def heartbeat(self) -> None:
        self._queue._report(self._job_id, None, False)


Worker = Callable[[JobPlan, JobContext], object]
PlanValidator = Callable[[JobPlan], str | None]


@dataclass(slots=True)
class _Record:
    snapshot: JobSnapshot
    published_at: float
    published_revision: int = 1
    last_validated_at: float | None = None
    cancelled: Event = field(default_factory=Event)


class JobQueue:
    """One dispatcher, one physical invocation per job, named slots per invocation.

    The validator returns None for a usable plan, otherwise a reason. It must be
    quick, read-only and independent of ordinary preference changes or busy slots.
    It runs outside the scheduler lock, including for resource-blocked plans.
    Workers must return only once their physical provider work has actually stopped.
    Callers own result publication and must not commit effects from cancelled jobs.
    """

    def __init__(
        self,
        capacities: Mapping[str, int],
        validate: PlanValidator,
        *,
        progress_interval: float = 0.25,
        revalidate_interval: float = 1.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        for name, capacity in capacities.items():
            self._check_capacity(name, capacity)
        if not 0 < progress_interval < float("inf"):
            raise ValueError("Progress interval must be finite and positive")
        if not 0 < revalidate_interval < float("inf"):
            raise ValueError("Revalidation interval must be finite and positive")
        self._capacities = dict(capacities)
        self._validate = validate
        self._progress_interval = progress_interval
        self._revalidate_interval = revalidate_interval
        self._clock = clock
        self._condition = Condition()
        self._records: dict[str, _Record] = {}
        self._pending: dict[str, Worker] = {}
        self._active: set[str] = set()
        self._used: Counter[str] = Counter()
        self._threads: set[Thread] = set()
        self._generation = 0
        self._capacity_revision = 0
        self._closed = False
        self._dispatcher = Thread(
            target=self._schedule, name="muteinous-jobs", daemon=False
        )
        self._dispatcher.start()

    @staticmethod
    def _check_capacity(name: str, capacity: int) -> None:
        if not name or type(capacity) is not int or capacity < 0:
            raise ValueError("Resource capacities must be nonnegative integers")

    def _wake(self) -> None:
        self._generation += 1
        self._condition.notify_all()

    def _store(
        self, record: _Record, snapshot: JobSnapshot, *, material: bool = True
    ) -> None:
        snapshot = replace(snapshot, revision=record.snapshot.revision + 1)
        record.snapshot = snapshot
        if material:
            record.published_revision = snapshot.revision
            record.published_at = self._clock()

    def submit(self, plan: JobPlan, worker: Worker) -> str:
        with self._condition:
            if self._closed:
                raise RuntimeError("Job queue is closed")
            job_id = str(uuid4())
            self._records[job_id] = _Record(JobSnapshot(job_id, plan), self._clock())
            self._pending[job_id] = worker
            self._wake()
            return job_id

    def set_capacity(self, name: str, capacity: int) -> None:
        """Zero means unavailable; reductions never revoke occupied slots."""
        self._check_capacity(name, capacity)
        with self._condition:
            if self._closed:
                raise RuntimeError("Job queue is closed")
            self._capacities[name] = capacity
            self._capacity_revision += 1
            self._wake()

    def snapshot(self, job_id: str) -> JobSnapshot:
        """Return the latest state, regardless of presentation throttling."""
        with self._condition:
            return self._records[job_id].snapshot

    def poll(self, job_id: str, after_revision: int = 0) -> JobSnapshot | None:
        """Return a coalesced presentation update; material changes bypass throttling."""
        with self._condition:
            record = self._records[job_id]
            snapshot = record.snapshot
            if snapshot.revision <= after_revision:
                return None
            now = self._clock()
            if (
                record.published_revision <= after_revision
                and now - record.published_at < self._progress_interval
            ):
                return None
            if record.published_revision < snapshot.revision:
                record.published_revision = snapshot.revision
                record.published_at = now
            return snapshot

    def _report(self, job_id: str, progress: Progress | None, meaningful: bool) -> None:
        with self._condition:
            record = self._records.get(job_id)
            if record is None:
                return
            old = record.snapshot
            if old.state != JobState.RUNNING:
                return
            now = self._clock()
            current = old.progress if progress is None else progress
            self._store(
                record,
                replace(
                    old,
                    progress=current,
                    last_activity_at=now,
                    last_progress_at=now if meaningful else old.last_progress_at,
                ),
                material=current.stage != old.progress.stage,
            )

    def cancel(self, job_id: str) -> bool:
        with self._condition:
            record = self._records[job_id]
            old = record.snapshot
            if old.state not in (JobState.QUEUED, JobState.RUNNING):
                return False
            record.cancelled.set()
            self._pending.pop(job_id, None)
            self._store(
                record,
                replace(old, state=JobState.CANCELLED, detail="Cancelled by request"),
            )
            self._wake()
            return True

    def discard(self, job_id: str) -> bool:
        """Discard a terminal, physically stopped job and release its result."""
        with self._condition:
            record = self._records[job_id]
            if (
                record.snapshot.state
                not in (
                    JobState.COMPLETED,
                    JobState.FAILED,
                    JobState.CANCELLED,
                    JobState.NEEDS_ATTENTION,
                )
                or record.snapshot.physical_running
            ):
                return False
            del self._records[job_id]
            return True

    def _validate_plan(self, plan: JobPlan) -> str | None:
        try:
            return self._validate(plan)
        except BaseException as error:
            return f"Plan validation failed: {_error_detail(error)}"

    def _schedule(self) -> None:
        while True:
            processing_job_id: str | None = None
            try:
                with self._condition:
                    if self._closed:
                        return
                    generation = self._generation
                    capacity_revision = self._capacity_revision
                    plans = [
                        (job_id, self._records[job_id].snapshot.plan)
                        for job_id in self._pending
                    ]
                    self._threads = {
                        thread for thread in self._threads if thread.is_alive()
                    }
                for job_id, plan in plans:
                    processing_job_id = job_id
                    with self._condition:
                        if self._closed:
                            return
                        if self._capacity_revision != capacity_revision:
                            break
                        if job_id not in self._pending:
                            processing_job_id = None
                            continue
                        record = self._records[job_id]
                        eligible = all(
                            self._capacities.get(resource, 0) > self._used[resource]
                            for resource in plan.resources
                        )
                        last_validated_at = record.last_validated_at
                        should_validate = (
                            eligible
                            or last_validated_at is None
                            or self._clock() - last_validated_at
                            >= self._revalidate_interval
                        )
                        if not should_validate:
                            self._dispatch(job_id, None)
                            self._condition.notify_all()
                            processing_job_id = None
                            continue
                    # Never hold the lock across external validation. If capacity
                    # changed, restart at the oldest pending job before dispatching
                    # a younger one: a previously blocked job may now be eligible.
                    reason = self._validate_plan(plan)
                    validated_at = self._clock()
                    with self._condition:
                        if self._closed:
                            return
                        if self._capacity_revision != capacity_revision:
                            break
                        if job_id in self._pending:
                            self._records[job_id].last_validated_at = validated_at
                            self._dispatch(job_id, reason)
                        self._condition.notify_all()
                    processing_job_id = None
                with self._condition:
                    self._condition.notify_all()
                    timeout = self._next_revalidation_delay()
                    self._condition.wait_for(
                        lambda: self._closed or self._generation != generation,
                        timeout=timeout,
                    )
            except BaseException as error:
                with self._condition:
                    if processing_job_id is not None:
                        if processing_job_id in self._pending:
                            self._fail_job(
                                processing_job_id,
                                f"Scheduler failed: {_error_detail(error)}",
                            )
                    self._condition.notify_all()
                    if self._closed:
                        return
                    generation = self._generation
                    self._condition.wait_for(
                        lambda: self._closed or self._generation != generation,
                        timeout=0.25,
                    )

    def _next_revalidation_delay(self) -> float | None:
        if not self._pending:
            return None
        validated = [
            self._records[job_id].last_validated_at for job_id in self._pending
        ]
        if any(value is None for value in validated):
            return 0.0
        next_due = min(
            value + self._revalidate_interval
            for value in validated
            if value is not None
        )
        return max(0.0, next_due - self._clock())

    def _fail_job(
        self,
        job_id: str,
        detail: str,
        *,
        reserved: bool = False,
        thread: Thread | None = None,
    ) -> None:
        record = self._records.get(job_id)
        if record is None:
            return
        self._pending.pop(job_id, None)
        if reserved:
            self._used.subtract(record.snapshot.plan.resources)
            self._active.discard(job_id)
            self._capacity_revision += 1
        if thread is not None:
            self._threads.discard(thread)
        old = record.snapshot
        failed = replace(
            old,
            state=JobState.FAILED,
            physical_running=False,
            result=None,
            detail=detail,
            revision=old.revision + 1,
        )
        record.snapshot = failed
        record.published_revision = failed.revision
        self._wake()

    def _dispatch(self, job_id: str, reason: str | None) -> None:
        record = self._records[job_id]
        old = record.snapshot
        resources = old.plan.resources
        unavailable = [name for name in resources if not self._capacities.get(name, 0)]
        if reason is not None or unavailable:
            self._pending.pop(job_id)
            detail = reason
            if detail is None:
                detail = f"Unavailable: {', '.join(unavailable)}"
            self._store(
                record, replace(old, state=JobState.NEEDS_ATTENTION, detail=detail)
            )
            return
        busy = [
            name for name in resources if self._used[name] >= self._capacities[name]
        ]
        if busy:
            detail = f"Waiting for: {', '.join(busy)}"
            if old.detail != detail:
                self._store(record, replace(old, detail=detail))
            return
        worker = self._pending.pop(job_id)
        reserved = False
        thread: Thread | None = None
        try:
            self._used.update(resources)
            reserved = True
            self._active.add(job_id)
            self._store(
                record,
                replace(
                    old, state=JobState.RUNNING, physical_running=True, detail=None
                ),
            )
            thread = Thread(
                target=self._run,
                args=(job_id, worker),
                name=f"job-{job_id}",
                daemon=False,
            )
            self._threads.add(thread)
            thread.start()
        except BaseException as error:
            if thread is not None and thread.ident is not None:
                # Swallow post-launch errors; _run owns this reservation now.
                return
            self._fail_job(
                job_id,
                f"Worker start failed: {_error_detail(error)}",
                reserved=reserved,
                thread=thread,
            )

    def _run(self, job_id: str, worker: Worker) -> None:
        with self._condition:
            record = self._records[job_id]
            plan = record.snapshot.plan
            context = JobContext(self, job_id, record.cancelled)
        state = JobState.COMPLETED
        result: object = None
        detail: str | None = None
        try:
            if not context.cancelled:
                result = worker(plan, context)
        except BaseException as error:
            state = JobState.FAILED
            detail = _error_detail(error)
        with self._condition:
            self._finish(job_id, state, result, detail)

    def _finish(
        self, job_id: str, state: JobState, result: object, detail: str | None
    ) -> None:
        record = self._records[job_id]
        old = record.snapshot
        self._used.subtract(old.plan.resources)
        self._active.remove(job_id)
        self._capacity_revision += 1
        if old.state == JobState.CANCELLED:
            self._store(record, replace(old, physical_running=False))
        else:
            self._store(
                record,
                replace(
                    old,
                    state=state,
                    physical_running=False,
                    result=result,
                    detail=detail,
                ),
            )
        self._wake()

    def drain(self, timeout: float | None = None) -> bool:
        """Wait for pending and physical work; a wait timeout never cancels a job."""
        with self._condition:
            return self._condition.wait_for(
                lambda: not self._pending and not self._active, timeout
            )

    def close(self) -> None:
        """Stop accepting work, cancel jobs and join all physical workers.

        Call from the owning thread, not a worker or validator. A noncooperative
        provider can delay close indefinitely; this is not application shutdown policy.
        """
        with self._condition:
            self._closed = True
            for job_id in (*self._pending, *self._active):
                self.cancel(job_id)
            self._wake()
        self._dispatcher.join()
        for thread in self._threads:
            thread.join()
