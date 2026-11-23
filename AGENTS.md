# Coding-agent entry point

This file is a **navigation checklist, not a second architecture or workflow specification**. Use version-controlled project documentation and current repository evidence rather than another agent's conversation as authority.

## Before working

1. Inspect the assigned Issue/PR, checked-out branch, code and tests. For resumed work, obtain the exact pushed branch/ref and handoff pointer from the task, Issue/PR, or coordinator.
2. Complete the [task-start agent-note discovery](.agents/README.md#task-start-discovery) on every new or resumed task, even when your coding tool automatically loads `AGENTS.md`.
3. Read the [initial-release scope](docs/release-scope.md) and **applicable original D-number decisions** in the [complete architecture log](docs/architecture/decisions.md). Follow [architecture-documentation governance](docs/development.md#architecture-documentation-governance) for authority, discrepancies or proposed changes.
4. Consult [code organization and dependency boundaries](docs/architecture/code-organization.md) and [testing policy](docs/testing.md) for the affected work.

## While working and handing off

- Follow the [development/PR workflow](docs/development.md#work-unit-and-review-policy), [test requirements](docs/testing.md) and [decision-coverage evidence rules](docs/architecture/decision-coverage.md#updating-this-tracker).
- Before pausing or completing work, follow the [agent knowledge-sharing and handoff procedures](.agents/README.md) for findings, cross-task notices, handoffs and cleanup.
- When documentation references an **existing repository file**, use a relative Markdown link. Keep hypothetical or not-yet-created file paths as code, not broken links.
