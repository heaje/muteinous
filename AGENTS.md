# Coding-agent entry point

This file is a **navigation checklist, not a second architecture or workflow specification**. Use version-controlled project documentation and current repository evidence rather than another agent's conversation as authority.

## Before working

1. Inspect the assigned Issue/PR, checked-out branch, code and tests. To resume unfinished work, follow the [handoff instructions](.agent/README.md#unfinished-work-handoffs). If Issue/PR discussions are inaccessible, obtain the task, exact pushed branch/ref and handoff path from the coordinator.
2. Read the [initial-release scope](docs/release-scope.md) and **applicable original D-number decisions** in the [complete architecture log](docs/architecture/decisions.md). Follow [architecture-documentation governance](docs/development.md#architecture-documentation-governance) for authority, discrepancies or proposed changes.
3. Consult [code organization and dependency boundaries](docs/architecture/code-organization.md) and [testing policy](docs/testing.md) for the affected work. Check [coordination state](.agent/current-state.md) and [reusable technical findings](.agent/README.md#reusable-findings); verify potentially stale findings against the current code.

## While working and handing off

- Follow the [development/PR workflow](docs/development.md#work-unit-and-review-policy), [test requirements](docs/testing.md) and [decision-coverage evidence rules](docs/architecture/decision-coverage.md#updating-this-tracker).
- Use the [agent knowledge-sharing and handoff procedures](.agent/README.md) for cross-task discoveries, concurrent-agent notices, unfinished work and cleanup.
- When documentation references an **existing repository file**, use a relative Markdown link. Keep hypothetical or not-yet-created file paths as code, not broken links.
