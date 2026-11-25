# Reusable agent workflows

Select the relevant workflow from the requested task. An explicitly named workflow overrides automatic selection, but never expands permissions or approved scope. Ask before proceeding when ambiguity materially changes scope, authorization or deliverables. For other tasks use the [entry point](../../AGENTS.md) and relevant canonical guidance; do not force a workflow.

| Task intent | Workflow | Example |
| --- | --- | --- |
| Implement an Issue | [Implement issue](implement-issue.md) | Implement Issue #21. |
| Independently review an existing PR | [Review PR](review-pr.md) | Independently review PR #26. |
| Review, fix, push, repeat | [Review/fix loop](review-fix-loop.md) | Run a review/fix loop against PR #26. |
| Simplify existing tests | [Cleanup tests](cleanup-tests.md) | Clean up the tests in PR #26. |

Read only the selected workflow (and another if needed for an authorized phase). Each may be explicitly invoked, e.g. “Run `.agents/workflows/review-fix-loop.md` against PR #26.” Model and delegation configuration belong in the task or harness, not the workflow. Follow [role-based discovery](../../docs/development.md#delegation-and-independent-review) and [harness verification](../../docs/agent-discovery.md) as needed.
