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

The current required workflow is Windows-only; the Taskfile and portable marker are ready for the separate CI phase. D161's independently failing test-step timeout and five-minute test execution target remain mandatory; the intentional timeout-overrun negative-control is **deferred and unverified** pending a separately approved test (see the [Issue #2 deferral](https://github.com/heaje/muteinous/issues/2#issuecomment-7113969758)).

## Local validation commands

After [explicit setup](development.md#local-python-bootstrap), run from the repository root on Windows, Linux or macOS (no activation required):

~~~shell
task check
~~~

For focused checks use `task lint`, `task format-check`, `task typecheck`, `task decisions`, `task test`, `task build`, or `task version-preview`. Use `task test -- -m portable` for portability-sensitive tests. The default `-n logical` uses pytest-xdist with psutil to select logical CPU workers; override with `task test -- -n 2` for a modest local worker count. The [Windows PR workflow](../.github/workflows/pr.yml) validates the editable import, wheel/sdist build and isolated wheel import, commit range and PR title, and runs individual checks with separate test-only timing and an independent ten-minute test-step timeout. The [decision-ID checker](../scripts/check_decision_ids.py) rejects mismatched, duplicate or malformed decision identifiers. Versioning tests use isolated temporary Git repositories and the real configured providers.

## Other validation tiers

Longer native-format, hardware, real-model, recovery/failure-injection, and end-to-end tests may run on main, scheduled, or release workflows when appropriate. **Release validation must cover all applicable supported behavior**; do not defer all safety coverage outside PR checks.

## Test layout

Use `tests/unit/`, `tests/contracts/`, `tests/integration/`, `tests/e2e/`, `tests/fixtures/`, and `tests/support/` as needed. Mirror production modules only when helpful.

## Introducing CI and early coverage

Bootstrap with meaningful package-install/import smoke tests, not fabricated safety tests. Add representative deterministic integration coverage with each new safety-critical capability. Keep CI failures and incomplete runs visible; changes to runtime budgets or required checks need explicit review under [D161](architecture/decisions.md).
