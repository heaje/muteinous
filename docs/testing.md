# Testing policy — D160–D161 and D165

## Required pull-request validation

On the baseline **two-vCPU Windows runner**, target **five minutes or less of test execution**, excluding setup and packaging. Investigate overruns without weakening or skipping coverage. Enforce an independent **approximately ten-minute test-step timeout** that fails CI on timeout, test failure, or an incomplete run; a whole-job timeout is not a substitute. Report test-only elapsed time separately from setup, track slow tests with `pytest --durations`, and benchmark serial against modest parallelism when selecting or revisiting worker counts.

Run fast unit and plugin-contract tests plus representative **deterministic safety-critical integration tests** for implemented capabilities, covering as applicable:
- Source identity/freshness and stale-edit/configuration rejection.
- Required-edit completeness and selected-scope or deferred-manual-resolution refusals (D24/D143/D159).
- PCM sample/timing/fade fidelity outside intended edits.
- Shared installation ownership, backup, replacement/removal, and recovery safeguards.
- Result-bundle integrity, invalidation, and protected cleanup.

Use small generic synthetic fixtures and controlled inference fakes; required PR checks must not depend on heavy model downloads, GPUs, or real game installations. Do not claim skipped, timed-out, unrun, or unimplemented coverage as passed.

**Timeout failure-path verification:** A configured test-step timeout is not, by itself, proof that a timeout fails the required CI check. In a separately scheduled negative-control run, deliberately overrun the test step, verify that the step and job fail independently of the whole-job timeout, and record the run URL and diagnostic logs in the relevant Issue/PR. Keep this deliberately failing check out of routine PR validation. Until the negative-control evidence exists, report timeout behavior as configured but **not verified**; do not claim the acceptance criterion is met.

## Planned mandatory portability checks — D165

Once the CI phase is implemented, PRs must pass the D161 Windows comprehensive suite **and** lightweight, required Linux/macOS checks on explicit versioned runner images. Linux/macOS scope is Go Task and uv environment setup, locked installation, wheel/sdist build/import and selected portability-sensitive tests registered as `@pytest.mark.portable`. Keep portable tests alongside their functional tests; only mark cases whose real dependencies and behavior work on all supported CI platforms. A skipped or failing case must not be quietly hidden to satisfy the gate. Windows retains linting, typing and all required tests; Linux/macOS do not duplicate Windows lint/type checks.

The current Windows-only workflow and local Python 3.12 commands below remain the **existing implementation** until the relevant PRs are merged. D161's independently failing test-step timeout and five-minute test execution target remain mandatory; the intentional timeout-overrun negative-control is **deferred and unverified** pending a separately approved test (see the [Issue #2 deferral](https://github.com/heaje/muteinous/issues/2#issuecomment-7113969758)).

## Local validation commands

After [installing development dependencies with uv](development.md#local-python-bootstrap), run from the repository root on Windows (no virtual-environment activation required):

~~~powershell
.\.venv\Scripts\python.exe -m ruff check src scripts tests
.\.venv\Scripts\python.exe -m ruff format --check src scripts tests
.\.venv\Scripts\python.exe -m mypy src scripts tests
.\.venv\Scripts\python.exe scripts/check_decision_ids.py
.\.venv\Scripts\python.exe -m pytest -n logical --durations=10
~~~

`-n logical` uses the `pytest-xdist[psutil]` development dependency to select logical CPU workers; use `-n 2` locally if the machine has more cores than the tests need. The [PR workflow](../.github/workflows/pr.yml) also validates editable installation and an isolated wheel import, enforces the test-step timeout, and reports test-only timing. The [decision-ID checker](../scripts/check_decision_ids.py) rejects mismatched, duplicate, or malformed decision identifiers.

## Other validation tiers

Longer native-format, hardware, real-model, recovery/failure-injection, and end-to-end tests may run on main, scheduled, or release workflows when appropriate. **Release validation must cover all applicable supported behavior**; do not defer all safety coverage outside PR checks.

## Test layout

Use `tests/unit/`, `tests/contracts/`, `tests/integration/`, `tests/e2e/`, `tests/fixtures/`, and `tests/support/` as needed. Mirror production modules only when helpful.

## Introducing CI and early coverage

Bootstrap with meaningful package-install/import smoke tests, not fabricated safety tests. Add representative deterministic integration coverage with each new safety-critical capability. Keep CI failures and incomplete runs visible; changes to runtime budgets or required checks need explicit review under [D161](architecture/decisions.md).
