"""Reusable job-queue fakes, factories and thread-test helpers."""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Callable
from threading import Event, current_thread

from muteinous.infrastructure.jobs.queue import JobContext, JobPlan


def plan(*resources: str, source: str = "v1") -> JobPlan:
    return JobPlan(
        "fake",
        "fixed",
        resources,
        json.dumps({"source": source}, separators=(",", ":")),
    )


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


class CountingFakeClock(FakeClock):
    def __init__(self) -> None:
        super().__init__()
        self._lock = threading.Lock()
        self._dispatcher_calls = 0

    def __call__(self) -> float:
        if current_thread().name == "muteinous-jobs":
            with self._lock:
                self._dispatcher_calls += 1
        return super().__call__()

    @property
    def dispatcher_calls(self) -> int:
        with self._lock:
            return self._dispatcher_calls


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


def capture_thread_exceptions(errors: list[BaseException]) -> Callable[[object], None]:
    def capture(args: object) -> None:
        error = getattr(args, "exc_value", None)
        if isinstance(error, BaseException):
            errors.append(error)

    return capture
