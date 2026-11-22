# Development and implementation workflow

The repository is currently documentation-first; actual environment setup commands and dependencies will be established in scaffolding/CI PR 2. Do not assume a Python toolchain, test command, or UI framework is already configured.

## Proposed PR sequence

1. **Documentation PR 1**: complete D01–D161 snapshot, scope, organization, testing, agent guidance, and temporary knowledge conventions.
2. **Scaffolding/CI PR 2**: minimal installable Python package, project metadata, import smoke test, and Windows two-vCPU CI with a hard test-execution timeout.
3. Cohesive, testable implementation slices; investigate native-format reconstruction and safe installation risks early.

## GitHub conventions

Use GitHub Issues for actionable deliverables and acceptance criteria; reference applicable D-number decisions and tests. Suggested milestones: M0 Foundation, M1 Shared Core and Safety, M2 Discovery and Scanning, M3 Filtering/Preview/Desktop Review, M4 Safe Apply/Initial Release. Keep PRs reviewable and cohesive; local checkpoint commits are fine, with squash merging preferred. PR descriptions should state purpose, decisions, included/excluded scope, test evidence, and safety impact.

Use a decision-coverage table to link requirements to implementation and verification; documentation alone does not mean implemented. Do not copy legacy game-specific adapters or fixtures. Check licensing and provenance before any code reuse.

## Agent continuity

Read [AGENTS.md](../AGENTS.md) and [.agent/README.md](../.agent/README.md). Put unfinished-branch handoffs on Issues/PRs, reusable temporary findings in `.agent/findings/`, and enduring facts in permanent documentation. Do not treat stale notes as authoritative.

## Architecture source-of-truth transition

The Space log remains canonical until explicit approval of a Git-based source-of-truth transition. Proposed amendments require review; do not silently rewrite agreed decisions.
