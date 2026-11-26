"""Unit tests of our required-test policy, without starting pytest sessions."""

from pathlib import Path
from types import SimpleNamespace
from typing import cast
from unittest.mock import Mock

import pytest

from tests.conftest import _RequiredTestPolicy

pytestmark = pytest.mark.portable


def config(**attributes: object) -> pytest.Config:
    return cast(pytest.Config, SimpleNamespace(**attributes))


def session(status: pytest.ExitCode) -> pytest.Session:
    return cast(pytest.Session, SimpleNamespace(exitstatus=status))


@pytest.mark.parametrize(
    "status",
    [
        pytest.ExitCode.OK,
        pytest.ExitCode.TESTS_FAILED,
        pytest.ExitCode.INTERRUPTED,
        pytest.ExitCode.NO_TESTS_COLLECTED,
    ],
)
def test_required_skip_changes_only_success(status: pytest.ExitCode) -> None:
    policy = _RequiredTestPolicy(config())
    current = session(status)
    policy.pytest_runtest_logreport(
        SimpleNamespace(outcome="skipped", nodeid="test_runtime")
    )
    policy.pytest_sessionfinish(current, status)
    expected = pytest.ExitCode.TESTS_FAILED if status == pytest.ExitCode.OK else status
    assert current.exitstatus == expected


def test_worker_collection_skips_reach_controller(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    worker_config = config(workerinput={}, workeroutput={})
    worker = _RequiredTestPolicy(worker_config)
    worker_session = session(pytest.ExitCode.OK)
    worker.pytest_collectreport(
        SimpleNamespace(outcome="skipped", nodeid="test_collection.py")
    )
    worker.pytest_sessionfinish(worker_session, pytest.ExitCode.OK)
    assert worker_session.exitstatus == pytest.ExitCode.OK
    controller_config = config()
    controller = _RequiredTestPolicy(controller_config)
    controller.pytest_testnodedown(
        SimpleNamespace(workeroutput=getattr(worker_config, "workeroutput")), None
    )
    current = session(pytest.ExitCode.OK)
    controller.pytest_sessionfinish(current, pytest.ExitCode.OK)
    assert current.exitstatus == pytest.ExitCode.TESTS_FAILED
    reporter = Mock()
    controller.pytest_terminal_summary(reporter, current.exitstatus, controller_config)
    reporter.write_line.assert_any_call("  test_collection.py")


def test_expected_xfail_and_pass_do_not_fail_policy() -> None:
    policy = _RequiredTestPolicy(config())
    current = session(pytest.ExitCode.OK)
    policy.pytest_runtest_logreport(
        SimpleNamespace(outcome="skipped", nodeid="expected", wasxfail="reason")
    )
    policy.pytest_runtest_logreport(SimpleNamespace(outcome="passed", nodeid="pass"))
    policy.pytest_sessionfinish(current, pytest.ExitCode.OK)
    assert current.exitstatus == pytest.ExitCode.OK


def test_session_time_is_reported(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    ticks = iter([10.0, 12.5])
    monkeypatch.setattr(
        "tests.conftest.time", SimpleNamespace(perf_counter=lambda: next(ticks))
    )
    controller_config = config()
    policy = _RequiredTestPolicy(controller_config)
    current = session(pytest.ExitCode.OK)
    policy.pytest_sessionstart(current)
    policy.pytest_sessionfinish(current, pytest.ExitCode.OK)
    reporter = Mock()
    policy.pytest_terminal_summary(reporter, current.exitstatus, controller_config)
    reporter.write_line.assert_any_call("pytest session time: 2.500 seconds")
    assert summary.read_text("utf-8") == "Pytest session time: 2.500 seconds\n"
