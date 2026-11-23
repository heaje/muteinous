# Implementation coordination snapshot

**Last reconciled:** 2026-11-22. **Authority:** GitHub Issues, PRs, checked-out code and canonical architecture override this snapshot.

## Current

- The architecture is recorded in the [decision log](../docs/architecture/decisions.md); the implementation-readiness assessment at this reconciliation was **ready with nonblocking open items** (see the "Still open" notes within individual decisions).
- [PR #1](https://github.com/heaje/muteinous/pull/1) introduced the architecture log, agent-continuity conventions and the initial coverage ledger.
- No functional Muteinous v2 application implementation or required PR CI has been committed to `main` as of this reconciliation.

## Next

1. Review the completeness of the [repository decision log](../docs/architecture/decisions.md) and handoff conventions; publish any approved corrections through the [documentation review process](../docs/development.md#architecture-documentation-governance).
2. Use a separate bootstrap PR for `pyproject.toml`, `src/muteinous/__init__.py`, a minimal `tests/unit/` smoke test, and Windows two-vCPU CI. Validate package installation and test discovery, and enforce an independently failing ~600-second test-process timeout following the [CI introduction policy](../docs/testing.md#introducing-ci-and-early-coverage). This is a proposal, not an existing workflow or passing check.
3. Plan roughly 12–18 cohesive feature/safety Issues rather than one Issue per decision; possible milestones are M0 repository foundation, M1 shared core/safety, M2 discovery/scanning, M3 filtering/preview/desktop review, and M4 safe Apply/release. These Issues/milestones are **not yet created**; verify GitHub before treating them as live.
4. Investigate reusable native-format reconstruction, fidelity and safe installation viability **early**, not only at final Apply integration.

## Cross-task risks

- Keep implementation requirements and contributor instructions self-contained in version-controlled repository documentation.
- Supported native editing and loader/installation safety require actual verified capability evidence; do not assume an earlier game-specific implementation provides it.

This file is a short coordination aid. **Live status belongs in Issues/PRs**; verify before choosing work. Do not update it for every branch checkpoint.
