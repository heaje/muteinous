# Implementation coordination snapshot

**Last reconciled:** 2026-11-26. **Evidence baseline:** [main at `a46bada`](https://github.com/heaje/muteinous/commit/a46bada876461bd60446ff5599159fbf017c57a4), merged by [PR #43](https://github.com/heaje/muteinous/pull/43), with prior baseline `f3b3523` from [PR #41](https://github.com/heaje/muteinous/pull/41). GitHub Issues/PRs and checked-out code govern implementation; the [canonical architecture](../docs/architecture/decisions.md) governs requirements. This snapshot is the outstanding cross-task verification register, not a substitute for the [decision evidence ledger](../docs/architecture/decision-coverage.md).

## Current

- **M0 infrastructure:** implementation is present. Current-main-equivalent CI and branch ruleset enforcement are verified as described below; operational acceptance is still incomplete. Earlier budget-exhaustion and private-Free-plan/inactive-ruleset reports are obsolete.
- **M1 implementation:** Issues [#16](https://github.com/heaje/muteinous/issues/16)–[#22](https://github.com/heaje/muteinous/issues/22) are closed and their implementation accepted. The M1 audit [R1](https://github.com/heaje/muteinous/pull/43) found no confirmed defect. This is not M1 verification completion.

### M1 issue dispositions

| Issue | Accepted implementation and current evidence |
| --- | --- |
| [#16](https://github.com/heaje/muteinous/issues/16) | [PR #24](https://github.com/heaje/muteinous/pull/24): identity-only models/source metadata. Windows full suite and portable Linux/macOS subset now ran on the PR #43 tree; domain integration and nonportable cross-platform behavior are not implied. |
| [#17](https://github.com/heaje/muteinous/issues/17) | [PR #38](https://github.com/heaje/muteinous/pull/38): accepted BLAKE3 source-validity foundation. Current full Windows and portable Linux/macOS checks ran, but they do not complete cold-cache/Linux/macOS hashing benchmarks, advisory checks, frozen-app redistribution review, or M2 workflow integration. D14–D15 remain M4. |
| [#18](https://github.com/heaje/muteinous/issues/18) | [PR #33](https://github.com/heaje/muteinous/pull/33): immutable speech results and timing validation. Current full Windows and portable Linux/macOS tests include the portable speech-model tests; provider/storage/filter integration remains future work. The prior static re-review is recorded at [PR #33](https://github.com/heaje/muteinous/pull/33#issuecomment-7180968665). |
| [#19](https://github.com/heaje/muteinous/issues/19) | [PR #27](https://github.com/heaje/muteinous/pull/27): shared PCM and replaceable lossless WAV scratch. Current Windows full suite includes nonportable tests; the portable subset ran on Linux/macOS. This does not establish native-tool compatibility or macOS behavior for nonportable tests. |
| [#20](https://github.com/heaje/muteinous/issues/20) | [PR #25](https://github.com/heaje/muteinous/pull/25) findings and [PR #36](https://github.com/heaje/muteinous/pull/36) documentation/retained experiment. The [R1 ancestry audit](https://github.com/heaje/muteinous/pull/43) verified `8b3b3ba` is an ancestor of `ccaf315` and the diff is documentation-only. Native experiment remains outside main/distribution; current main CI does not exercise that branch-only code. Outstanding checks are listed below. |
| [#21](https://github.com/heaje/muteinous/issues/21) | [PR #26](https://github.com/heaje/muteinous/pull/26), [PR #30](https://github.com/heaje/muteinous/pull/30): job-queue foundation and ledger evidence. Current full Windows and portable Linux/macOS test suites include the queue regression. Provider integration, persistence, actual provider shutdown and stall policy remain separate implementation work. |
| [#22](https://github.com/heaje/muteinous/issues/22) | [PR #28](https://github.com/heaje/muteinous/pull/28): isolated staging, publication and integrity foundation. Current full Windows and portable Linux/macOS suites include portable storage cases; POSIX-specific cases not marked portable were not exercised by these jobs. |

## Deferred verification

Unchecked items are outstanding, not passes or waivers. The PR workflow has no push trigger and no required PR-check run targets exact main `a46bada`; separate manual release-workflow dispatches at that SHA are in progress and their results are not recorded here. [Run 45863237303](https://github.com/heaje/muteinous/actions/runs/45863237303) passed on PR #43 final head `6cadc5a`, testing synthetic merge `eb6d804`. GitHub's commit API verifies its tree `57ecda8` equals the merge commit tree on main `a46bada`; this is **tree-equivalent PR CI, not exact-main PR-check execution**. No rerun is required by D160–D166 as reviewed in R5. Current D161 text still names a two-vCPU baseline. The maintainer directed a four-vCPU baseline amendment for a separate reviewed PR; until it merges, do not treat this run as satisfying the current baseline. The `pr.yml` step name/warning describing the two-vCPU baseline will need corresponding follow-up after that amendment; this PR does not edit the workflow or decision text.

The run's Windows job passed 574 tests on four logical CPUs (4.341 s pytest session; 5.254 s test-step wall time), plus lint, format, strict typing, decision IDs, Conventional Commit/PR title checks, version preview, sdist/wheel and isolated import. Linux passed 530 portable tests in 2.512 s and macOS passed 530 in 3.589 s; both also passed locked setup and packaging/import checks. CPython was 3.14.10. These are individual observed runs, not controlled benchmarks. Current D161 text still specifies two vCPU; the maintainer has directed a separate four-vCPU amendment, pending review. Once merged, this run is the baseline-hardware measurement against the five-minute target (verify then). Earlier [main dispatch 45771751629](https://github.com/heaje/muteinous/actions/runs/45771751629) tested `f3b3523` (Windows 570 tests, 46.536 s on four logical CPUs; Linux/macOS 524 portable); [PR #41 run 45771353335](https://github.com/heaje/muteinous/actions/runs/45771353335) is historical. Actions availability is restored.

| Outstanding gate | Evidence and completion criteria |
| --- | --- |
| **D161 baseline transition and timeout negative control** | Current D161 text names a two-vCPU Windows baseline; CI on this public repository runs 4 vCPU ([run 45863237303](https://github.com/heaje/muteinous/actions/runs/45863237303): 4 logical CPUs, 574 passed, 4.341 s session). Maintainer directed the baseline be changed to four vCPU; amendment pending via a separate reviewed PR. Once merged, this run is the baseline-hardware measurement against the five-minute target (verify then). The deliberate timeout negative control remains separate and in progress under maintainer authorization; verify step and job fail independently of job timeout and record diagnostics. |
| **D166 live release acceptance** | In progress by other agents under maintainer authorization; no results recorded here. Exercise development-build and alpha/beta/RC/stable draft acceptance, artifact download/metadata, SHA/version/checksums/notes/prerelease flag, transfer, permissions and abandoned-draft recovery without publishing. |
| **Dependabot, D164–D165** | Read-only settings check 2026-11-26: alerts/security fixes remain disabled; automated security fixes `enabled=false`; vulnerability-alert API reports disabled (404). MAINTAINER will enable alerts and security fixes; this remains a maintainer action, not completed. Also verify weekly recurrence, grouped PR titles and compatibility with bundled uv; existing individual update runs do not prove recurrence. |
| **Architecture confirmation** | [Issue #5](https://github.com/heaje/muteinous/issues/5) criterion: maintainer confirmation that decisions match the approved original architecture discussion remains open. |
| **BLAKE3 benchmark/advisory follow-up** | In progress in a separate PR/work unit; no results recorded here. Cold-cache measurement plus Linux/macOS benchmark repeat and security-advisory recheck remain pending. Existing benchmark was warm-cache, synthetic and one Windows machine. |
| **Frozen-application notice/redistribution audit** | Before redistribution, inspect the actual dependency/binary graph and required notices; the earlier audit did not inspect all crate notices, parse the SBOM or inspect binary features. A minimal frozen-app smoke test is not a release build. |
| **#20 retained branch checks** | Still outstanding: locked Windows rerun on retained branch, native Linux/macOS reproduction, package-exclusion check, and any checks applicable only to experiment code absent from main. Current PR CI covers main's portable subset, not the retained experiment or nonportable Linux/macOS tests. The four-vCPU baseline amendment is tracked separately above. |
| **Per-issue checks outside current CI** | See issue matrix below. Current Windows full suite and Linux/macOS portable subsets satisfy only those exact scopes; unmarked/nonportable cases were not run on Linux/macOS. |

### M1 historical deferrals: current-run disposition

Run [45863237303](https://github.com/heaje/muteinous/actions/runs/45863237303) executes the entire current test suite on Windows and only `@pytest.mark.portable` tests on Linux/macOS, plus locked environment/package checks. The same policy is documented in [testing.md](../docs/testing.md#mandatory-portability-checks--d165). Thus “current-main full Windows” and “portable Linux/macOS” are satisfied on the PR #43 tree (not exact main); “Linux/macOS execution” means portable tests only, not the whole suite, locked native experiment runtime, or every platform-specific case.

| Historical item | Now satisfied by exact evidence | Still open / not established |
| --- | --- | --- |
| **#16** | Full Windows suite and portable Linux/macOS subset on PR #43 tree; identity/model tests are included in the full suite (run log and portable markers). | Nonportable Linux/macOS tests; any claim beyond the tested synthetic-merge tree. |
| **#17** | Full Windows and portable Linux/macOS suites, including the portable fingerprint test module `tests/unit/infrastructure/sources/test_fingerprints.py` and locked build/import path (run log and module-level portable marker). This exercises the locked BLAKE3 runtime on the Linux/macOS portable jobs. | Cold-cache and cross-platform benchmark; advisory recheck; frozen-app notices. |
| **#18** | Full Windows and portable Linux/macOS suites; speech tests declare portable (`tests/unit/models/test_speech.py`). | Provider/integration behavior not implemented; nonportable tests/platform cases and exact-main execution. The earlier unlocked focused reviewer run remains historical, not required locked validation. |
| **#19** | Full Windows and portable Linux/macOS suite for marked scratch/PCM cases. | Nonportable Linux/macOS cases, native tools/format compatibility, and exact-main execution. |
| **#20** | Main's portable tests and full Windows suite only; no equivalence to experiment validation. | Retained-branch locked Windows rerun, native Linux/macOS probes, experiment package exclusions, and baseline-hardware timing after the D161 amendment merges; no game-loader/install claim. |
| **#21** | Full Windows and portable Linux/macOS test suites; `tests/integration/jobs/test_job_queue_scheduling.py` is portable and includes the capacity-release regression. | Provider/persistence/real shutdown/stall integrations are not implemented; nonportable platform cases and exact-main execution. |
| **#22** | Full Windows and portable Linux/macOS tests for portable storage behavior. | POSIX-specific/nonportable cases, exact-main execution and supported-filesystem claims beyond tested coverage. |

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

Independent static/read-only reviews at main `a46bada` (not code execution): R1 #16–22 acceptance audit found no actionable findings and verified #20 branch ancestry/documentation-only delta; native probes were not rerun. R2 cross-module review found no findings; queue capacity-revision restart and `test_capacity_release_during_validation_restarts_fifo` were checked. R3 canonical architecture review found no findings. R4 PR #43 delta review is recorded at [PR #43 comment](https://github.com/heaje/muteinous/pull/43#issuecomment-7198925281); its reported P2 test-isolation concern was rejected by the supervisor and MAINTAINER directed no restoration; it is not an outstanding action. R5 M0 infrastructure review found no findings. PR #41 post-merge review is recorded at [PR #41 comment](https://github.com/heaje/muteinous/pull/41#issuecomment-7198951004), no findings. **PR #41 and #43 merged without pre-merge recorded independent review**—a historical process deviation; later post-merge reviews do not erase it. Reviews were static and do not replace execution evidence.

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
