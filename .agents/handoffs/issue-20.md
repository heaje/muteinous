# Issue #20 / draft PR #25 handoff - AST and Ogg Vorbis specimens

Related: [Issue #20](https://github.com/heaje/muteinous/issues/20), [draft PR #25](https://github.com/heaje/muteinous/pull/25), [PR #27](https://github.com/heaje/muteinous/pull/27) (Issue #19, upstream).

Branch `m1/issue-20-native-format-poc`, stacked on `feat/m1-4-pcm-scratch-19`. All work is committed and pushed; the PR description records the exact pushed head, upstream base SHA and the local validation results. Verify them with `git rev-parse HEAD` and `git merge-base HEAD origin/feat/m1-4-pcm-scratch-19` rather than trusting this note.

## State

- Two isolated, synthetic experiments use the real shared `PCMFormat` / `audio_scratch` / `WaveStorage` / `Scratch.edit` boundary: [AST](../../experiments/native_ast/README.md) (lossless Nintendo-console PCM16 container, byte-exact) and [Ogg Vorbis](../../experiments/native_ogg/README.md) (lossy, Windows-relevant loose standard container, measured tolerances and padded edits).
- Required tests use injected fake codecs and need no FFmpeg; the real-FFmpeg scripts are manual native-tool checks (`python -m experiments.native_ast.probe`, `.native_ast.shared_edit`, `experiments.native_ogg.probe`, `.native_ogg.shared_edit`).
- `experiments/` is covered by `task lint`, `format-check` and `typecheck`; it is excluded from the wheel and sdist.
- No production adapter, game-facing write, dependency change, loader trial or title-specific rule.

## Remaining before merge (coordinator-owned steps marked *)

1. Merge order: PR #27 / Issue #19 first. After its squash merge, replay only the #20 commits onto current `main`, retarget PR #25 to `main`, rerun `task setup` and `task check` plus the four manual scripts on the exact merged upstream.
2. Remote CI and Linux/macOS behaviour have not been observed; local evidence is Windows only. Preserve the outstanding infrastructure verification tracked in [#4](https://github.com/heaje/muteinous/issues/4).
3. Remove this handoff and its pointer in [`README.md`](README.md); retire or promote the two findings (`ast-pcm-roundtrip.md`, `vorbis-lossy-roundtrip.md`) per [the finding lifecycle](../README.md#reusable-findings).
4. *Decision-coverage ledger, coordination snapshot, merge and issue closure belong to the coordinator.

## Not established

Game-loader acceptance, engine banks (Wwise, FMOD, Unity, Unreal), independent decoder agreement, other FFmpeg builds, redistribution licensing of any FFmpeg build (the tested one is GPL-configured and must not be bundled), production bounded-memory streaming and installation safety.
