# Outstanding verification register

Evidence is tied to the cited revisions and runs (PR #43's tree-equivalent run matches the historical M1 baseline `a46bada`). This is the cross-task outstanding-verification register, not a diary; implementation authority remains the [decision log](../docs/architecture/decisions.md) and [coverage ledger](../docs/architecture/decision-coverage.md).

M1 implementation for Issues #16–22 is accepted; M1 verification remains outstanding as listed below.

## Deferred verification

Unchecked items remain outstanding, not passes or waivers. Linux/macOS CI executes only tests marked `pytest.mark.portable`; the authoritative scope is the markers in code and [testing policy](../docs/testing.md#mandatory-portability-checks--d165), not a frozen per-file inventory. Exact-main PR-event required checks did not run at `a46bada`; tree-equivalent PR CI and exact-main release preflights did run (links below).

### Open obligations

- **D166 residual acceptance:** perform refusal drills for existing draft/tag/inventory conflicts, failed-run recovery beyond deletion, and a human publication-gate walkthrough. The five exact-main release runs succeeded: [development](https://github.com/heaje/muteinous/actions/runs/45868348785), [alpha](https://github.com/heaje/muteinous/actions/runs/45868511441), [beta](https://github.com/heaje/muteinous/actions/runs/45868860528), [RC](https://github.com/heaje/muteinous/actions/runs/45869170684), [stable](https://github.com/heaje/muteinous/actions/runs/45869538943). Detailed draft/checksum/permission observations are executor-reported and were not independently re-inspected; nothing was published.
- **Dependabot (D164–D165):** observe scheduled version-update recurrence, grouped PR titles, and compatibility with bundled uv. Alerts and security updates are enabled and verified; this is observation only.
- **Architecture:** obtain maintainer confirmation on [Issue #5](https://github.com/heaje/muteinous/issues/5) that decisions match the approved original architecture discussion.
- **BLAKE3 benchmarks:** during M2 hashing work, add a genuine cold-cache benchmark mode and measure native Linux plus macOS; the macOS run requires an authorized throwaway runner job. WSL2 is not native Linux, and existing benchmark warms its fixture.
- **Frozen application:** before redistribution, audit actual dependency/binary graph and required notices; prior audit did not parse SBOM or inspect all crate notices/binary features.
- **Issue #20 retained branch:** keep `poc/native-formats-issue-20` (AST is M2's first native format). Complete locked Windows rerun, native Linux/macOS reproduction, package-exclusion check, and retained-branch baseline-hardware timing. No loader/install claim. Native Linux/macOS CI coverage remains portable-marked tests only.
- **M2 discovery (D132–D133/D137–D138):** [#51](https://github.com/heaje/muteinous/issues/51) / [PR #57](https://github.com/heaje/muteinous/pull/57): real Windows Steam/Epic/GOG launcher integration, native registry reads against actual keys, and real-installation probe coverage remain unverified. Tests must not modify the actual Windows Registry; the former temporary-key fixture has been replaced with simulated native API responses. [Historical CI run 45957715285](https://github.com/heaje/muteinous/actions/runs/45957715285) at `c184ff76f2271007a211f416ef190d868a3fe336` passed 589 Windows and 543 portable tests on each of Linux/macOS; see the PR for subsequent revision-specific checks. When appropriate Windows hardware and actual launcher installations are available, exercise generic metadata discovery, manual intake, stale/missing candidates, read-only source preservation and useful provisional probe results; measure responsiveness and coverage to revisit numeric budgets. Nonstandard locations (including Epic PCB mode), blocked OS calls and check/open races remain limitations; do not treat the probe as proof of format support or absence. No independent review or physical launcher validation is claimed; review/acceptance disposition remains in the PR. Keep real-game evidence local.
- **CI scope:** exact-main PR-event required checks were absent at baseline `a46bada`; tree-equivalent PR CI [45863237303](https://github.com/heaje/muteinous/actions/runs/45863237303) and exact-main release preflights [45868348785](https://github.com/heaje/muteinous/actions/runs/45868348785), [45868511441](https://github.com/heaje/muteinous/actions/runs/45868511441), [45868860528](https://github.com/heaje/muteinous/actions/runs/45868860528), [45869170684](https://github.com/heaje/muteinous/actions/runs/45869170684), [45869538943](https://github.com/heaje/muteinous/actions/runs/45869538943) exist. They do not establish unmarked Linux/macOS coverage.

### Historical process notes

PR #41 and #43 merged without pre-merge recorded independent review; post-merge summaries are recorded at [PR #41](https://github.com/heaje/muteinous/pull/41#issuecomment-7198951004), [PR #43](https://github.com/heaje/muteinous/pull/43#issuecomment-7198925281), and [PR #45](https://github.com/heaje/muteinous/pull/45#issuecomment-7199498788). This process deviation remains historical fact. #20 is branch-only synthetic feasibility, not production, loader, or installation evidence. Observation/hypothesis: editable-install metadata lagged the fresh build version; uv metadata caching was plausible but untested, and no change was made.

### Next

M2 sequencing is governed by the decision log and the maintainer-approved M2 planning decisions (decisions.md, 2026-11-26). Check prerequisites before starting dependent work.

### Cross-task risks

- Review, required CI, issue acceptance, milestone verification, and release readiness are separate gates; distinguish PR-event checks, exact-main preflights, and unrun platform scope.
- Preserve [initial-release scope](../docs/release-scope.md), source-validity preconditions, and explicit native compatibility evidence; synthetic success is not loader or installation safety.
