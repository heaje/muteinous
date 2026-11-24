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

Install [uv](https://docs.astral.sh/uv/getting-started/installation/) first. Use Python 3.12 for parity with the [Windows PR workflow](../.github/workflows/pr.yml) (the distribution requires Python 3.11+). From the repository root, create `.venv` and install the package and development extras with uv:

~~~powershell
uv venv --python 3.12 .venv
uv pip install --python .venv/Scripts/python.exe -e '.[dev]'
.\.venv\Scripts\python.exe -c 'import muteinous; print(muteinous.__file__)'
uv build --wheel --out-dir dist
~~~

Run the [local checks](testing.md#local-validation-commands) before opening a PR. Those commands explicitly use `.venv`'s interpreter; activation is not needed. This bootstrap uses uv's pip-compatible environment workflow with bounded tool versions in `pyproject.toml` and no lockfile. The current bootstrap package has no production API and no runtime dependencies. Package subdirectories are added only when justified by [D160](architecture/decisions.md), not as placeholders.

## Approved development and release direction (implementation pending)

Decisions [D163–D166](architecture/decisions.md) specify future Go Task commands, a verified newest-stable Python series and committed uv lock, Conventional Commits/Commitizen and setuptools-scm, Windows-primary and required Linux/macOS portable CI, Dependabot, and manually initiated draft GitHub Releases. These are **planned changes**, tracked in [parent issue #4](https://github.com/heaje/muteinous/issues/4) and phase issues [#5 (architecture)](https://github.com/heaje/muteinous/issues/5), [#6 (tooling/versioning)](https://github.com/heaje/muteinous/issues/6), [#7 (CI/dependencies)](https://github.com/heaje/muteinous/issues/7), and [#8 (builds/releases)](https://github.com/heaje/muteinous/issues/8); they are **not yet the commands or settings of this repository**.

Until the respective phase PRs merge, the explicit Python 3.12 uv commands above and the current [PR workflow](../.github/workflows/pr.yml) describe the actual bootstrap. After adoption, `task setup` must explicitly prepare the locked `.venv`; other Task commands must use it without shell activation and must not silently provision it. `task check` runs routine checks while individual tasks remain available for focused validation and CI reporting. Cross-platform developer commands are distinct from claims of Linux/macOS application support.

The future official release workflow will be manual, build wheels and sdists from each release tag and record source/build metadata and SHA-256 checksums, and produce draft GitHub Releases with Commitizen notes for human review before publication. It will not publish to PyPI or write `CHANGELOG.md`. Development artifacts will also be built and retained only on manual request, using repository-default retention. Refer to [D166](architecture/decisions.md) for prerelease and recovery rules; do not represent any planned mechanism as implemented until verified in its respective PR.

## Architecture documentation governance

The version-controlled [architecture decision log](architecture/decisions.md) is the **self-contained implementation reference for this repository** (adopted as canonical by the merge of PR #1). Contributors should be able to implement, test, review, and propose changes without access to private planning discussions or other external workspaces. If the recorded requirements are missing, ambiguous or contradictory, raise the issue for maintainer review rather than guessing or silently changing a decision. Approved amendments and supersessions must be recorded in the decision log through a reviewed PR, with affected implementation guidance and evidence tracking synchronized. Maintainers are responsible for reconciling earlier planning records; contributors do not need those records.

**Avoid stale copies:** Do not repeat a fixed decision count/range, historical decision statuses or detailed architecture rules in onboarding files, project overviews or coordination notes. Cite the [decision log](architecture/decisions.md) (specific D-numbers only when useful for traceability). Keep [release scope](release-scope.md), [code organization](architecture/code-organization.md) and [testing](testing.md) as focused implementation guidance, not alternative authorities. When a decision changes, review and update only its affected derived guidance and [coverage rows](architecture/decision-coverage.md) in the same documentation synchronization; compare coverage IDs with the current log instead of assuming a permanent last ID.

[Decision coverage](architecture/decision-coverage.md) tracks implementation **and verification**, not merely documentation or work started. Implementation PRs carry current Issue/PR/test evidence; the merger/coordinator reconciles the ledger from accepted evidence rather than asking parallel agents to edit shared rows.

## Agent continuity

Follow [`AGENTS.md`](../AGENTS.md) and [temporary-knowledge instructions](../.agents/README.md): unfinished branch handoffs in Issues/PRs (with a committed branch-local note for repo-only agents), cross-task verified findings under [`.agents/findings/`](../.agents/findings/README.md), and enduring knowledge in permanent docs. Reconcile [`.agents/current-state.md`](../.agents/current-state.md) periodically, not per commit. Never commit proprietary game assets, keys, or unreviewed game-specific compatibility assumptions.
