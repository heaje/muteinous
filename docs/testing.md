# Test strategy and CI runtime (D160–D161)

## Required pull-request checks

On a baseline **two-vCPU Windows GitHub Actions runner**, target **at most five minutes of test execution** for the required PR suite. Enforce an approximately **ten-minute hard timeout on test execution itself**; a job-level timeout alone does not meet this requirement. A test timeout must fail the check, not silently skip or truncate it. Track slow tests (e.g. pytest `--durations`) and benchmark serial versus two workers.

The PR suite includes fast unit and contract tests plus deterministic, safety-critical integration tests covering:

- Source validity and stale-result rejection.
- Required-edit completeness and conservative scope failure.
- PCM fidelity, timing, and safe preview behavior.
- Installation ownership, verified originals, backups and recovery.
- Storage/cache integrity and invalidation.

Add these checks as the corresponding implementation arrives. Never assert that the scaffold already tests unimplemented behavior.

## Other test tiers

Longer real-model, hardware, native-tool, native-format and end-to-end suites may run separately as justified. They do not replace required deterministic safety checks. Use synthetic, small, deterministic fixtures and avoid downloading heavy models in required PR checks.

## Organization

`tests/unit/`, `tests/contracts/`, `tests/integration/`, `tests/e2e/`, `tests/fixtures/`, and `tests/support/`. Mirror code structure within tiers only when useful. Changes to runtime budgets, test tiering, or coverage must be explicit and reviewed; do not meet the budget by hiding lost coverage.

See the complete D161 text in [decisions.md](architecture/decisions.md).
