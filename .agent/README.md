# Temporary implementation knowledge

This directory is a **time-limited knowledge exchange between coding agents**, not a second architecture decision log, task tracker, or permanent diary. Its files are version-controlled so agents without ChatGPT Space or issue-comment access can benefit from earlier work.

## Where information belongs

| Kind | Home | Lifetime |
| --- | --- | --- |
| Architectural contract and release policy | `docs/architecture/`; `docs/release-scope.md` | Permanent |
| Live task ownership, progress and acceptance | GitHub Issue / PR | Per task; retained by GitHub |
| Incomplete implementation handoff | Issue / PR **and optionally a branch-local `handoffs/<task>.md`** | Until work resumes/completes |
| Reusable, nonobvious technical discovery | `findings/<topic>.md` | Until incorporated, disproved or irrelevant |
| Cross-task next steps and blockers | `current-state.md` | Reconciled periodically |
| Enduring setup, tooling or testing procedure | `docs/development.md`; `docs/testing.md` | Permanent |

Never use these notes to override D01–D161 or infer that an unverified suggestion is implemented. Read only findings relevant to the task and verify against the code.

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

## Unfinished-work handoffs

When pausing incomplete work, write a short handoff on the related Issue or PR. For repository-only agents, commit a **task-specific branch-local file** in [`handoffs/`](handoffs/README.md) so the next agent can recover without needing the original chat or GitHub comments. Prefer an Issue/PR comment when available; the branch note is a portability fallback, **not a competing global status source**.

Include:
- Task/Issue and PR link (if present); **exact branch name**, and the last **tested or predecessor** commit SHA when useful. A committed handoff file cannot know the SHA of the commit containing itself: verify actual branch HEAD with `git rev-parse HEAD` after checkout, and put the final pushed SHA in the Issue/PR comment after pushing.
- Implemented changes and files touched; decisions or acceptance criteria already addressed.
- Remaining concrete steps, known blockers and unresolved risks.
- Reproduction commands, test outputs and tests **not** run.
- Relevant findings and any assumptions that still need verification.

Before handing off, push a checkpoint commit if safe and possible; uncommitted local work is not transferable. Do not claim that a handoff file on another branch is visible on `main`. Point the incoming agent to the right branch/PR. Remove obsolete branch-local handoffs before merge or when the task is completed; Git history preserves them.

## Coordination and cleanup

The coordinator updates `current-state.md` after substantial merges/milestone reviews, not after each agent action; avoid concurrent edit conflicts. At those reviews, verify Issue/PR statuses and the latest branch evidence. Promote enduring fixes into permanent docs, close the corresponding Issue or PR, and delete obsolete findings/handoffs. Keep the directory small; **a discovery is valuable, not its chronological investigation log**.
