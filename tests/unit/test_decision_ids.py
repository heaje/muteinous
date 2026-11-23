"""Negative controls for the decision-log/coverage-ledger consistency gate."""

import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts/check_decision_ids.py"
LOG = "### D01 — Original\n### D02 — Second\n"
LEDGER = "| Decision | Phase |\n| --- | --- |\n| D01 | Initial |\n| D02 | Initial |\n"


def run_checker(
    tmp_path: Path, log: str, ledger: str
) -> subprocess.CompletedProcess[str]:
    decisions = tmp_path / "decisions.md"
    coverage = tmp_path / "decision-coverage.md"
    decisions.write_text(log, encoding="utf-8")
    coverage.write_text(ledger, encoding="utf-8")
    return subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--decisions",
            str(decisions),
            "--coverage",
            str(coverage),
        ],
        capture_output=True,
        text=True,
        check=False,
    )


def test_matching_unique_ids_pass(tmp_path: Path) -> None:
    result = run_checker(tmp_path, LOG, LEDGER)
    assert result.returncode == 0, result.stdout


def test_missing_row_fails(tmp_path: Path) -> None:
    result = run_checker(tmp_path, LOG, LEDGER.replace("| D02 | Initial |\n", ""))
    assert result.returncode != 0
    assert "Missing coverage rows: D02" in result.stdout


def test_extra_row_fails(tmp_path: Path) -> None:
    result = run_checker(tmp_path, LOG, LEDGER + "| D03 | Initial |\n")
    assert result.returncode != 0
    assert "Coverage rows without decisions: D03" in result.stdout


def test_duplicate_log_heading_fails(tmp_path: Path) -> None:
    result = run_checker(tmp_path, LOG + "## D1 — Duplicate\n", LEDGER)
    assert result.returncode != 0
    assert "Decision log has duplicate IDs: D01" in result.stdout


def test_duplicate_ledger_row_fails(tmp_path: Path) -> None:
    result = run_checker(tmp_path, LOG, LEDGER + "| D01 | Initial |\n")
    assert result.returncode != 0
    assert "Coverage ledger has duplicate IDs: D01" in result.stdout


def test_no_decisions_never_passes(tmp_path: Path) -> None:
    result = run_checker(tmp_path, "# Empty\n", "| Decision | Phase |\n")
    assert result.returncode != 0
    assert "No numbered decision headings" in result.stdout


def test_malformed_heading_and_missing_row_fails(tmp_path: Path) -> None:
    log = LOG.replace("### D02 — Second", "## D02: Second")
    ledger = LEDGER.replace("| D02 | Initial |\n", "")
    result = run_checker(tmp_path, log, ledger)
    assert result.returncode != 0
    assert "Malformed decision heading at line 2" in result.stdout


def test_malformed_duplicate_heading_fails(tmp_path: Path) -> None:
    result = run_checker(tmp_path, LOG + "## D01: Duplicate\n", LEDGER)
    assert result.returncode != 0
    assert "Malformed decision heading at line 3" in result.stdout


def test_malformed_ledger_row_fails(tmp_path: Path) -> None:
    result = run_checker(tmp_path, LOG, LEDGER.replace("| D02 |", "| D02: |"))
    assert result.returncode != 0
    assert "Malformed coverage row at line 4" in result.stdout


def test_incidental_prose_id_is_not_a_definition(tmp_path: Path) -> None:
    result = run_checker(tmp_path, LOG + "D01 is also referenced in prose.\n", LEDGER)
    assert result.returncode == 0, result.stdout


def test_nonnumeric_decision_heading_fails(tmp_path: Path) -> None:
    result = run_checker(tmp_path, LOG + "### DXX — Invalid\n", LEDGER)
    assert result.returncode != 0
    assert "Malformed decision heading at line 3" in result.stdout


def test_nonnumeric_ledger_row_fails(tmp_path: Path) -> None:
    result = run_checker(tmp_path, LOG, LEDGER + "| DXX | Initial |\n")
    assert result.returncode != 0
    assert "Malformed coverage row at line 5" in result.stdout


def test_spaced_decision_id_fails(tmp_path: Path) -> None:
    result = run_checker(tmp_path, LOG, LEDGER + "| D 03 | Initial |\n")
    assert result.returncode != 0
    assert "Malformed coverage row at line 5" in result.stdout


@pytest.mark.parametrize("malformed_id", ["D-02", "DQ", "Dabc"])
def test_matching_malformed_id_pairs_fail(tmp_path: Path, malformed_id: str) -> None:
    """Matching malformed IDs must not disappear from both ID sets."""
    log = LOG.replace("D02", malformed_id)
    ledger = LEDGER.replace("D02", malformed_id)
    result = run_checker(tmp_path, log, ledger)
    assert result.returncode != 0
    assert "Malformed decision heading at line 2" in result.stdout
    assert "Malformed coverage row at line 4" in result.stdout
