# Architecture decision implementation and verification coverage

**Source:** [architecture decision log](decisions.md). This is an implementation-and-verification evidence ledger, **not** a second copy of the requirements or a task board. The rows below reflect the decisions recorded when this ledger was created; whenever the decision log changes, reconcile the row set and affected statuses against the current source. Documentation alone is **not implementation or verification**.

**Phase:** `Initial / as applicable` covers the applicable release and its mandatory safety constraints **when their capability/path applies**, not every optional/conditional mechanism. `Later` denotes an approved deferral and `Superseded` a historical decision. Phase labels are tracking metadata; validate them against the [current scope](../release-scope.md) and decision log rather than treating these initial labels as permanent policy. A qualified label marks a decision whose safety/refusal obligations apply now while its user-approval or override features are deferred under D159.

**Implementation status:** `No implementation evidence`, `In progress`, `Implemented / unverified`, `Verified`, `Deferred` or `Superseded`. Change a row only with linked Issue/PR and relevant test/inspection proof; do not treat PR merge alone as safety verification. For multi-requirement decisions, retain clear partial evidence rather than declaring them wholly verified.

**Update ownership:** Each implementation PR records affected D-numbers and evidence in its own description. The merging agent/coordinator reconciles this shared table from accepted evidence at merge time or promptly afterward, rather than having concurrent feature branches edit the same rows.

| Decision | Phase | Implementation status | Issue / PR evidence | Verification evidence |
| --- | --- | --- | --- | --- |
| D01 | Initial / as applicable | No implementation evidence | — | — |
| D02 | Initial / as applicable | No implementation evidence | — | — |
| D03 | Initial / as applicable | No implementation evidence | — | — |
| D04 | Initial / as applicable | No implementation evidence | — | — |
| D05 | Initial / as applicable | No implementation evidence | — | — |
| D06 | Initial / as applicable | No implementation evidence | — | — |
| D07 | Initial / as applicable | No implementation evidence | — | — |
| D08 | Initial / as applicable | No implementation evidence | — | — |
| D09 | Initial / as applicable | No implementation evidence | — | — |
| D10 | Initial / as applicable | No implementation evidence | — | — |
| D11 | Initial / as applicable | No implementation evidence | — | — |
| D12 | Initial / as applicable | No implementation evidence | — | — |
| D13 | Initial / as applicable | No implementation evidence | — | — |
| D14 | Initial / as applicable | No implementation evidence | — | — |
| D15 | Initial / as applicable | No implementation evidence | — | — |
| D16 | Initial / as applicable | No implementation evidence | — | — |
| D17 | Initial / as applicable | No implementation evidence | — | — |
| D18 | Initial / as applicable | No implementation evidence | — | — |
| D19 | Initial / as applicable | No implementation evidence | — | — |
| D20 | Initial / as applicable | No implementation evidence | — | — |
| D21 | Initial / as applicable | No implementation evidence | — | — |
| D22 | Initial / as applicable | No implementation evidence | — | — |
| D23 | Initial / as applicable | No implementation evidence | — | — |
| D24 | Initial / as applicable | No implementation evidence | — | — |
| D25 | Initial / as applicable | No implementation evidence | — | — |
| D26 | Initial / as applicable | No implementation evidence | — | — |
| D27 | Initial / as applicable | No implementation evidence | — | — |
| D28 | Initial / as applicable | No implementation evidence | — | — |
| D29 | Initial / as applicable | No implementation evidence | — | — |
| D30 | Initial / as applicable | No implementation evidence | — | — |
| D31 | Initial / as applicable | No implementation evidence | — | — |
| D32 | Initial / as applicable | No implementation evidence | — | — |
| D33 | Initial / as applicable | No implementation evidence | — | — |
| D34 | Initial / as applicable | No implementation evidence | — | — |
| D35 | Initial / as applicable | No implementation evidence | — | — |
| D36 | Initial / as applicable | No implementation evidence | — | — |
| D37 | Initial / as applicable | No implementation evidence | — | — |
| D38 | Initial / as applicable | No implementation evidence | — | — |
| D39 | Initial / as applicable | No implementation evidence | — | — |
| D40 | Initial / as applicable | No implementation evidence | — | — |
| D41 | Initial / as applicable | No implementation evidence | — | — |
| D42 | Initial / as applicable; per-match choices deferred (D159) | No implementation evidence | — | — |
| D43 | Initial / as applicable | No implementation evidence | — | — |
| D44 | Initial / as applicable | No implementation evidence | — | — |
| D45 | Initial / as applicable | No implementation evidence | — | — |
| D46 | Initial / as applicable | No implementation evidence | — | — |
| D47 | Initial / as applicable | No implementation evidence | — | — |
| D48 | Initial / as applicable | No implementation evidence | — | — |
| D49 | Initial / as applicable | No implementation evidence | — | — |
| D50 | Initial / as applicable | No implementation evidence | — | — |
| D51 | Initial / as applicable | No implementation evidence | — | — |
| D52 | Initial / as applicable | No implementation evidence | — | — |
| D53 | Initial / as applicable | No implementation evidence | — | — |
| D54 | Initial / as applicable | No implementation evidence | — | — |
| D55 | Initial / as applicable | No implementation evidence | — | — |
| D56 | Initial / as applicable | No implementation evidence | — | — |
| D57 | Initial / as applicable | No implementation evidence | — | — |
| D58 | Initial / as applicable | No implementation evidence | — | — |
| D59 | Initial / as applicable | No implementation evidence | — | — |
| D60 | Initial / as applicable | No implementation evidence | — | — |
| D61 | Initial / as applicable | No implementation evidence | — | — |
| D62 | Initial / as applicable | No implementation evidence | — | — |
| D63 | Initial / as applicable | No implementation evidence | — | — |
| D64 | Initial / as applicable | No implementation evidence | — | — |
| D65 | Initial / as applicable | No implementation evidence | — | — |
| D66 | Initial / as applicable | No implementation evidence | — | — |
| D67 | Initial / as applicable | No implementation evidence | — | — |
| D68 | Initial / as applicable | No implementation evidence | — | — |
| D69 | Initial / as applicable | No implementation evidence | — | — |
| D70 | Superseded | Superseded by D71 | — | — |
| D71 | Initial / as applicable | No implementation evidence | — | — |
| D72 | Initial: refuse-only; approval UI deferred (D159) | No implementation evidence | — | — |
| D73 | Initial: refuse-only; approval UI deferred (D159) | No implementation evidence | — | — |
| D74 | Initial / as applicable | No implementation evidence | — | — |
| D75 | Initial / as applicable | No implementation evidence | — | — |
| D76 | Initial: refuse-only; approval UI deferred (D159) | No implementation evidence | — | — |
| D77 | Initial / as applicable | No implementation evidence | — | — |
| D78 | Initial / as applicable | No implementation evidence | — | — |
| D79 | Initial / as applicable | No implementation evidence | — | — |
| D80 | Initial / as applicable | No implementation evidence | — | — |
| D81 | Initial / as applicable | No implementation evidence | — | — |
| D82 | Initial / as applicable | No implementation evidence | — | — |
| D83 | Initial / as applicable | No implementation evidence | — | — |
| D84 | Initial / as applicable | No implementation evidence | — | — |
| D85 | Initial / as applicable | In progress | [#21](https://github.com/heaje/muteinous/issues/21) / [PR #26](https://github.com/heaje/muteinous/pull/26) | Queue-level only: a cancelled running job keeps its slots until the worker returns and late results/reports are rejected ([cancellation tests](../../tests/integration/jobs/test_job_queue_cancellation.py)). Alignment/provider-specific rules not implemented. Local Windows evidence only; no remote CI, Linux/macOS unverified ([#4](https://github.com/heaje/muteinous/issues/4)). |
| D86 | Initial / as applicable | No implementation evidence | — | — |
| D87 | Initial / as applicable | In progress | [#21](https://github.com/heaje/muteinous/issues/21) / [PR #26](https://github.com/heaje/muteinous/pull/26) | In-process queue foundation (`src/muteinous/infrastructure/jobs/queue.py`): stable IDs, JSON-object plan input separate from workers, status, cancellation, resource limits, drain/close ([scheduling](../../tests/integration/jobs/test_job_queue_scheduling.py), [cancellation](../../tests/integration/jobs/test_job_queue_cancellation.py) tests). Persistence-ready input schema still open; no real providers or shutdown integration. Local Windows evidence only; no remote CI, Linux/macOS unverified ([#4](https://github.com/heaje/muteinous/issues/4)). |
| D88 | Initial / as applicable | Implemented / unverified | [#21](https://github.com/heaje/muteinous/issues/21) / [PR #26](https://github.com/heaje/muteinous/pull/26) | FIFO among eligible jobs with independent bypass and capacity-release restart during validation ([scheduling tests](../../tests/integration/jobs/test_job_queue_scheduling.py); [finding](../../.agents/findings/job-dispatch-capacity-race.md)). A job overlapping a younger stream's resources can be bypassed repeatedly, as the decision permits. Local Windows evidence only; no remote CI, Linux/macOS unverified ([#4](https://github.com/heaje/muteinous/issues/4)). |
| D89 | Initial / as applicable | In progress | [#21](https://github.com/heaje/muteinous/issues/21) / [PR #26](https://github.com/heaje/muteinous/pull/26) | Named resources with atomic multi-slot acquisition, no partial reservation, configurable capacities ([scheduling tests](../../tests/integration/jobs/test_job_queue_scheduling.py)). Concrete resource naming/registration still open. Local Windows evidence only; no remote CI, Linux/macOS unverified ([#4](https://github.com/heaje/muteinous/issues/4)). |
| D90 | Initial / as applicable | No implementation evidence | — | — |
| D91 | Initial / as applicable | In progress | [#21](https://github.com/heaje/muteinous/issues/21) / [PR #26](https://github.com/heaje/muteinous/pull/26) | Immutable resolved `JobPlan` with dispatch-time validator and Needs attention without fallback ([scheduling tests](../../tests/integration/jobs/test_job_queue_scheduling.py)). Real provider/source validators not integrated. Local Windows evidence only; no remote CI, Linux/macOS unverified ([#4](https://github.com/heaje/muteinous/issues/4)). |
| D92 | Initial / as applicable | Implemented / unverified | [#21](https://github.com/heaje/muteinous/issues/21) / [PR #26](https://github.com/heaje/muteinous/pull/26) | Preference changes apply only to new submissions; queued plans are preserved ([scheduling tests](../../tests/integration/jobs/test_job_queue_scheduling.py)). Local Windows evidence only; no remote CI, Linux/macOS unverified ([#4](https://github.com/heaje/muteinous/issues/4)). |
| D93 | Initial / as applicable | In progress | [#21](https://github.com/heaje/muteinous/issues/21) / [PR #26](https://github.com/heaje/muteinous/pull/26) | No queue-wait or execution deadline; busy plans stay queued with a waiting reason and are revalidated on an interval ([scheduling tests](../../tests/integration/jobs/test_job_queue_scheduling.py)). Alignment retry pending-request policy not implemented. Local Windows evidence only; no remote CI, Linux/macOS unverified ([#4](https://github.com/heaje/muteinous/issues/4)). |
| D94 | Initial / as applicable | No implementation evidence | — | — |
| D95 | Initial / as applicable | In progress | [#21](https://github.com/heaje/muteinous/issues/21) / [PR #26](https://github.com/heaje/muteinous/pull/26) | Optional stage/activity/count progress with heartbeat distinct from meaningful progress ([progress tests](../../tests/integration/jobs/test_job_queue_progress.py), [WorkCount tests](../../tests/unit/infrastructure/jobs/test_work_count.py)). No stall warning (D94) or provider adapters. Local Windows evidence only; no remote CI, Linux/macOS unverified ([#4](https://github.com/heaje/muteinous/issues/4)). |
| D96 | Initial / as applicable | In progress | [#21](https://github.com/heaje/muteinous/issues/21) / [PR #26](https://github.com/heaje/muteinous/pull/26) | Optional per-invocation progress reporting retaining only the latest snapshot ([progress tests](../../tests/integration/jobs/test_job_queue_progress.py)). No provider adapters. Local Windows evidence only; no remote CI, Linux/macOS unverified ([#4](https://github.com/heaje/muteinous/issues/4)). |
| D97 | Initial / as applicable | In progress | [#21](https://github.com/heaje/muteinous/issues/21) / [PR #26](https://github.com/heaje/muteinous/pull/26) | Percentage only for a reliable denominator; overall count optional ([WorkCount tests](../../tests/unit/infrastructure/jobs/test_work_count.py)). Local Windows evidence only; no remote CI, Linux/macOS unverified ([#4](https://github.com/heaje/muteinous/issues/4)). |
| D98 | Initial / as applicable | Implemented / unverified | [#21](https://github.com/heaje/muteinous/issues/21) / [PR #26](https://github.com/heaje/muteinous/pull/26) | Routine updates coalesced by `poll`; stage, state and detail changes returned promptly ([progress tests](../../tests/integration/jobs/test_job_queue_progress.py)). UI polling not implemented. Local Windows evidence only; no remote CI, Linux/macOS unverified ([#4](https://github.com/heaje/muteinous/issues/4)). |
| D99 | Initial / as applicable | In progress | [#21](https://github.com/heaje/muteinous/issues/21) / [PR #26](https://github.com/heaje/muteinous/pull/26) | Unknown/provisional totals report counts without a percentage ([WorkCount tests](../../tests/unit/infrastructure/jobs/test_work_count.py)). Reliability criteria for discovery totals remain provider work. Local Windows evidence only; no remote CI, Linux/macOS unverified ([#4](https://github.com/heaje/muteinous/issues/4)). |
| D100 | Initial / as applicable | In progress | [#21](https://github.com/heaje/muteinous/issues/21) / [PR #26](https://github.com/heaje/muteinous/pull/26) | Six lifecycle states with separate detail and `physical_running` ([scheduling](../../tests/integration/jobs/test_job_queue_scheduling.py), [cancellation](../../tests/integration/jobs/test_job_queue_cancellation.py) tests). Permitted transitions and user-facing handling still open. Local Windows evidence only; no remote CI, Linux/macOS unverified ([#4](https://github.com/heaje/muteinous/issues/4)). |
| D101 | Initial / as applicable | Implemented / unverified | [#21](https://github.com/heaje/muteinous/issues/21) / [PR #26](https://github.com/heaje/muteinous/pull/26) | One execution attempt per submission; failures retained as Failed with detail and no retry ([failure tests](../../tests/integration/jobs/test_job_queue_failures.py), [scheduling tests](../../tests/integration/jobs/test_job_queue_scheduling.py)). Local Windows evidence only; no remote CI, Linux/macOS unverified ([#4](https://github.com/heaje/muteinous/issues/4)). |
| D102 | Initial / as applicable | No implementation evidence | — | — |
| D103 | Initial / as applicable | No implementation evidence | — | — |
| D104 | Initial / as applicable | No implementation evidence | — | — |
| D105 | Initial / as applicable | No implementation evidence | — | — |
| D106 | Initial / as applicable | No implementation evidence | — | — |
| D107 | Initial / as applicable | No implementation evidence | — | — |
| D108 | Initial / as applicable | No implementation evidence | — | — |
| D109 | Initial / as applicable | No implementation evidence | — | — |
| D110 | Initial / as applicable | No implementation evidence | — | — |
| D111 | Initial / as applicable | No implementation evidence | — | — |
| D112 | Initial / as applicable | No implementation evidence | — | — |
| D113 | Initial / as applicable | No implementation evidence | — | — |
| D114 | Initial / as applicable | No implementation evidence | — | — |
| D115 | Initial / as applicable | No implementation evidence | — | — |
| D116 | Initial / as applicable | No implementation evidence | — | — |
| D117 | Initial / as applicable | No implementation evidence | — | — |
| D118 | Initial / as applicable | No implementation evidence | — | — |
| D119 | Initial / as applicable | No implementation evidence | — | — |
| D120 | Initial / as applicable | No implementation evidence | — | — |
| D121 | Initial / as applicable | No implementation evidence | — | — |
| D122 | Initial / as applicable | No implementation evidence | — | — |
| D123 | Initial / as applicable | No implementation evidence | — | — |
| D124 | Initial / as applicable | No implementation evidence | — | — |
| D125 | Initial / as applicable | No implementation evidence | — | — |
| D126 | Initial / as applicable | No implementation evidence | — | — |
| D127 | Initial / as applicable | No implementation evidence | — | — |
| D128 | Initial / as applicable | No implementation evidence | — | — |
| D129 | Initial / as applicable | No implementation evidence | — | — |
| D130 | Initial / as applicable | No implementation evidence | — | — |
| D131 | Initial / as applicable | No implementation evidence | — | — |
| D132 | Initial / as applicable | No implementation evidence | — | — |
| D133 | Initial / as applicable | No implementation evidence | — | — |
| D134 | Initial / as applicable | No implementation evidence | — | — |
| D135 | Initial / as applicable | No implementation evidence | — | — |
| D136 | Initial: automatic speech assessment/refusal; manual confirmation later (D162) | No implementation evidence | — | — |
| D137 | Initial / as applicable | No implementation evidence | — | — |
| D138 | Initial / as applicable | No implementation evidence | — | — |
| D139 | Initial / as applicable | No implementation evidence | — | — |
| D140 | Initial: automatic association/refusal; manual confirmation later (D162) | No implementation evidence | — | — |
| D141 | Initial / as applicable | No implementation evidence | — | — |
| D142 | Initial / as applicable | No implementation evidence | — | — |
| D143 | Initial / as applicable | No implementation evidence | — | — |
| D144 | Initial / as applicable | No implementation evidence | — | — |
| D145 | Initial / as applicable | No implementation evidence | — | — |
| D146 | Initial | No implementation evidence | — | — |
| D147 | Later (D159) | Deferred (D159) | — | — |
| D148 | Later (D159) | Deferred (D159) | — | — |
| D149 | Later (D159) | Deferred (D159) | — | — |
| D150 | Later (D159) | Deferred (D159) | — | — |
| D151 | Later (D159) | Deferred (D159) | — | — |
| D152 | Later (D159) | Deferred (D159) | — | — |
| D153 | Later (D159) | Deferred (D159) | — | — |
| D154 | Later (D159) | Deferred (D159) | — | — |
| D155 | Later (D159) | Deferred (D159) | — | — |
| D156 | Later (D159) | Deferred (D159) | — | — |
| D157 | Later (D159) | Deferred (D159) | — | — |
| D158 | Later (D159) | Deferred (D159) | — | — |
| D159 | Cross-cutting | No implementation evidence | — | — |
| D160 | Cross-cutting | In progress | [#2](https://github.com/heaje/muteinous/issues/2) / [PR #3](https://github.com/heaje/muteinous/pull/3); [#6](https://github.com/heaje/muteinous/issues/6) / [PR #10](https://github.com/heaje/muteinous/pull/10) | Single `src/muteinous` distribution, installed-package smoke test, test organization and decision-ID check verified by [Windows CI](https://github.com/heaje/muteinous/actions/runs/45266951928) and [three-platform tooling matrix](https://github.com/heaje/muteinous/actions/runs/45313050872). Bootstrap only; application-layer boundaries and safety integration tests not yet implemented. |
| D161 | Cross-cutting | In progress | [#2](https://github.com/heaje/muteinous/issues/2) / [PR #3](https://github.com/heaje/muteinous/pull/3); [#7](https://github.com/heaje/muteinous/issues/7) / [PR #11](https://github.com/heaje/muteinous/pull/11); [#4](https://github.com/heaje/muteinous/issues/4) | [Two-worker benchmark](https://github.com/heaje/muteinous/actions/runs/45119082187); [Windows full CI](https://github.com/heaje/muteinous/actions/runs/45396493406): two logical CPUs, 40 tests, 21.338 s pytest session / 22.587 s test-step wall time; no skips. Native ten-minute test-step timeout configured; deliberate failure-path control deferred, not verified. Final main CI and representative application safety tests outstanding. |
| D162 | Cross-cutting (release phasing) | No implementation evidence | — | — |
| D163 | Cross-cutting (development tooling) | Implemented / unverified | [#6](https://github.com/heaje/muteinous/issues/6) / [PR #10](https://github.com/heaje/muteinous/pull/10); [PR #12](https://github.com/heaje/muteinous/pull/12); [#4](https://github.com/heaje/muteinous/issues/4) | [Three-platform review matrix](https://github.com/heaje/muteinous/actions/runs/45313050872): explicit setup, locked readiness refusals, portable commands and safe clean; Windows full checks passed. Subsequent Taskfile changes in PR #12 lack final-head remote CI; reverify current main. |
| D164 | Cross-cutting (Python/dependencies) | In progress | [#6](https://github.com/heaje/muteinous/issues/6) / [PR #10](https://github.com/heaje/muteinous/pull/10); [#7](https://github.com/heaje/muteinous/issues/7) / [PR #11](https://github.com/heaje/muteinous/pull/11); [PR #12](https://github.com/heaje/muteinous/pull/12); [#4](https://github.com/heaje/muteinous/issues/4) | [Windows compatibility probe](https://github.com/heaje/muteinous/actions/runs/45298464859) and [compatibility record](../python-compatibility.md): 3.14.10 candidate binary imports pass; 3.15.2 blocked by wheels. Locked uv setup passed on [three platforms](https://github.com/heaje/muteinous/actions/runs/45313050872). Dependabot config statically validated; successful default-branch version-update runs recorded for [uv](https://github.com/heaje/muteinous/actions/runs/45440756640) and [GitHub Actions](https://github.com/heaje/muteinous/actions/runs/45440755466). Weekly recurrence, generated PR titles, bundled uv compatibility and security alerts/fixes remain unverified. Final lock changes lack remote CI; required application/native/GPU/GUI runtime compatibility not established. |
| D165 | Cross-cutting (CI/portability) | In progress | [#7](https://github.com/heaje/muteinous/issues/7) / [PR #11](https://github.com/heaje/muteinous/pull/11); [#4](https://github.com/heaje/muteinous/issues/4) | [CI run 45396493406](https://github.com/heaje/muteinous/actions/runs/45396493406): Windows full 40 tests; Ubuntu/macOS 24 portable each; setup/build/import, commit checks and no skips. Main ruleset inactive on private Free plan per maintainer; required merge gates not enforced. Final main CI and D161 timeout negative control outstanding. |
| D166 | Cross-cutting (versioning/releases) | Implemented / unverified | [#6](https://github.com/heaje/muteinous/issues/6) / [PR #10](https://github.com/heaje/muteinous/pull/10); [#8](https://github.com/heaje/muteinous/issues/8) / [PR #13](https://github.com/heaje/muteinous/pull/13); [#4](https://github.com/heaje/muteinous/issues/4) | Commitizen/SCM and pre-1.0 behavior tested in [tooling matrix](https://github.com/heaje/muteinous/actions/runs/45313050872); release PR reports local `task check` passing 85 tests at final head `108f441` and earlier disposable-repo API checks. Earlier [CI](https://github.com/heaje/muteinous/actions/runs/45408049042) predates draft-first amendment. Final workflow creates draft targeting validated SHA; GitHub tags on human publication, abandoned draft deleted manually. Live dispatch, artifact transfer/download, token permissions, all channels, manual recovery and final-head remote CI unverified. Desktop installer deferred until app exists. |

## Updating this tracker

For each implementation PR, report affected decision IDs, Issue/PR references, and test/inspection results (including remaining unverified requirements) in the PR description. Once accepted, the merger/coordinator updates affected rows as a single merge-time reconciliation or prompt follow-up, rather than maintaining competing ledger edits across active branches. Keep **exactly one row for every numbered decision in the current decision log**, including historical/superseded decisions; add new rows and reconcile statuses or phases when approved decisions change. Preserve partial-evidence limits instead of treating all safeguards as verified. When CI exists, add a deterministic check comparing the **sets of decision IDs in the log and ledger**, rejecting missing, extra or duplicate IDs. Do not hardcode a maximum decision number or freeze historical phase classifications in the check; substantive status changes require review against the source.
