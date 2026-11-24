# Development and implementation workflow

This guide records enduring contribution and review practices. Consult the [coordination snapshot](../.agents/current-state.md) and linked GitHub Issues/PRs for current work, proposed milestones, setup status and unfinished tasks; do not infer their existence from this guide.

## Work unit and review policy

- Prefer **cohesive feature/safety Issues**, not one per decision. Each Issue should identify goals, relevant decisions, acceptance/verification evidence, dependencies, and excluded/deferred features.
- Organize milestones in GitHub as useful for the actual implementation. Investigate reusable native-format reconstruction and safe installation viability early, not only during final Apply integration.
- Use a focused branch and testable PR for each coherent implementation slice. A few meaningful commits or local checkpoints are fine; **squash merge preferred** to avoid noisy permanent history. Parallel agents should avoid editing shared architecture/coordination files simultaneously.
- PR descriptions: purpose and Issue, affected D-number decisions with actual implementation/verification evidence and unverified parts, scope/exclusions, tests and CI evidence, safety/compatibility implications, and remaining risks. The merger/coordinator reconciles the shared [decision-coverage ledger](architecture/decision-coverage.md) from accepted PR evidence at merge time or promptly afterward; parallel feature branches should not separately maintain the same table. When required checks are in place, review and branch protections should guard merge; don't represent these protections as already configured.

## Repository foundation

When adding initial packaging and CI, follow the [code organization](architecture/code-organization.md) and [CI introduction and early coverage requirements](testing.md#introducing-ci-and-early-coverage). Track bootstrap work in live Issues/PRs and the [temporary coordination snapshot](../.agents/current-state.md), not as permanent progress assertions in this guide.

### Local Python bootstrap

Install [Go Task](https://taskfile.dev/docs/installation), Git and [uv](https://docs.astral.sh/uv/getting-started/installation/) (CI uses uv 0.13.9). Use a full Git checkout including tags. On Windows, Linux or macOS, run from the repository root:

~~~shell
task setup
task check
~~~

The [Taskfile](../Taskfile.yml) explicitly installs the managed Python patch pinned in [`.python-version`](../.python-version), synchronizes the committed [universal lock](../uv.lock), and installs the editable package using the locked build dependencies. Use only the 3.14 minor series; the verified Windows patch is 3.14.10. Update the patch pin deliberately after verifying a newer compatible patch. Routine tasks use the repository-local .venv interpreter directly, never activate a shell, and never install dependencies. Routine checks refuse a missing, incorrect-patch or unsynchronized environment without installing anything; run setup again after switching branches or updating dependencies. For intentional dependency changes, update the constraints in [pyproject.toml](../pyproject.toml), run `uv lock`, review the lock diff and run setup and checks. Do not regenerate the lock as part of routine CI.

Individual commands: `task lint`, `task format-check`, `task typecheck`, `task decisions`, `task test`, `task build`, and `task version-preview`. The build command creates wheel and sdist from a fresh temporary output directory, checks the SCM, sdist, wheel and installed metadata versions, validates an isolated wheel import, and copies the distributions to dist/. Older distributions remain in dist/; use only artifacts from the current build, not a glob over accumulated versions. The clean task removes only reproducible pytest, Ruff and mypy cache directories and does not require setup; it leaves .venv, distributions and unrelated files intact. See [testing policy](testing.md#local-validation-commands).

### Git versions and commits

D166 uses Git tags of the form `v0.2.0` (PEP 440 prerelease tags such as `v0.2.0a1`), setuptools-scm for package metadata, and Commitizen for the next release proposal. No manually maintained project version or changelog. Use Conventional Commits for all new commits and the PR title; e.g. `fix: correct sample boundaries`. The Windows PR workflow validates the full PR commit range and title with Commitizen, not just the squash title. Commitizen’s default nonconventional prefix exemptions are disabled. After setup, check a message locally with `.venv/bin/python -m commitizen check --message "fix: correct sample boundaries"` (Linux/macOS) or `.\\.venv\\Scripts\\python.exe -m commitizen check --message "fix: correct sample boundaries"` (Windows PowerShell).

`task version-preview` shows the current SCM development version and Commitizen's proposed next version without changing files or tags. The preview explicitly answers Commitizen's first-tag prompt without creating a tag. PR CI builds the synthetic merge checkout, so its development version may identify that merge SHA rather than the PR head; official releases must build from their own tag. No eligible increment is a normal result for documentation/build-only changes. Before 1.0, breaking changes normally bump minor (e.g. v0.2.0 followed by a breaking feature proposes 0.3.0; the development package may be 0.2.1.devN+gSHA). Do not run a mutating bump/tag command to preview versions. Graduation to 1.0 requires a reviewed policy change.

### Python compatibility

See [Python compatibility evidence](python-compatibility.md) for the Windows 3.14 selection, the specific 3.15 blockers and remaining runtime validation. The bootstrap has no runtime dependencies; candidate Hushpatch libraries are investigated separately and are not adopted automatically. Tooling portability is not application support.

## Development and release direction

D163–D166 define the work tracked by [parent issue #4](https://github.com/heaje/muteinous/issues/4) and phase issues [#5 (architecture)](https://github.com/heaje/muteinous/issues/5), [#6 (tooling/versioning)](https://github.com/heaje/muteinous/issues/6), [#7 (CI/dependencies)](https://github.com/heaje/muteinous/issues/7), and [#8 (builds/releases)](https://github.com/heaje/muteinous/issues/8). The Windows workflow uses locked Task commands; mandatory Linux/macOS CI, Dependabot, branch protection and release automation are separate phases.

The future official release workflow will be manual, build wheels and sdists from each release tag and record source/build metadata and SHA-256 checksums, and produce draft GitHub Releases with Commitizen notes for human review before publication. It will not publish to PyPI or write `CHANGELOG.md`. Development artifacts will also be built and retained only on manual request, using repository-default retention. Refer to [D166](architecture/decisions.md) for prerelease and recovery rules; do not represent any planned mechanism as implemented until verified in its respective PR.

## Architecture documentation governance

The version-controlled [architecture decision log](architecture/decisions.md) is the **self-contained implementation reference for this repository** (adopted as canonical by the merge of PR #1). Contributors should be able to implement, test, review, and propose changes without access to private planning discussions or other external workspaces. If the recorded requirements are missing, ambiguous or contradictory, raise the issue for maintainer review rather than guessing or silently changing a decision. Approved amendments and supersessions must be recorded in the decision log through a reviewed PR, with affected implementation guidance and evidence tracking synchronized. Maintainers are responsible for reconciling earlier planning records; contributors do not need those records.

**Avoid stale copies:** Do not repeat a fixed decision count/range, historical decision statuses or detailed architecture rules in onboarding files, project overviews or coordination notes. Cite the [decision log](architecture/decisions.md) (specific D-numbers only when useful for traceability). Keep [release scope](release-scope.md), [code organization](architecture/code-organization.md) and [testing](testing.md) as focused implementation guidance, not alternative authorities. When a decision changes, review and update only its affected derived guidance and [coverage rows](architecture/decision-coverage.md) in the same documentation synchronization; compare coverage IDs with the current log instead of assuming a permanent last ID.

[Decision coverage](architecture/decision-coverage.md) tracks implementation **and verification**, not merely documentation or work started. Implementation PRs carry current Issue/PR/test evidence; the merger/coordinator reconciles the ledger from accepted evidence rather than asking parallel agents to edit shared rows.

## Agent continuity

Follow [`AGENTS.md`](../AGENTS.md) and [temporary-knowledge instructions](../.agents/README.md): unfinished branch handoffs in Issues/PRs (with a committed branch-local note for repo-only agents), cross-task verified findings under [`.agents/findings/`](../.agents/findings/README.md), and enduring knowledge in permanent docs. Reconcile [`.agents/current-state.md`](../.agents/current-state.md) periodically, not per commit. Never commit proprietary game assets, keys, or unreviewed game-specific compatibility assumptions.
