# Temporary agent working knowledge

This directory is **not an architecture source of truth** and is **not a replacement for GitHub Issues/PRs**. It prevents repeated investigation across agents and sessions.

## Read order

1. The assigned Issue or PR and current branch/code.
2. `AGENTS.md`, applicable architecture/release/testing docs.
3. `current-state.md` and only the relevant topic findings.

## What goes where

| Knowledge | Location |
| --- | --- |
| Enduring requirement or decision | `docs/architecture/` |
| Task ownership, progress, acceptance, unfinished branch handoff | GitHub Issue/PR |
| Cross-task discovery, reproduction, pitfalls, temporary workaround | `.agent/findings/<topic>.md` |
| Near-term cross-task coordination | `current-state.md` |
| Enduring developer or test procedure | `docs/development.md` or `docs/testing.md` |

## Finding template

Use only when a finding is useful; do not create placeholder files.

```md
# Topic
Status: active | resolved | superseded
Relevant: Issue/PR links, decision IDs
Last verified: YYYY-MM-DD
Retire or promote when: <specific condition>

## Finding and scope
<what is actually known; where it applies>

## Evidence / reproduction
<commands, logs, code paths, measurements, or links>

## Implications / recommended next step
<actionable guidance, caveats, unknowns>
```

Do not store credentials, personal information, huge logs, or speculation presented as fact. Validate old findings against current code. Promote durable knowledge into permanent docs, then delete the temporary finding. Prefer short, topic-specific notes over agent diaries.

## End-of-session handoff for unfinished work

Post to the Issue or PR: current branch and commit, what changed, next concrete steps, tests run/results, blockers, and links to relevant findings. Do this even if the work is not PR-ready. Git history and Issue/PR comments preserve history; do not create a permanent journal.

`current-state.md` is coordinated after significant merges or milestone reviews to avoid concurrent-agent merge conflicts.
