# Instructions for coding agents

Read this file first. Before implementing a task, read the assigned GitHub Issue/PR, [release scope](docs/release-scope.md), relevant entries in [D01–D161](docs/architecture/decisions.md), [code organization](docs/architecture/code-organization.md), [testing](docs/testing.md), and [agent handoffs](.agent/README.md). Check the actual code and GitHub status; handoffs may be stale.

## Architectural guardrails

- D159 defines the initial release. Do not implement deferred editing features as part of ordinary initial-release tasks.
- D160 defines the one-package layout; add directories/modules when needed, not speculative placeholders.
- D161 defines Windows two-vCPU PR test-runtime targets and safety-critical coverage.
- Preserve source validity, fidelity, explicit Apply, scope completeness, installation ownership, backups, recovery, and conservative failure behavior. Never silently skip required edits, invent timings, claim unsupported coverage, or modify game files during scan/settings/preview.
- No maintained title-specific code, title lists, configuration or fixtures (D132–D133). Native/engine adapters must use observed capabilities and evidence.
- D70 is superseded by D71; do not implement superseded requirements as current.
- The Architecture Decision Log is authoritative for detailed requirements. If a task requires a new architectural choice or conflicts with a decision, flag it for explicit review; do not silently decide or rewrite the log.
- The Space decision log remains canonical until an explicit handoff is approved; repository docs are a reviewable snapshot.

## Work and verification

- Keep changes cohesive and linked to an Issue; use a PR for review, preferably squash-merged.
- Include deterministic tests for changed behavior and safety boundaries. Do not hide failed or slow tests to meet the runtime budget.
- Update [decision coverage](docs/architecture/decision-coverage.md) with actual implementation/test evidence, never marking a decision implemented just because it is documented.
- Before finishing, run applicable checks, state what was run and what was not, and note unresolved risks.

## Shared knowledge and handoff

- Read [.agent/current-state.md](.agent/current-state.md) and task-relevant [.agent/findings/](.agent/findings/) before investigation.
- On interrupted/unfinished work, leave a concise handoff on the relevant Issue or PR: branch/commit, completed work, remaining steps, verification results, blockers, and non-obvious pitfalls.
- Record reusable cross-task discoveries in a focused `.agent/findings/<topic>.md` only if they are evidence-backed and likely to save future agents meaningful time. Include scope, evidence/reproduction, implications, links, and an expiration or verification condition.
- Promote enduring facts to permanent docs; remove obsolete temporary notes. Git history preserves deleted notes.
- GitHub Issues/PRs own task status; architecture docs own requirements; `.agent/` supplies short-lived context. Do not duplicate status everywhere.
- Do not have every concurrent agent rewrite `.agent/current-state.md`; reconcile it at milestone/coordination points or after significant merges.
