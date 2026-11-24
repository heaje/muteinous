# Testing policy — D160–D161 and D165

## Required pull-request validation

On the baseline **two-vCPU Windows runner**, target **five minutes or less of pytest session time**, excluding Task readiness checks, process startup/teardown, and packaging/setup outside pytest. The required-test plugin reports this session duration in the terminal and GitHub step summary. The workflow separately reports test-step wall time, which includes Task readiness checks and process overhead. Investigate overruns without weakening or skipping coverage. Enforce an independent **approximately ten-minute test-step timeout** that fails CI on timeout, test failure, or an incomplete run; a whole-job timeout is not a substitute. Track slow tests with `pytest --durations`, and benchmark serial against modest parallelism when selecting or revisiting worker counts.

Run fast unit and plugin-contract tests plus representative **deterministic safety-critical integration tests** for implemented capabilities, covering as applicable:
- Source identity/freshness and stale-edit/configuration rejection.
- Required-edit completeness and selected-scope or deferred-manual-resolution refusals (D24/D143/D159).
- PCM sample/timing/fade fidelity outside intended edits.
- Shared installation ownership, backup, replacement/removal, and recovery safeguards.
- Result-bundle integrity, invalidation, and protected cleanup.

Use small generic synthetic fixtures and controlled inference fakes; required PR checks must not depend on heavy model downloads, GPUs, or real game installations. The root [`tests/conftest.py`](../tests/conftest.py) guard fails the pytest session and lists test IDs if any test is skipped, including runtime skips and collection-time skips such as `pytest.importorskip`; xdist worker skips are collected on the controller. It only changes an otherwise-successful exit status, preserving existing nonzero statuses. Expected xfails are a separate pytest outcome and are not treated as skips; this project does not add xfail or strict-xfail policy. Empty selections retain pytest's nonzero exit status. Do not claim skipped, timed-out, unrun, or unimplemented coverage as passed.

**Timeout failure-path verification:** A configured test-step timeout is not, by itself, proof that a timeout fails the required CI check. In a separately scheduled negative-control run, deliberately overrun the test step, verify that the step and job fail independently of the whole-job timeout, and record the run URL and diagnostic logs in the relevant Issue/PR. Keep this deliberately failing check out of routine PR validation. Until the negative-control evidence exists, report timeout behavior as configured but **not verified**; do not claim the acceptance criterion is met.

## Mandatory portability checks — D165

The [PR workflow](../.github/workflows/pr.yml) runs the D161 Windows comprehensive suite **and** lightweight Linux/macOS checks on explicit versioned runner images. All three named checks must be required in repository settings. Linux/macOS scope is Go Task and uv environment setup, locked installation, wheel/sdist build/import and selected portability-sensitive tests registered as `@pytest.mark.portable`. Keep portable tests alongside their functional tests; only mark cases whose real dependencies and behavior work on all supported CI platforms. A skipped or failing case must not be quietly hidden to satisfy the gate. Windows retains linting, typing and all required tests; Linux/macOS do not duplicate Windows lint/type checks.

The stable check names and runner labels are:

| Required check | Runner | Scope |
| --- | --- | --- |
| Windows package and tests | `windows-2025` | Full suite, lint, format, strict typing, decision IDs, commit range and PR title, version preview, packaging and imports |
| Linux portability | `ubuntu-26.04` | Locked setup, packaging and imports, portable tests |
| macOS portability | `macos-26` | Locked setup, packaging and imports, portable tests |

The portable selection currently covers installed-distribution import, real Git/Commitizen/setuptools-scm/uv versioning, and isolated pytest-policy regression tests in [test_package_import.py](../tests/unit/test_package_import.py), [test_versioning.py](../tests/unit/test_versioning.py), and [test_pytest_policy.py](../tests/unit/test_pytest_policy.py). These exercise platform-sensitive paths, subprocesses, metadata and package rebuilds using the locked tools and temporary Git repositories; the policy tests also verify serial and xdist skip handling in isolated pytest runs. The decision-ID checker tests remain in the comprehensive Windows suite because they test documentation parsing, not a portability-sensitive contract. Reevaluate markers as dependencies and functionality evolve. The portable jobs use two workers to avoid unnecessary worker startup; Windows retains `-n logical` and runs every test. This is tooling portability, not verified non-Windows application compatibility.

 D161's independently failing test-step timeout and five-minute test execution target remain mandatory; the intentional timeout-overrun negative-control is **deferred and unverified** pending a separately approved test (see the [Issue #2 deferral](https://github.com/heaje/muteinous/issues/2#issuecomment-7113969758)).

## Local validation commands

After [explicit setup](development.md#local-python-bootstrap), run from the repository root on Windows, Linux or macOS (no activation required):

~~~shell
task check
~~~

For focused checks use `task lint`, `task format-check`, `task typecheck`, `task decisions`, `task test`, `task build`, or `task version-preview`. Use `task test -- -m portable` for portability-sensitive tests. The default `-n logical` uses pytest-xdist with psutil to select logical CPU workers; override with `task test -- -n 2` for a modest local worker count. In Windows PowerShell, use `task.cmd test -- -m portable -n 2` when forwarding pytest options; the npm-provided `task.ps1` shim can pass `-m` to Task's own flag parser instead. The Windows job in the [PR workflow](../.github/workflows/pr.yml) validates the editable import, wheel/sdist build and isolated wheel import, commit range and PR title, and runs individual checks with pytest session timing, separately labeled test-step wall time, and an independent ten-minute test-step timeout. The [decision-ID checker](../scripts/check_decision_ids.py) rejects mismatched, duplicate or malformed decision identifiers. Versioning tests use isolated temporary Git repositories and the real configured providers.

## Other validation tiers

Longer native-format, hardware, real-model, recovery/failure-injection, and end-to-end tests may run on main, scheduled, or release workflows when appropriate. **Release validation must cover all applicable supported behavior**; do not defer all safety coverage outside PR checks.

## Test layout

Use `tests/unit/`, `tests/contracts/`, `tests/integration/`, `tests/e2e/`, `tests/fixtures/`, and `tests/support/` as needed. Mirror production modules only when helpful.

## Introducing CI and early coverage

Bootstrap with meaningful package-install/import smoke tests, not fabricated safety tests. Add representative deterministic integration coverage with each new safety-critical capability. Keep CI failures and incomplete runs visible; changes to runtime budgets or required checks need explicit review under [D161](architecture/decisions.md).
