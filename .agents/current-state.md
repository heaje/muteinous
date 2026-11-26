# Implementation coordination snapshot

**Last reconciled:** 2026-11-26. **Evidence baseline:** [main at `a46bada`](https://github.com/heaje/muteinous/commit/a46bada876461bd60446ff5599159fbf017c57a4), merged by [PR #43](https://github.com/heaje/muteinous/pull/43), with prior baseline `f3b3523` from [PR #41](https://github.com/heaje/muteinous/pull/41). GitHub Issues/PRs and checked-out code govern implementation; the [canonical architecture](../docs/architecture/decisions.md) governs requirements. This snapshot is the outstanding cross-task verification register, not a substitute for the [decision evidence ledger](../docs/architecture/decision-coverage.md).

## Current

- **M0 infrastructure:** implementation is present. Current-main-equivalent CI and branch ruleset enforcement are verified as described below; operational acceptance is still incomplete. Earlier budget-exhaustion and private-Free-plan/inactive-ruleset reports are obsolete.
- **M1 implementation:** Issues [#16](https://github.com/heaje/muteinous/issues/16)–[#22](https://github.com/heaje/muteinous/issues/22) are closed and their implementation accepted. The independent R1 acceptance audit found no confirmed defect. This is not M1 verification completion.

### M1 issue dispositions

| Issue | Accepted implementation and current evidence |
| --- | --- |
| [#16](https://github.com/heaje/muteinous/issues/16) | [PR #24](https://github.com/heaje/muteinous/pull/24): identity-only models/source metadata. Windows ran the full suite. Linux/macOS ran only marked tests: one SegmentKey context case in `test_segment.py`, one exact-source-text case in `test_source.py`, and the package-boundary case in `test_package_boundary.py`; other model tests ran on Windows only. |
| [#17](https://github.com/heaje/muteinous/issues/17) | [PR #38](https://github.com/heaje/muteinous/pull/38): accepted BLAKE3 source-validity foundation. Linux/macOS portable jobs executed one marked fingerprint determinism/algorithm-distinguishability test and one marked validity test; the remaining fingerprint tests (including bounded/chunked reads, hasher construction and unreadable-file behavior) ran on Windows only. Cold-cache and Linux/macOS benchmarks, advisories, frozen-app redistribution review, and M2 workflow integration remain open. D14–D15 remain M4. |
| [#18](https://github.com/heaje/muteinous/issues/18) | [PR #33](https://github.com/heaje/muteinous/pull/33): immutable speech results and timing validation. `tests/unit/models/test_speech.py` has a module-level portable marker, so all tests in that file ran on Linux/macOS as well as Windows. Provider/storage/filter integration remains future work. The prior static re-review is recorded at [PR #33](https://github.com/heaje/muteinous/pull/33#issuecomment-7180968665). |
| [#19](https://github.com/heaje/muteinous/issues/19) | [PR #27](https://github.com/heaje/muteinous/pull/27): shared PCM and replaceable lossless WAV scratch. `test_pcm.py`, `test_wav.py`, and `test_audio_scratch.py` each have module-level portable markers and ran on Linux/macOS; Windows ran the full suite. This does not establish native-tool compatibility or behavior in unmarked tests. |
| [#20](https://github.com/heaje/muteinous/issues/20) | [PR #25](https://github.com/heaje/muteinous/pull/25) findings and [PR #36](https://github.com/heaje/muteinous/pull/36) documentation/retained experiment. R1 verified `8b3b3ba` is an ancestor of `ccaf315` and the diff is documentation-only; the review summary is recorded in PR #45 comments. Native experiment remains outside main/distribution; current CI does not exercise its branch-only code. Outstanding checks are listed below. |
| [#21](https://github.com/heaje/muteinous/issues/21) | [PR #26](https://github.com/heaje/muteinous/pull/26), [PR #30](https://github.com/heaje/muteinous/pull/30): job-queue foundation and ledger evidence. Portable-marked queue files `test_job_queue_scheduling.py`, `test_job_queue_progress.py`, `test_job_queue_cancellation.py`, and `test_job_queue_failures.py` ran on Linux/macOS; Windows ran the full suite. Provider integration, persistence, actual provider shutdown and stall policy remain separate implementation work. |
| [#22](https://github.com/heaje/muteinous/issues/22) | [PR #28](https://github.com/heaje/muteinous/pull/28): isolated staging, publication and integrity foundation. Linux/macOS ran only portable-marked storage tests/cases: unit `test_bundles.py`, `test_filesystem.py`, `test_staging.py`, portable-marked cases in `test_space.py`, and marked cases in integration `test_result_storage_integrity.py`, `test_result_storage_space.py`, `test_result_storage_publication.py`, and `test_result_storage_cleanup.py`. Windows ran the full suite; unmarked POSIX-specific cases did not run on Linux/macOS. |

## Deferred verification

Unchecked items are outstanding, not passes or waivers. The PR workflow has no push trigger and no required PR-check run targets exact main `a46bada`; separate manual release-workflow dispatches at that SHA are in progress and their results are not recorded here. [Run 45863237303](https://github.com/heaje/muteinous/actions/runs/45863237303) passed on PR #43 final head `6cadc5a`, testing synthetic merge `eb6d804`. GitHub's commit API verifies its tree `57ecda8` equals the merge commit tree on main `a46bada`; this is **tree-equivalent PR CI, not exact-main PR-check execution**. No rerun is required by D160–D166 as reviewed in R5.

The run's Windows job passed 574 tests on four logical CPUs (4.341 s pytest session; 5.254 s test-step wall time), plus lint, format, strict typing, decision IDs, Conventional Commit/PR title checks, version preview, sdist/wheel and isolated import. Linux passed 530 portable tests in 2.512 s and macOS passed 530 in 3.589 s; both also passed locked setup and packaging/import checks. CPython was 3.14.10. These are individual observed runs, not controlled benchmarks. Earlier [main dispatch 45771751629](https://github.com/heaje/muteinous/actions/runs/45771751629) tested `f3b3523` (Windows 570 tests, 46.536 s on four logical CPUs; Linux/macOS 524 portable); [PR #41 run 45771353335](https://github.com/heaje/muteinous/actions/runs/45771353335) is historical. Actions availability is restored. D161 baseline context and the pending amendment are summarized in the gate below.

| Outstanding gate | Evidence and completion criteria |
| --- | --- |
| **D161 baseline transition and timeout negative control** | Current D161 text names a two-vCPU Windows baseline; CI on this public repository runs 4 vCPU ([run 45863237303](https://github.com/heaje/muteinous/actions/runs/45863237303): 4 logical CPUs, 574 passed, 4.341 s session). The maintainer directed the baseline be changed to four vCPU; amendment is pending via a separate reviewed PR. Once merged, this run is the baseline-hardware measurement against the five-minute target (verify then). The deliberate timeout negative control remains separate and in progress under maintainer authorization; verify step and job fail independently of job timeout and record diagnostics. `pr.yml` step/warning wording should be updated after the amendment; this PR does not edit the workflow or decision text. |
| **D166 live release acceptance** | In progress by other agents under maintainer authorization; no results recorded here. Exercise development-build and alpha/beta/RC/stable draft acceptance, artifact download/metadata, SHA/version/checksums/notes/prerelease flag, transfer, permissions and abandoned-draft recovery without publishing. |
| **Dependabot, D164–D165** | Read-only settings check 2026-11-26: alerts/security fixes remain disabled; automated security fixes `enabled=false`; vulnerability-alert API reports disabled (404). MAINTAINER will enable alerts and security fixes; this remains a maintainer action, not completed. Also verify weekly recurrence, grouped PR titles and compatibility with bundled uv; existing individual update runs do not prove recurrence. |
| **Architecture confirmation** | [Issue #5](https://github.com/heaje/muteinous/issues/5) criterion: maintainer confirmation that decisions match the approved original architecture discussion remains open. |
| **BLAKE3 benchmark/advisory follow-up** | In progress in a separate PR/work unit; no results recorded here. Cold-cache measurement plus Linux/macOS benchmark repeat and security-advisory recheck remain pending. Existing benchmark was warm-cache, synthetic and one Windows machine. |
| **Frozen-application notice/redistribution audit** | Before redistribution, inspect the actual dependency/binary graph and required notices; the earlier audit did not inspect all crate notices, parse the SBOM or inspect binary features. A minimal frozen-app smoke test is not a release build. |
| **#20 retained branch checks** | Still outstanding: locked Windows rerun on retained branch, native Linux/macOS reproduction, package-exclusion check, and any checks applicable only to experiment code absent from main. Current PR CI covers main's portable-marked subset, not the retained experiment or nonportable Linux/macOS tests. The D161 timing gate below also applies to the retained branch. |
| **Per-issue checks outside current CI** | See issue matrix below. Current Windows full suite and Linux/macOS portable subsets satisfy only those exact scopes; unmarked/nonportable cases were not run on Linux/macOS. |

### M1 historical deferrals: current-run disposition

Run [45863237303](https://github.com/heaje/muteinous/actions/runs/45863237303) executes the entire current test suite on Windows and only `@pytest.mark.portable` tests on Linux/macOS, plus locked environment/package checks. The same policy is documented in [testing.md](../docs/testing.md#mandatory-portability-checks--d165). Thus “current-main full Windows” and “portable Linux/macOS” are satisfied on the PR #43 tree (not exact main); “Linux/macOS execution” means portable tests only, not the whole suite, locked native experiment runtime, or every platform-specific case.

| Historical item | Now satisfied by exact evidence | Still open / not established |
| --- | --- | --- |
| **#16** | Full Windows suite; Linux/macOS ran only marked cases: one each in `test_segment.py` (content context), `test_source.py` (exact source text), and `test_package_boundary.py`. | Other model tests on Linux/macOS; any claim beyond the tested synthetic-merge tree. |
| **#17** | Full Windows suite and locked build/import; Linux/macOS ran only `test_fingerprint_is_deterministic_and_algorithm_distinguishable` from `test_fingerprints.py` (locked BLAKE3 import and determinism/algorithm distinction) and `test_changed_dependency_identity_invalidates_only_dependent_result` from `test_validity.py`. | Remaining fingerprint/validity tests on Linux/macOS; cold-cache/cross-platform benchmarks, advisories, frozen-app notices. |
| **#18** | Full Windows suite and all tests in `tests/unit/models/test_speech.py` on Linux/macOS (module-level portable marker). | Provider/integration behavior not implemented; tests outside that portable file and exact-main execution. Earlier unlocked focused reviewer run remains historical. |
| **#19** | Full Windows suite and all cases in `test_pcm.py`, `test_wav.py`, and `test_audio_scratch.py` on Linux/macOS (each file has a module-level portable marker). | Other/unmarked PCM or scratch cases on Linux/macOS; native tools/format compatibility. |
| **#20** | Main's portable tests and full Windows suite only; no equivalence to experiment validation. | Retained-branch locked Windows rerun, native Linux/macOS probes, experiment package exclusions, and baseline-hardware timing after the D161 amendment merges; no game-loader/install claim. |
| **#21** | Full Windows suite and portable-marked Linux/macOS queue files `test_job_queue_scheduling.py`, `test_job_queue_progress.py`, `test_job_queue_cancellation.py`, and `test_job_queue_failures.py`; scheduling includes the capacity-release regression. | Unmarked queue cases on Linux/macOS; provider/persistence/real shutdown/stall integrations and exact-main execution. |
| **#22** | Full Windows suite and only portable-marked storage modules/cases listed in the Issue #22 disposition above on Linux/macOS. | Unmarked storage/POSIX cases, exact-main execution and supported-filesystem claims beyond tested coverage. |

### Issue #42 benchmark disposition

The final-head focused benchmark on the same 24-logical-CPU workstation covered five PR #43 test files (`tests/integration/test_pytest_policy.py`, `tests/unit/test_build_configuration.py`, `tests/unit/test_pytest_policy.py`, `tests/unit/test_release.py`, `tests/unit/test_versioning.py`), 72 tests:

| Selection | Result | Pytest session | Wall |
| --- | --- | ---: | ---: |
| Serial (`-n 0`) | 72 passed | 1.273 s | 1.823 s |
| `-n 2` | 72 passed | 1.280 s | 1.827 s |
| Default (24 workers) | 72 passed | 3.066 s | 3.648 s |
| Full suite, default | 574 passed | 3.878 s | 4.459 s |

These are one run per mode, not controlled benchmarks or baseline-hardware evidence. The original #42 scope at `f3b3523` (two files, 33 tests: serial 52.641 s, two workers 31.029 s, 24 workers 22.513 s) was not remeasured; it differs in scope and content, so this is not a like-for-like comparison. The maintainer approved closing #42 after recording the benchmark. The coordinator, not this PR, will comment and close the issue after this PR merges; this PR does not modify #42.

Fresh supervisor-directed local validation was reported for Windows 11 Pro on 2026-11-26 at exact main `a46bada`, clean before and after: 24 logical processors, CPython 3.14.10, uv 0.13.9, Task 3.54.0, pytest 9.2.0, xdist 3.8.0; locked `task setup` succeeded; `task check` succeeded, including 574 tests (3.870 s, 24 workers), Ruff/format (71 files), strict mypy (70 source files), decision IDs, build/isolated import and preview `0.1.dev29+ga46bada87` / next `0.1.0`. `task.cmd test -- -n 2`: 574 passed (4.782 s session, 5.345 s wall); `task.cmd test -- -m portable -n 2`: 530 passed (4.313 s session, 4.856 s wall). This is reported executor evidence on 24 CPUs, not a pre-amendment baseline measurement.

**Editable metadata observation (not a defect classification):** after setup, editable dist-info/importlib metadata reported `0.1.dev26+g6f057f5b0`, while fresh build and version preview reported current `0.1.dev29+ga46bada87`. `pyproject.toml` uses dynamic setuptools-scm versioning and has no `[tool.uv] cache-keys`. uv metadata caching is a plausible but untested explanation. The validated build/isolated-install path reports the current SHA; no release/packaging failure was observed. No change was made and this observation is not permanent guidance.

### M1 review and milestone gates

Independent static read-only reviews by separate agents on 2026-11-26 at main `a46bada` (no code executed): R1 M1 issues #16–22 acceptance, R2 cross-module integration, R3 canonical architecture, R4 PR #43 delta, R5 M0 infrastructure. R1/R2/R3/R5 summaries are recorded in PR #45 comments. R1 found no actionable implementation defect and verified the #20 branch ancestry/documentation-only delta; native probes were not rerun. R2 found no application-code defect and checked the queue capacity-revision restart/regression. R3 found no canonical-architecture issue. R4's direct record is [PR #43 comment](https://github.com/heaje/muteinous/pull/43#issuecomment-7198925281); its reported P2 test-isolation concern was rejected by the supervisor and MAINTAINER directed no restoration, so it is not an open action. R5 found Dependabot alerts/security fixes disabled (coordinator-confirmed API evidence; maintainer will enable them) and stale M0 status evidence, reconciled here; it found no application-code defect. The PR #41 post-merge review is recorded at [PR #41 comment](https://github.com/heaje/muteinous/pull/41#issuecomment-7198951004). **PR #41 and #43 merged without pre-merge recorded independent review**—a historical process deviation; later post-merge reviews do not erase it. Reviews were static and do not replace execution evidence.

| Readiness dimension | Status |
| --- | --- |
| M1 implementation completion | Accepted for #16–22; no confirmed defects. |
| M1 verification completion | **Not complete**: D161 baseline amendment and timeout negative control, D166 live workflows, Dependabot actions, #5 confirmation, BLAKE3 follow-up, frozen redistribution audit and #20 retained-branch checks remain. |
| M2 planning readiness | Not determined here; coordinator must establish M2 scope/dependencies. |
| M2 implementation readiness | Not authorized by M1 implementation closure; verify prerequisite gates and scope first. |
| PR merge readiness | This documentation PR must satisfy its required CI and independent review; zero mandatory repository approvals does not waive the independent-review policy. |
| Release readiness | Not established; D161/D165/D166 and applicable safety gates remain. |

## Next

1. Transfer and complete the exact outstanding gates above; update affected [coverage rows](../docs/architecture/decision-coverage.md) only with evidence. Never treat issue closure, PR merge, portable checks or a tree-equivalent PR run as proof of unrun coverage.
2. M2 discovery/scanning, M3 filtering/preview/review, and M4 safe Apply/release remain proposed sequencing; consult the coordinator and current decisions before starting dependent implementation.

## Cross-task risks

- Independent review, required CI, issue acceptance, milestone verification and release readiness are separate gates. Do not infer exact-main execution or nonportable cross-platform compatibility from the current PR run.
- Preserve the [initial-release scope](../docs/release-scope.md), source-validity preconditions and explicit native compatibility evidence. Synthetic success is not loader or installation safety.
