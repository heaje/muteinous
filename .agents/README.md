# Temporary implementation knowledge

This directory is a **time-limited knowledge exchange between coding agents**, not a second architecture decision log, task tracker, or permanent diary. Notes are version-controlled and shared through discoverable branches and task handoffs, without depending on an individual agent's conversation history.

## Task-start discovery

Tools do not necessarily discover Markdown files in `.agents/` automatically. On **every new or resumed task**, after opening [`AGENTS.md`](../AGENTS.md):

1. Read the [coordination snapshot](current-state.md), then verify potentially stale status against the assigned Issue/PR and checked-out code.
2. **Enumerate the files** under [`findings/`](findings/README.md), not just its README, and read findings relevant to the assigned work. Verify their evidence against the current implementation before using them.
3. If resuming unfinished work, use the task's provided branch/ref and handoff path to locate the relevant note under [`handoffs/`](handoffs/README.md). If the pointer is absent, obtain it from the coordinator; a note on another branch is not visible automatically.
4. Before pausing or completing work, consult the [finding lifecycle](#reusable-findings), [handoff rules](#unfinished-work-handoffs) and [cleanup guidance](#coordination-and-cleanup) as applicable.

## Where information belongs

| Kind | Home | Lifetime |
| --- | --- | --- |
| Architectural contract and release policy | [`docs/architecture/decisions.md`](../docs/architecture/decisions.md); [`docs/release-scope.md`](../docs/release-scope.md) | Permanent |
| Live task ownership, progress and acceptance | GitHub Issue / PR | Per task; retained by GitHub |
| Incomplete implementation handoff | Issue / PR; optionally a branch-local `handoffs/<task>.md` ([handoff guidance](handoffs/README.md)) | Until work resumes/completes |
| Reusable, nonobvious technical discovery | `findings/<topic>.md` ([finding guidance](findings/README.md)) | Until incorporated, disproved or irrelevant |
| Cross-task next steps and blockers | [`current-state.md`](current-state.md) | Reconciled periodically |
| Enduring setup, tooling or testing procedure | [`docs/development.md`](../docs/development.md); [`docs/testing.md`](../docs/testing.md) | Permanent |

Never use these notes to override the [architecture decision log](../docs/architecture/decisions.md) or infer that an unverified suggestion is implemented. Read only findings relevant to the task and verify against the code.

## Reusable findings

Create a separate focused Markdown file in [`findings/`](findings/README.md) only when a discovery would save another agent meaningful investigation. Prefer an actionable conclusion and **reproducible evidence** over a transcript of attempts.

Suggested structure:

```markdown
# Short topic
Status: active | resolved | superseded
Last verified: YYYY-MM-DD
Related: issue/PR, decision IDs, code or test paths
Retire/promote when: a concrete fix, verification, or date/event occurs

## Finding and limitations
What is known; where it applies; what is still uncertain.

## Reproduction / evidence
Commands, conditions, measurements, failure text, and links as appropriate.

## Recommendation
The next investigation or implementation step.
```

Do not commit passwords, keys, personal details, machine-specific confidential paths, private game assets, or giant logs. A finding can be unverified, but label it **hypothesis**, not conclusion.

**Cross-branch visibility:** A finding committed only on one feature branch is not visible on other branches. When a discovery may affect other active work, promptly post a short notice in an existing relevant shared Issue/PR discussion: symptom, reproduction/evidence, affected tasks, and the branch/commit containing the detailed finding. If another agent cannot access those discussions, the coordinator must pass the notice and the relevant ref in that agent's task assignment. Do not open a new tracking Issue for every small observation.

## Unfinished-work handoffs

When pausing incomplete work, write a short handoff on the related Issue or PR. For repository-only agents, commit a **task-specific branch-local file** in [`handoffs/`](handoffs/README.md) so the next agent can recover without needing the original chat or GitHub comments. A branch-local file cannot be found merely by inspecting `main`: **the incoming agent must receive the exact pushed branch/ref and handoff path** through an accessible Issue/PR or its task assignment. When GitHub discussions are inaccessible, the coordinator supplies this pointer directly. The branch note is a portability fallback, **not a competing global status source**.

Include:
- Task/Issue and PR link (if present); **exact branch name**, and the last **tested or predecessor** commit SHA when useful. A committed handoff file cannot know the SHA of the commit containing itself: verify actual branch HEAD with `git rev-parse HEAD` after checkout, and put the final pushed SHA in the Issue/PR comment after pushing.
- Implemented changes and files touched; decisions or acceptance criteria already addressed.
- Remaining concrete steps, known blockers and unresolved risks.
- Reproduction commands, test outputs and tests **not** run.
- Relevant findings and any assumptions that still need verification.

Before handing off, push a checkpoint commit if safe and possible; uncommitted local work is not transferable. Verify that the branch/ref was pushed and that the incoming agent has its pointer; do not claim that a handoff file on another branch is visible on `main`. Remove obsolete branch-local handoffs before merge or when the task is completed; Git history preserves them.

## Coordination and cleanup

The coordinator updates [`current-state.md`](current-state.md) after substantial merges/milestone reviews, not after each agent action; avoid concurrent edit conflicts. At those reviews, verify Issue/PR statuses and the latest branch evidence. A PR that fixes a documented workaround should retire/delete its temporary finding, or mark it resolved/superseded with a link to the fix, so stale advice is not left active. Promote enduring fixes into permanent docs, close the corresponding Issue or PR, and delete obsolete findings/handoffs. Keep the directory small; **a discovery is valuable, not its chronological investigation log**.
