# Issue #20 handoff — incomplete

Related: [#20](https://github.com/heaje/muteinous/issues/20), [#19](https://github.com/heaje/muteinous/issues/19); D05–D08, D16, D24, D132–D135, D160.
Branch: `m1/issue-20-native-format-poc`.
Base inspected: `f5ba24e2b5043dad7f6118dee79edb57880adf26`.

The [AST experiment](../../experiments/native_ast/README.md) and [reproducible probe](../../experiments/native_ast/probe.py) are an identity transport investigation only. They succeeded on the available Linux environment; see experiment README for exact output and limitations. No production code, dependency lock, coordination snapshot or coverage ledger changes.

Resume after #19's implementation is merged to main; rebase this branch onto current main and inspect the real editor/storage interface rather than inventing one. Decide whether this narrow AST specimen remains suitable for the final demonstration (it does not establish Windows relevance). Complete shared editing, grouping, all-or-nothing preparation/refusals, independent validation and required tests; run task setup and task check with the pinned environment. Remove this handoff before completion. No game-facing writes, proprietary assets, loader experiment or merge authorization. See the issue/PR for the pushed checkpoint SHA.
