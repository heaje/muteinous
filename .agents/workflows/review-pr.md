# Independently review a PR

Review only: do not edit implementation or tests, push corrections, or merge unless separately authorized.

1. Complete [full-task discovery](../README.md#task-start-discovery). Inspect PR metadata, exact head/base SHAs, diff, Issue, acceptance criteria, applicable decisions and relevant review history; confirm the actual comparison base. Use an isolated checkout for validation where possible.
2. Independently assess changed behavior and affected callers, safety, integrity, concurrency, failure handling, scope and maintainability as applicable. Review tests against [contract-based testing](../../docs/testing.md#contract-based-testing), not arbitrary coverage or mutation targets.
3. Evaluate each proposed finding under the [actionable review criteria](../../docs/development.md#actionable-review-findings); corroborate evidence, reachability, impact and minimal correction. Use focused delegation only where useful and follow the [role policy](../../docs/development.md#delegation-and-independent-review).
4. Run relevant validation without changing the PR. Record commands, outcomes, limitations and whether head/base moved; reassess material changes before issuing a current verdict.
5. Report exact reviewed revisions, confirmed findings in consequence order with file/line evidence, any valuable nonblocking improvements separately, criteria/decision coverage, validation and a merge-readiness verdict (ready, changes required, or blocked by missing evidence). Do not equate no findings with passing unperformed checks. A reviewer of their own changes cannot claim independent review.
