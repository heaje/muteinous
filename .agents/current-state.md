# Implementation coordination snapshot

**Last reconciled:** 2026-11-24. **Authority:** GitHub Issues, PRs, checked-out code and canonical architecture override this snapshot.

## Current

- [PR #1](https://github.com/heaje/muteinous/pull/1) established the [canonical architecture](../docs/architecture/decisions.md) and evidence ledger.
- M0 repository foundation: [Issue #2](https://github.com/heaje/muteinous/issues/2) and infrastructure phases [#5](https://github.com/heaje/muteinous/issues/5)–[#8](https://github.com/heaje/muteinous/issues/8) are closed; PRs [#3](https://github.com/heaje/muteinous/pull/3), [#9](https://github.com/heaje/muteinous/pull/9), [#10](https://github.com/heaje/muteinous/pull/10), [#11](https://github.com/heaje/muteinous/pull/11), [#12](https://github.com/heaje/muteinous/pull/12) and [#13](https://github.com/heaje/muteinous/pull/13) merged. One installable package, locked Task/uv tooling, Windows full and Linux/macOS portable CI definitions, and draft-first release automation exist. No functional application features have been implemented.
- [Parent #4](https://github.com/heaje/muteinous/issues/4) remains open for outstanding verification: Actions budget/billing block, current-main remote CI, live build/release workflows, inactive main protection, Dependabot activation/live behavior, D161 timeout negative control, and maintainer confirmation of #5 criterion 2. Do not infer verification from merged code or closed phase issues. The [coverage ledger](../docs/architecture/decision-coverage.md) records the partial evidence.

## Next

1. M1 (shared core and safety foundations): foundation-first with early native-format feasibility investigation. Agreed implementation Issues [#16](https://github.com/heaje/muteinous/issues/16)–[#22](https://github.com/heaje/muteinous/issues/22) contain the scope, dependencies and acceptance criteria. Start with #16; independent work may proceed as appropriate. #19 requires the [D06 amendment PR #15](https://github.com/heaje/muteinous/pull/15) to merge before implementation. The GitHub milestone still needs creation and assignment. Build only justified, independently testable components; follow the [work-unit policy](../docs/development.md#work-unit-and-review-policy).
2. Investigate reusable native-format extraction, reconstruction, fidelity and safe installation viability early in M1, in parallel with foundation work where practical, not only at final Apply integration. Keep experiments separate from claims of supported game capability.
3. Proposed subsequent milestones: M2 discovery/scanning, M3 filtering/preview/desktop review, M4 safe Apply/release. Milestone boundaries and issue decomposition remain proposals.
4. Resume infrastructure verification tracked in #4 when available; do not mark deferred requirements verified or close the parent without evidence.

## Cross-task risks

- Actions are reported disabled for budget/billing; current main has not completed remote CI since final PR #12/#13 changes. Use applicable local checks and record verification limits.
- Keep requirements self-contained in version-controlled documentation; preserve the [initial-release scope](../docs/release-scope.md) and safety/refusal constraints.
- Native editing and loader/installation safety require verified capability evidence; prior game-specific implementation is not proof.

This file is a short coordination aid. **Live status belongs in Issues/PRs**; verify before choosing work. Do not update it for every branch checkpoint.
