"""Regression tests for the required pytest execution policy."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.portable

_POLICY = Path(__file__).resolve().parents[1] / "conftest.py"


def run_inner_pytest(
    project: Path,
    source: str,
    *,
    workers: int | None = None,
    portable_only: bool = False,
    summary_path: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    project.mkdir()
    shutil.copyfile(_POLICY, project / "conftest.py")
    (project / "pytest.ini").write_text(
        "[pytest]\n"
        "addopts = -ra --strict-markers --strict-config\n"
        "markers = portable: portable inner test\n",
        encoding="utf-8",
    )
    (project / "test_inner.py").write_text(source, encoding="utf-8")

    command = [
        sys.executable,
        "-I",
        "-m",
        "pytest",
        "-q",
        "-c",
        str(project / "pytest.ini"),
    ]
    if workers is not None:
        command.extend(["-n", str(workers)])
    if portable_only:
        command.extend(["-m", "portable"])
    command.append(str(project / "test_inner.py"))

    env = os.environ.copy()
    for name in (
        "GITHUB_STEP_SUMMARY",
        "PYTEST_ADDOPTS",
        "PYTEST_PLUGINS",
        "PYTEST_DISABLE_PLUGIN_AUTOLOAD",
        "PYTEST_XDIST_AUTO_NUM_WORKERS",
        "PYTEST_CURRENT_TEST",
    ):
        env.pop(name, None)
    if summary_path is not None:
        env["GITHUB_STEP_SUMMARY"] = str(summary_path)
    return subprocess.run(
        command,
        cwd=project,
        env=env,
        capture_output=True,
        check=False,
        text=True,
    )


@pytest.mark.parametrize("workers", [None, 2], ids=["serial", "xdist"])
@pytest.mark.parametrize("skip_kind", ["runtime", "importorskip"])
def test_skipped_tests_fail(
    tmp_path: Path, workers: int | None, skip_kind: str
) -> None:
    if skip_kind == "runtime":
        source = "import pytest\n\ndef test_skipped():\n    pytest.skip('deliberate')\n"
    else:
        source = (
            "import pytest\n"
            "pytest.importorskip('module_that_does_not_exist_for_this_test')\n"
            "\n"
            "def test_unreachable():\n"
            "    pass\n"
        )

    result = run_inner_pytest(tmp_path / "project", source, workers=workers)
    output = result.stdout + result.stderr

    assert result.returncode != 0, output
    assert "Required test suite contains skipped tests" in output
    assert "test_inner.py" in output


def test_all_passing_tests_still_pass_and_report_session_time(tmp_path: Path) -> None:
    summary_path = tmp_path / "step-summary.md"
    result = run_inner_pytest(
        tmp_path / "project",
        "def test_passes():\n    assert True\n",
        summary_path=summary_path,
    )
    output = result.stdout + result.stderr

    assert result.returncode == 0, output
    assert "pytest session time:" in output
    assert "Pytest session time:" in summary_path.read_text(encoding="utf-8")


def test_inner_pytest_ignores_inherited_ci_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    summary_path = tmp_path / "outer-step-summary.md"
    summary_path.write_text("", encoding="utf-8")
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary_path))
    monkeypatch.setenv("PYTEST_ADDOPTS", "-k no_inner_tests_match")
    monkeypatch.setenv("PYTEST_PLUGINS", "plugin_that_does_not_exist")
    monkeypatch.setenv("PYTEST_DISABLE_PLUGIN_AUTOLOAD", "1")
    monkeypatch.setenv("PYTEST_XDIST_AUTO_NUM_WORKERS", "not-a-worker-count")

    result = run_inner_pytest(
        tmp_path / "project",
        "def test_passes():\n    assert True\n",
        workers=2,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert summary_path.read_text(encoding="utf-8") == ""


def test_empty_portable_selection_keeps_pytest_exit_code_5(tmp_path: Path) -> None:
    result = run_inner_pytest(
        tmp_path / "project",
        "def test_not_portable():\n    pass\n",
        portable_only=True,
    )

    assert result.returncode == 5, result.stdout + result.stderr
