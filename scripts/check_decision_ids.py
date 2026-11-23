"""Check that the normative decision log and coverage ledger index the same IDs."""

from __future__ import annotations

import argparse
import re
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DECISIONS = ROOT / "docs/architecture/decisions.md"
COVERAGE = ROOT / "docs/architecture/decision-coverage.md"

# Count only real definitions and table rows. Detect malformed ID-like entries
# separately, including nonnumeric IDs and separators misplaced inside IDs.
DECISION_HEADING = re.compile(r"^#{2,6}[ \t]+D(0*[1-9]\d*)[ \t]+[—–-]", re.MULTILINE)
DECISION_CANDIDATE = re.compile(
    r"^#{2,6}[ \t]+D(?:[ \t_-]*\d|[A-Za-z]+[ \t]+[—–:-])",
    re.MULTILINE,
)
COVERAGE_ROW = re.compile(r"^\|[ \t]*D(0*[1-9]\d*)[ \t]*\|", re.MULTILINE)
COVERAGE_CANDIDATE = re.compile(
    r"^\|[ \t]*D(?!ecision[ \t]*\|)[^|\r\n]*\|", re.MULTILINE
)


def _ids(text: str, pattern: re.Pattern[str]) -> Counter[int]:
    return Counter(int(match) for match in pattern.findall(text))


def _format_ids(ids: set[int]) -> str:
    return ", ".join(f"D{number:02d}" for number in sorted(ids))


def _malformed_entries(
    text: str, candidate: re.Pattern[str], valid: re.Pattern[str], label: str
) -> list[str]:
    return [
        f"{label} at line {number}: {line}"
        for number, line in enumerate(text.splitlines(), 1)
        if candidate.match(line) and not valid.match(line)
    ]


def validate(decisions: str, coverage: str) -> list[str]:
    """Return all ID integrity failures, including malformed or duplicate entries."""
    log_ids = _ids(decisions, DECISION_HEADING)
    ledger_ids = _ids(coverage, COVERAGE_ROW)
    errors = _malformed_entries(
        decisions, DECISION_CANDIDATE, DECISION_HEADING, "Malformed decision heading"
    )
    errors.extend(
        _malformed_entries(
            coverage, COVERAGE_CANDIDATE, COVERAGE_ROW, "Malformed coverage row"
        )
    )
    if not log_ids:
        errors.append("No numbered decision headings found in the decision log")
    if not ledger_ids:
        errors.append("No numbered decision rows found in the coverage ledger")
    for label, counts in (("Decision log", log_ids), ("Coverage ledger", ledger_ids)):
        duplicates = {number for number, count in counts.items() if count > 1}
        if duplicates:
            errors.append(f"{label} has duplicate IDs: {_format_ids(duplicates)}")
    missing = set(log_ids) - set(ledger_ids)
    extra = set(ledger_ids) - set(log_ids)
    if missing:
        errors.append(f"Missing coverage rows: {_format_ids(missing)}")
    if extra:
        errors.append(f"Coverage rows without decisions: {_format_ids(extra)}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--decisions", type=Path, default=DECISIONS)
    parser.add_argument("--coverage", type=Path, default=COVERAGE)
    args = parser.parse_args()
    try:
        decisions = args.decisions.read_text(encoding="utf-8")
        coverage = args.coverage.read_text(encoding="utf-8")
    except OSError as exc:
        print(f"Decision-ID check failed: {exc}")
        return 1

    errors = validate(decisions, coverage)
    for error in errors:
        print(f"Decision-ID check failed: {error}")
    if errors:
        return 1
    print(
        "Decision-ID check passed: decision headings and coverage rows match uniquely"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
