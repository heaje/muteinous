"""One real xdist run verifies registration and collection-skip delivery."""

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.portable
def test_required_policy_fails_on_worker_collection_skip(tmp_path: Path) -> None:
    policy = Path(__file__).resolve().parents[1] / "conftest.py"
    shutil.copyfile(policy, tmp_path / "conftest.py")
    (tmp_path / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")
    (tmp_path / "test_skipped.py").write_text(
        "import pytest\n"
        "pytest.importorskip('module_missing_for_required_policy_test')\n",
        encoding="utf-8",
    )
    # A passing item ensures pytest would otherwise exit successfully.
    (tmp_path / "test_passing.py").write_text(
        "def test_passes():\n    pass\n", encoding="utf-8"
    )
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
    result = subprocess.run(
        [sys.executable, "-I", "-m", "pytest", "-q", "-n", "2"],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        check=False,
        text=True,
    )
    output = result.stdout + result.stderr
    assert result.returncode == pytest.ExitCode.TESTS_FAILED, output
    assert "Required test suite contains skipped tests" in output
    assert "test_skipped.py" in output
