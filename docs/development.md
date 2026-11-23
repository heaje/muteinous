# Development and implementation workflow

**State:** documentation handoff in PR #1; Python tooling and CI have **not** been established yet. Do not assume that setup commands, scripts, CI checks, branch protection, milestones or GitHub Projects already exist.

## Work unit and review policy

- Prefer 12–18 initial **cohesive feature/safety Issues**, not one per decision. Each Issue should identify goal, relevant D-number decisions, expected acceptance/verification, dependencies, and excluded/deferred features.
- Suggested milestones (not created): **M0** repository foundation; **M1** shared core and safety; **M2** discovery and scanning; **M3** filtering, preview and desktop review; **M4** safe Apply and initial release. Investigate native-format and installation viability early rather than waiting until M4.
- Use a focused branch and testable PR for each coherent implementation slice. A few meaningful commits or local checkpoints are fine; **squash merge preferred** to avoid noisy permanent history. Parallel agents should avoid editing shared architecture/coordination files simultaneously.
- PR descriptions: purpose and Issue, affected D-number decisions with actual implementation/verification evidence and unverified parts, scope/exclusions, tests and CI evidence, safety/compatibility implications, and remaining risks. The merger/coordinator reconciles the shared [decision-coverage ledger](architecture/decision-coverage.md) from accepted PR evidence at merge time or promptly afterward; parallel feature branches should not separately maintain the same table. When required checks are in place, review and branch protections should guard merge; don't represent these protections as already configured.

## PR 1 — documentation handoff

- Complete, source-faithful **D01–D161** snapshot including D70 supersession and D159 deferrals.
- Usable, offline agent onboarding: [`AGENTS.md`](../AGENTS.md), [release scope](release-scope.md), [code organization](architecture/code-organization.md), [test policy](testing.md), [decision coverage](architecture/decision-coverage.md), and [temporary continuity](../.agent/README.md).
- Task-specific handoff and cross-task finding lifecycle, including cleanup and promotion to permanent docs.
- Documentation-only: no code/test infrastructure or new architectural decisions. Review the snapshot and references; **merging does not itself declare a canonical-source transition**.

## PR 2 — minimal package and Windows CI

After PR 1 review, add `pyproject.toml`, `src/muteinous/__init__.py`, minimal `tests/unit/` smoke test, and Windows two-vCPU GitHub Actions workflow, with ordinary lint/type checking only as justified. Validate editable/installable package and test discovery. Enforce a **failing ~600-second test-process timeout** separate from setup/job timeouts and measure test runtime/slow tests. Do not download models in mandatory PR checks. Include representative deterministic safety integration tests **as each actual feature is implemented** (D160–D161), not invented during empty scaffolding.

## Architecture documentation governance

[Decision log](architecture/decisions.md) contains a complete snapshot of the Space page as read on 2026-11-22. The Space page remains formally canonical until an **explicitly approved and synchronized** transition; do not assume that merging PR 1 performs it. Agents without Space should implement from the repository copy, escalate apparent conflicts/missing requirements, and **not guess or silently revise agreed decisions**. While Space is canonical, a change to decision text must be agreed there first and synchronized through a reviewed Git PR. Once Git becomes authoritative, adopt a separately agreed decision-amendment workflow.

[Decision coverage](architecture/decision-coverage.md) tracks implementation **and verification**, not merely documentation or work started. Implementation PRs carry current Issue/PR/test evidence; the merger/coordinator reconciles the ledger from accepted evidence rather than asking parallel agents to edit shared rows.

## Agent continuity

Follow [`AGENTS.md`](../AGENTS.md) and [temporary-knowledge instructions](../.agent/README.md): unfinished branch handoffs in Issues/PRs (with a committed branch-local note for repo-only agents), cross-task verified findings under [`.agent/findings/`](../.agent/findings/README.md), and enduring knowledge in permanent docs. Reconcile [`.agent/current-state.md`](../.agent/current-state.md) periodically, not per commit. Never commit proprietary game assets, keys, or unreviewed game-specific compatibility assumptions.
