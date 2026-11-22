# Coding-agent instructions

This repository is intended to be usable by coding agents **without access to ChatGPT Space**. Read the version-controlled architecture and relevant handoffs, verify the current code, and ask for review when evidence or requirements are insufficient. Do not treat an agent's prior conversation as project authority.

## At the start of every task

1. Inspect the assigned GitHub Issue/PR, checked-out branch, actual code and tests, and any active [task handoff](.agent/README.md#unfinished-work-handoffs). If GitHub Issues/PRs are inaccessible, obtain the task description from the coordinating agent and use the branch's committed handoff.
2. Read [initial-release scope](docs/release-scope.md), [code organization](docs/architecture/code-organization.md), [testing](docs/testing.md), and the **relevant original D-number decisions** in [the complete decision log](docs/architecture/decisions.md).
3. Check [coordination state](.agent/current-state.md) and relevant [temporary findings](.agent/findings/README.md). Notes can be stale: reproduce their critical claims before relying on them.

## Authority and safety

- The full D01–D161 decision text is authoritative for requirements and overrides the short summaries. This checked-in copy is a complete usable snapshot for agents without Space; the Space page remains the formal canonical record until the owner approves a transition. If there is any discrepancy, conflict, or materially new architectural choice, surface it for review rather than silently rewriting a decision.
- **D159 controls release phasing.** The initial release has read-only detected-content review, user-selected safe previews, word lists/settings, user-initiated comprehensive scans, and explicit Apply. Per-occurrence editing, manual ranges, transcript corrections, bulk actions, import/export and Undo/Redo are later-phase work. Do not build their state/UX/infrastructure early.
- **D132–D133 prohibit repository-maintained game-specific implementations or knowledge:** no title/edition/store-ID catalog, per-game mappings, paths, compatibility exception, real-game fixture or imported legacy game adapter. Generic native/engine support must be justified by observed format/installation evidence.
- **D01–D02, D05, D10–D19, D24, D141–D143:** source validity; high-fidelity edits; selected-scope required-edit completeness; shared installation authority; ownership, original backups, restoration and update/running-game protection are non-negotiable. A plugin may stage artifacts but must not write game-facing files. Do not silently drop a required edit or shrink selected scope after preparation fails.
- **D69–D76, D133, D139–D140, D159:** do not invent timestamps, native subtitles, source text, speech roles, associations, safe mod destinations or complete coverage. Report uncertainty and refuse affected Apply when required evidence/authorization is unavailable. A capability permitted by a decision is not automatically mandatory to ship in the first release.
- **D146:** preview is user-driven, based on verified originals and safe PCM intervals; it does not prove native rebuilding, loader acceptance or install safety.
- **D70 is superseded by D71**; preserve the history, implement the active decision.
- **D160:** one `src/muteinous/` package with models/core/plugins/infrastructure/ui; no speculative directories, frozen plugin signatures, arbitrary abstractions or full initial CLI.
- **D161:** test-runtime target and hard test-execution timeout are independent of setup time; do not hide safety-critical tests for speed.

## Delivering a change

- Work in a focused branch/PR linked to its Issue and relevant D-number requirements. Keep commits meaningful; prefer a cohesive, reviewable change and squash merge when approved.
- Add deterministic tests, especially for source freshness, required edits, native/PCM fidelity, install safety and storage integrity where applicable. Do not report missing, skipped or timed-out tests as passed.
- Update [decision coverage](docs/architecture/decision-coverage.md) only with actual implementation or verification evidence. Documentation is **not** implementation.
- In the PR description include: outcome, decisions, changed and excluded scope, tests executed/results, unrun checks, safety implications, and any unresolved issue.

## Prevent knowledge loss

- **While working:** retain reproducible cross-task discoveries in focused `.agent/findings/<topic>.md` notes. Include evidence, caveats, last verified date and the condition that makes the finding obsolete. Keep secrets, actual game assets and speculative statements out of Git.
- **If work is unfinished at handoff:** commit/push useful work to a discoverable branch and leave a concise handoff on the Issue/PR. If the next agent may only have repository access, also commit `.agent/handoffs/<issue-or-task>.md` on the working branch. It must identify the branch, last **tested** commit (if known), completed and unfinished work, reproducible tests/results, blockers, and exact next actions. After pushing, put the final pushed commit SHA in the Issue/PR handoff when available; a branch-local note cannot reliably include the SHA of the commit that contains itself. See [handoff convention](.agent/README.md#unfinished-work-handoffs).
- **When merging/completing:** migrate lasting facts into permanent docs, revise/retire findings and task handoffs, and ensure the PR records final test evidence. Do not archive a long agent diary.
- GitHub Issues/PRs own live task status. `.agent/current-state.md` is a small **periodically reconciled** coordination snapshot, not a document every parallel agent edits.
