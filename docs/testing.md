# Test architecture and runtime policy — D160–D161

## Required pull-request validation

On a baseline **two-vCPU Windows GitHub Actions runner**, target **at most five minutes of test execution** for the required PR suite. This excludes provisioning, dependency setup and packaging. Five minutes is a target/investigation threshold, **not** permission to cut test coverage.

Enforce a **hard, approximately ten-minute timeout around the test-execution process itself**. The check **must fail** on timeout or incomplete tests; a workflow job timeout alone includes setup and does not satisfy D161. Clearly separate setup duration from actual test duration and preserve readable failure output. Benchmark a serial run against modest parallelism (e.g. two workers) on the baseline runner and track slow tests with `pytest --durations`.

Every PR should run fast unit and plugin-contract tests plus deterministic **representative safety-critical integration coverage** as implemented, including:
- Original source identity/freshness, stale scan/edit rejection and changed configuration.
- Required-edit completeness, D24/D143 selected-scope refusal and D159 deferred-manual-resolution blockers.
- Actual PCM sample/timing/fades and fidelity preservation outside edit regions.
- Shared installer ownership, backup, safe replacement/removal, recovery and update/running-game protection.
- Result bundle publication, integrity, invalidation and protected cleanup.

Use small generic **synthetic** fixtures and controlled inference fakes. Required checks must not silently download heavy speech models or rely on GPU/real game installations. **Do not report skipped, timed-out or unrun required coverage as passed.**

## Other validation tiers

Hardware/model downloads, native-format/codec tools, real inference, larger failures and end-to-end tests may be separately provisioned and gated on main, schedule or release candidates as appropriate. **Complete release validation** must exercise all applicable supported behavior even if it exceeds the PR runtime budget. Do not defer *all* safety coverage to longer suites.

## Test layout

Tests live in `tests/unit/`, `tests/contracts/`, `tests/integration/`, `tests/e2e/`, plus `tests/fixtures/` and `tests/support/`. Mirror code ownership where it aids discovery, not through compulsory one-test-per-file mirroring.

## Introducing CI and early coverage

When establishing packaging and Windows CI, begin with a minimal import/smoke test; do **not** fabricate safety-test coverage before functionality exists. Validate installation, test discovery, and appropriate lint/type checks. Use a Windows two-vCPU baseline runner and enforce an independently failing ~600-second test-process limit; report test-only execution time, slow tests, and failed/incomplete runs separately from setup. Required checks must not implicitly download speech models.

Add representative deterministic safety integration checks alongside each implementation slice that introduces a relevant capability. Never claim a not-yet-implemented safeguard is tested. Do not silently increase budgets, re-tier, or skip tests to hide a regression; a justified change requires review and evidence. Full normative policy: [D161](architecture/decisions.md).
