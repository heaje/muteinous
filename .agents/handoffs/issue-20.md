# Issue #20 handoff — stacked, incomplete

Related: [#20](https://github.com/heaje/muteinous/issues/20), [#19](https://github.com/heaje/muteinous/issues/19), [PR #25](https://github.com/heaje/muteinous/pull/25), [PR #27](https://github.com/heaje/muteinous/pull/27).
Branch: `m1/issue-20-native-format-poc`; stacked on `feat/m1-4-pcm-scratch-19` at `db091d4f97713178bf6ba2dd52cc4ed7cf3331cc`.

The [AST experiment](../../experiments/native_ast/README.md) records a previously executed identity round trip. The [stacked integration](../../experiments/native_ast/shared_edit.py) now calls upstream's actual PCM and scratch API; not yet executed. No production code, dependency lock, shared snapshot or coverage ledger changes.

Run the integration, add routine deterministic safety tests, run pinned Task validation and assess Windows relevance before completion. Coordinate upstream API changes via PR #27; keep the stack rebased with an explicit upstream SHA. After #19 squash-merges, replay only #20 commits onto main, retarget #25 and rerun validation. Do not merge #20 first. Remove this handoff on completion. No loader or game-facing writes. See PR for pushed SHA.
