# Development and implementation workflow

This guide records enduring contribution and review practices. Consult the [coordination snapshot](../.agents/current-state.md) and linked GitHub Issues/PRs for current work, proposed milestones, setup status and unfinished tasks; do not infer their existence from this guide.

## Engineering principles

Muteinous is an application with controlled internal callers, providers and exposed configuration, not a general-purpose framework. Implement approved requirements and supported behavior using the simplest maintainable solution. Trust controlled callers to honor documented programming contracts; do not add defensive complexity for arbitrary unsupported usage or speculative third-party consumers.

Ownership does not make runtime failures impossible. Validate user-controlled inputs, external/provider data, persisted state and other trust boundaries as required. Handle realistically reachable provider, OS, concurrency, resource and other operational failures; maintain meaningful internal invariants and all established security, data integrity, fidelity, refusal and recovery guarantees. Explicit architectural contracts take precedence; follow [architecture governance](#architecture-documentation-governance) rather than silently reinterpreting them.

## Work unit and review policy

- Prefer **cohesive feature/safety Issues**, not one per decision. Each Issue should identify goals, relevant decisions, acceptance/verification evidence, dependencies, and excluded/deferred features.
- Separate implementation closure from verification completion. Once in-scope implementation, applicable available local checks, documentation and review are accepted, the coordinator may close an implementation Issue whose remaining verification is blocked by external infrastructure, after recording each outstanding requirement in the [coordination snapshot](../.agents/current-state.md#deferred-verification). Link the original Issue/PR, exact checks, evidence and revision, blocker, resumption conditions and completion criteria. An infrastructure tracking parent may also close after transferring every outstanding obligation (including activation/configuration steps); this does not close those acceptance requirements. Do not close issues with unfinished implementation or unresolved actionable defects under this policy. Reopen or file a focused issue if verification exposes missing behavior. Milestone and release acceptance remain separate; required checks, independent review and D161/D165/D166 gates are not waived and unrun checks never count as passing. A documentation-only transfer cannot authorize merging other code without required checks.
- Organize milestones in GitHub as useful for the actual implementation. Investigate reusable native-format reconstruction and safe installation viability early, not only during final Apply integration.
- Use a focused branch and testable PR for each coherent implementation slice. A few meaningful commits or local checkpoints are fine; **squash merge preferred** to avoid noisy permanent history. Parallel agents should avoid editing shared architecture/coordination files simultaneously.
- PR descriptions: purpose and Issue, affected D-number decisions with actual implementation/verification evidence and unverified parts, scope/exclusions, tests and CI evidence, safety/compatibility implications, and remaining risks. The merger/coordinator reconciles the shared [decision-coverage ledger](architecture/decision-coverage.md) from accepted PR evidence at merge time or promptly afterward; parallel feature branches should not separately maintain the same table. When required checks are in place, review and branch protections should guard merge; don't represent these protections as already configured.

### Actionable review findings

For every actionable finding, establish in concise prose:

1. **Contract:** the approved requirement, supported behavior, meaningful invariant or justified engineering expectation violated.
2. **Reachability:** supported operating conditions in which the mechanism can occur, or an explicit contractual violation.
3. **Impact:** a material consequence for the application or maintainers.
4. **Evidence:** precise source references, reproduction or reliable analysis establishing the mechanism.
5. **Correction:** the smallest sufficient correction, without introducing unsupported guarantees.

These are eligibility criteria, not a required five-paragraph report template. Assess severity from actual impact and supported reachability. A synthetic reproduction is valid if it demonstrates a realistic failure mechanism or explicit contractual violation. A meaningful missing test protects a contract, not merely a line or mutation; use the [testing policy](testing.md#contract-based-testing). If an existing test demands unsupported behavior, correct the test rather than expanding production guarantees.

Report confirmed defects and meaningful test deficiencies as actionable findings. Omit speculative concerns, unsupported usage and personal implementation preferences from ordinary review results. Report optional maintainability improvements separately only when materially useful; they do not block completion. Unavailable evidence or checks must be disclosed separately, not presented as confirmed defects or passes.

### Delegation and independent review

- **Supervisor:** owns scope, full discovery, coordination, validation, finding confirmation and completion. Independently evaluate the evidence and minimal correction before authorizing any fix; reviewer consensus or repeated reports alone are insufficient.
- **Independent reviewer:** assess the assigned revision without relying on the implementer's conclusions; report evidence and a scoped verdict. A separate reviewer (agent/session or human) must not be the author of the changes under review.
- **Implementation/fix agent:** implement only assigned requirements or confirmed corrections; report changes, evidence and limitations.
- **Test reviewer:** when useful, examine contract coverage and test quality under the same actionable-finding rules.

The user or execution environment selects models, reasoning effort and concurrency. Use independent subagents when supported and requested; do not hardcode models or presume parent context inheritance.

For **full-task delegation**, supply the role, exact repository/ref, Issue/PR, scope, permissions and applicable workflow; the delegate completes normal [task-start discovery](../.agents/README.md#task-start-discovery). For **focused delegation**, the supervisor performs full discovery and supplies the exact target/ref, bounded assignment, applicable policy/decision links, relevant findings, coordination constraints, expected output and permissions. The delegate must access the universal entry point and applicable sources before acting, verify the target and evidence, and expand discovery if necessary; it need not repeat unrelated full-task reading. Independent review must have access to underlying evidence, not just a supervisor's conclusions.

At assignment start, the supervisor must ensure each delegate has the repository instructions and context applicable to its role and scope. Establish that each delegate has the required sources (e.g. read evidence or a short source acknowledgement); resolve missing access or conflicting instructions before work. Reuse unchanged context within an assignment rather than re-injecting policy each tool call. Do not require lengthy compliance transcripts.

Independent review is a completion gate for implementation, test cleanup and review/fix work. If independent review cannot be obtained, stop at the gate, request it from the maintainer/coordinator, and provide the exact revision, evidence and remaining checks. A pushed checkpoint or draft PR is not completion or merge readiness. A standalone independent review by a reviewer separate from the implementer satisfies the independence requirement for that reviewed scope; do not require a recursive review of every review.

### Review-loop termination

Repeat independent review, supervisor confirmation, minimal fixes and validation until no independently confirmed actionable findings remain within approved scope, supported conditions and documented contracts, and applicable validation requirements are satisfied. Re-review meaningful changes at the resulting revision. No arbitrary cycle limit may leave confirmed actionable defects unresolved. Do not prolong a loop solely for hypothetical hardening, mutation survival, optional improvements, implementation preference, unsupported usage or additional equivalent scenarios.

The supervisor owns termination and must disclose unresolved findings, missing independence, and unavailable or unperformed checks. Stop at a blocked gate and request what is needed; do not substitute a self-review or claim merge readiness without required evidence.

## Local development

Keep packaging and CI aligned with the [code organization](architecture/code-organization.md) and [testing policy](testing.md). Track implementation progress and verification evidence in Issues/PRs and the [coordination snapshot](../.agents/current-state.md).

### Local Python bootstrap

Install [Go Task](https://taskfile.dev/docs/installation), Git and [uv](https://docs.astral.sh/uv/getting-started/installation/) 0.13.6 or newer; 0.13.6 added the pinned managed CPython 3.14.10 (CI uses uv 0.13.9). Use a full Git checkout including tags. On Windows, Linux or macOS, run from the repository root:

~~~shell
task setup
task check
~~~

The [Taskfile](../Taskfile.yml) explicitly installs the managed Python patch pinned in [`.python-version`](../.python-version), synchronizes the committed [universal lock](../uv.lock), and installs the editable package using the locked build dependencies. Use only the 3.14 minor series; the verified Windows patch is 3.14.10. Update the patch pin deliberately after verifying a newer compatible patch. Routine tasks use the repository-local .venv interpreter directly, never activate a shell, and never install dependencies. Routine checks refuse a missing, incorrect-patch or unsynchronized environment without installing anything; run setup again after switching branches or updating dependencies. For intentional dependency changes, update the constraints in [pyproject.toml](../pyproject.toml), run `uv lock`, review the lock diff and run setup and checks. Do not regenerate the lock as part of routine CI.

Individual commands: `task lint`, `task format-check`, `task typecheck`, `task decisions`, `task test`, `task build`, and `task version-preview`. The build command creates wheel and sdist from a fresh temporary output directory, checks the SCM, sdist, wheel and installed metadata versions, validates an isolated wheel import, and copies the distributions to dist/. Older distributions remain in dist/; use only artifacts from the current build, not a glob over accumulated versions. The clean task removes only reproducible pytest, Ruff and mypy cache directories and does not require setup; it leaves .venv, distributions and unrelated files intact. See [testing policy](testing.md#local-validation-commands).

### Git versions and commits

D166 uses Git tags of the form `v0.2.0` (PEP 440 prerelease tags such as `v0.2.0a1`), setuptools-scm for package metadata, and Commitizen for the next release proposal. No manually maintained project version or changelog. Use Conventional Commits for all new commits and the PR title; e.g. `fix: correct sample boundaries`. The Windows PR workflow validates the full PR commit range and title with Commitizen, not just the squash title. Commitizen’s default nonconventional prefix exemptions are disabled. Merge commits from GitHub’s “Update branch” button and default `git revert` subjects fail commit validation; rebase, and use a `revert: ...` subject. After setup, check a message locally with `.venv/bin/python -m commitizen check --message "fix: correct sample boundaries"` (Linux/macOS) or `.\.venv\Scripts\python.exe -m commitizen check --message "fix: correct sample boundaries"` (Windows PowerShell).

`task version-preview` shows the current SCM development version and Commitizen's proposed next version without changing files or tags. The preview explicitly answers Commitizen's first-tag prompt without creating a tag, and treats both no eligible increment and no commits since the latest tag as normal results without suppressing other failures. PR CI builds the synthetic merge checkout, so its development version may identify that merge SHA rather than the PR head; official releases must build from their own tag. No eligible increment is a normal result for documentation/build-only changes. Before 1.0, breaking changes normally bump minor (e.g. v0.2.0 followed by a breaking feature proposes 0.3.0; the development package may be 0.2.1.devN+gSHA). Do not run a mutating bump/tag command to preview versions. Graduation to 1.0 requires a reviewed policy change.

### Python compatibility

See [Python compatibility evidence](python-compatibility.md) for the Windows 3.14 selection, the specific 3.15 blockers and remaining runtime validation. Select and validate actual runtime dependencies as features require them; candidate Hushpatch libraries are not adopted automatically. Tooling portability is not application support.

## CI and release procedures

D163–D166 govern development, dependencies, CI and release procedures. The [PR workflow](../.github/workflows/pr.yml) uses locked Task commands on Windows and focused Linux/macOS portability jobs (see [required checks](testing.md#mandatory-portability-checks--d165)). Consult the [coverage ledger](architecture/decision-coverage.md) for actual verification evidence.

### Dependency maintenance and merge gates

[Dependabot configuration](../.github/dependabot.yml) schedules weekly grouped version updates independently for the uv lock/manifest and GitHub Actions. Security updates are not included in the version-update groups. Enable Dependabot alerts and security updates where available; review security updates promptly and separately. The configured commit prefixes are Conventional Commit types; Dependabot PRs must pass the same commit/title validation and all three CI checks without exemption. Inspect constraints and lock changes, review compatibility implications, and merge deliberately; never enable auto-merge for dependency PRs. The Python patch and explicit uv installer version remain deliberate compatibility pins, not Python package dependencies.

Configure an active ruleset or branch protection for `main`: require pull requests, zero mandatory approving reviews, all three exact check names in the [testing policy](testing.md#mandatory-portability-checks--d165), and prohibit force pushes and deletion (including administrator bypass). For classic branch protection, enable **Do not allow bypassing the above settings**. Use GitHub Actions as the expected check source where offered. Require branches to be up to date with main before merging; rebase rather than introducing nonconventional merge commits. Confirm actual settings and availability in GitHub, rather than treating workflow definitions as enforcement. If private-repository plan or administration permissions prevent configuration, leave the protection criterion open and record the blocker and manual follow-up in the Issue/PR. Verify Dependabot scheduling in GitHub after the config is on the default branch; a feature-branch YAML file alone does not activate it.

### Manual builds and official releases

Follow [D166](architecture/decisions.md). The [manual development-build workflow](../.github/workflows/development-build.yml) builds wheel and sdist from the selected source SHA using the locked Python environment and existing package-validation helper. Download its named artifact under **Actions → run → Artifacts**; it contains the validated distributions, `build-metadata.json`, and `SHA256SUMS`. Retention is the repository's configured Actions default, not a workflow override. These are development builds, not official releases; routine PR checks do not upload retained distributions.

For an official release, use **Actions → Manual official draft release → Run workflow**, normally from `main` (or an intentional `release/*` stabilization branch). Choose alpha, beta, rc, or stable. The [release workflow](../.github/workflows/release.yml) runs the same Windows and Linux/macOS checks against the triggering SHA before preparing a version. [The release helper](../scripts/release.py) checks Conventional Commits after the bootstrap commit. Commitizen proposes the version and prerelease number; `packaging.version.Version` checks canonical PEP 440 tag ordering. The helper rejects channel mismatches, non-increasing or existing tags, divergent history and any 1.0+ version. Graduation to 1.0 requires a separate reviewed policy/configuration change. A stable tag with no eligible new commits cannot create a new release; an existing prerelease can progress without a new source commit.

The preparation job has read-only repository permissions. It creates the proposed tag in its disposable checkout and builds both distributions afresh from that exact tag. For cumulative notes and same-SHA channel promotions, it hides earlier local prerelease tags to avoid ambiguous Git resolution; it never changes remote tags. The stdlib-only draft job verifies transferred checksums and source SHA/tag/version/channel consistency, confirms local and remote tags match, refuses any existing draft or release/tag inventory mismatch, and refuses an already-existing release tag. It creates a **draft** GitHub Release targeting the validated SHA, without creating a remote tag. After upload, it verifies the unique draft, target SHA, asset sizes and GitHub SHA-256 digests against local files, tolerating bounded read-after-write lag. GitHub creates the tag at the draft's target SHA when a maintainer publishes, even if the source branch has moved. Alpha/beta/RC are prereleases; stable is not. Each channel builds fresh wheel and sdist assets, build metadata and a SHA-256 manifest. Generated notes are editable on GitHub, not committed to a changelog.

Before publication, confirm the workflow succeeded, review the draft classification, notes, tag/SHA and metadata, download the assets and verify the checksums (e.g. `sha256sum -c SHA256SUMS` from the download directory, or PowerShell `Get-FileHash -Algorithm SHA256` for each listed file). Edit notes if needed, then explicitly select **Publish release** in GitHub. Nothing publishes automatically. GitHub Releases are the authoritative changelog and sole official wheel/sdist distribution channel; no PyPI or committed `CHANGELOG.md`. Installer selection remains deferred until the desktop application exists.

### Failed or abandoned draft

If a run fails or a draft is abandoned, delete the draft in GitHub (UI or `gh release delete TAG`; confirm the exact draft first), then dispatch a fresh run. No remote tag exists before publication. Publishing a draft creates its tag at the draft's recorded SHA. If a tag was somehow created for an unpublished version, a maintainer must handle its deletion manually and record the action in the Issue/PR. Never move or reuse a published tag or delete a published release.

## Architecture documentation governance

The version-controlled [architecture decision log](architecture/decisions.md) is the **self-contained implementation reference for this repository** (adopted as canonical by the merge of PR #1). Contributors should be able to implement, test, review, and propose changes without access to private planning discussions or other external workspaces. If the recorded requirements are missing, ambiguous or contradictory, raise the issue for maintainer review rather than guessing or silently changing a decision. Approved amendments and supersessions must be recorded in the decision log through a reviewed PR, with affected implementation guidance and evidence tracking synchronized. Maintainers are responsible for reconciling earlier planning records; contributors do not need those records.

**Avoid stale copies:** Do not repeat a fixed decision count/range, historical decision statuses or detailed architecture rules in onboarding files, project overviews or coordination notes. Cite the [decision log](architecture/decisions.md) (specific D-numbers only when useful for traceability). Keep [release scope](release-scope.md), [code organization](architecture/code-organization.md) and [testing](testing.md) as focused implementation guidance, not alternative authorities. When a decision changes, review and update only its affected derived guidance and [coverage rows](architecture/decision-coverage.md) in the same documentation synchronization; compare coverage IDs with the current log instead of assuming a permanent last ID.

[Decision coverage](architecture/decision-coverage.md) tracks implementation **and verification**, not merely documentation or work started. Implementation PRs carry current Issue/PR/test evidence; the merger/coordinator reconciles the ledger from accepted evidence rather than asking parallel agents to edit shared rows.

## Agent continuity

Follow [`AGENTS.md`](../AGENTS.md) and [temporary-knowledge instructions](../.agents/README.md): unfinished branch handoffs in Issues/PRs (with a committed branch-local note for repo-only agents), cross-task verified findings under [`.agents/findings/`](../.agents/findings/README.md), and enduring knowledge in permanent docs. Reconcile [`.agents/current-state.md`](../.agents/current-state.md) periodically, not per commit. Never commit proprietary game assets, keys, or unreviewed game-specific compatibility assumptions.
