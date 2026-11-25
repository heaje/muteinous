"""Enforce the required pytest execution policy."""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).parent / "support"))


class _RequiredTestPolicy:
    def __init__(self, config: pytest.Config) -> None:
        self._config = config
        self._is_worker = hasattr(config, "workerinput")
        self._skipped_test_ids: set[str] = set()
        self._session_started_at: float | None = None
        self._session_duration = 0.0

    def _record_skip(self, report: Any) -> None:
        if (
            getattr(report, "outcome", None) == "skipped"
            and getattr(report, "wasxfail", None) is None
        ):
            self._skipped_test_ids.add(str(getattr(report, "nodeid", "<unknown>")))

    def pytest_collectreport(self, report: Any) -> None:
        self._record_skip(report)

    def pytest_runtest_logreport(self, report: Any) -> None:
        self._record_skip(report)

    def pytest_sessionstart(self, session: pytest.Session) -> None:
        if not self._is_worker:
            self._session_started_at = time.perf_counter()

    def pytest_sessionfinish(self, session: pytest.Session, exitstatus: int) -> None:
        if self._is_worker:
            workeroutput = getattr(self._config, "workeroutput", None)
            if workeroutput is not None:
                workeroutput["required_test_skips"] = sorted(self._skipped_test_ids)
            return

        if self._session_started_at is not None:
            self._session_duration = time.perf_counter() - self._session_started_at
        if self._skipped_test_ids and session.exitstatus == pytest.ExitCode.OK:
            session.exitstatus = pytest.ExitCode.TESTS_FAILED

    def pytest_testnodedown(self, node: Any, error: Any) -> None:
        workeroutput = getattr(node, "workeroutput", {})
        self._skipped_test_ids.update(workeroutput.get("required_test_skips", []))

    def pytest_terminal_summary(
        self, terminalreporter: Any, exitstatus: int, config: pytest.Config
    ) -> None:
        if self._is_worker:
            return

        terminalreporter.write_sep("=", "Required pytest session time")
        terminalreporter.write_line(
            f"pytest session time: {self._session_duration:.3f} seconds"
        )

        if self._skipped_test_ids:
            terminalreporter.write_sep("=", "Required test skips are failures")
            terminalreporter.write_line(
                "Required test suite contains skipped tests; this is a failure:"
            )
            for test_id in sorted(self._skipped_test_ids):
                terminalreporter.write_line(f"  {test_id}")

        summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
        if summary_path:
            with Path(summary_path).open("a", encoding="utf-8") as summary:
                summary.write(
                    f"Pytest session time: {self._session_duration:.3f} seconds\n"
                )


def pytest_configure(config: pytest.Config) -> None:
    config.pluginmanager.register(
        _RequiredTestPolicy(config), "muteinous-required-test-policy"
    )
