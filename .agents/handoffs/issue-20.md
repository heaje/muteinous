# Issue #20 / draft PR #25 handoff - AST and Ogg Vorbis specimens

Related: [Issue #20](https://github.com/heaje/muteinous/issues/20), [draft PR #25](https://github.com/heaje/muteinous/pull/25), [PR #27](https://github.com/heaje/muteinous/pull/27) (Issue #19, merged).

Branch `m1/issue-20-native-format-poc`, rebased onto `main` after #27 / #19 was squash-merged; PR #25 targets `main`. All work is committed and pushed; the PR description records the exact pushed head, base and the local validation results. Verify them with `git rev-parse HEAD` and `git merge-base HEAD origin/main` rather than trusting this note.

## State

- Two isolated, synthetic experiments use the real shared `PCMFormat` / `audio_scratch` / `WaveStorage` / `Scratch.edit` boundary: [AST](../../experiments/native_ast/README.md) (lossless Nintendo-console PCM16 container, byte-exact) and [Ogg Vorbis](../../experiments/native_ogg/README.md) (lossy, Windows-relevant loose standard container, measured tolerances and padded edits).
- Required tests cover only safety-critical shared-editor integration behavior, use injected fake codecs, need no FFmpeg, and never skip. Run the manual scripts from the repository root:
  - Windows: `.venv/Scripts/python.exe -m experiments.native_ast.probe`, `.venv/Scripts/python.exe -m experiments.native_ast.shared_edit`, `.venv/Scripts/python.exe -m experiments.native_ogg.probe`, `.venv/Scripts/python.exe -m experiments.native_ogg.shared_edit`.
  - POSIX: `.venv/bin/python -m experiments.native_ast.probe`, `.venv/bin/python -m experiments.native_ast.shared_edit`, `.venv/bin/python -m experiments.native_ogg.probe`, `.venv/bin/python -m experiments.native_ogg.shared_edit`.
- `experiments/` is covered by `task lint`, `format-check` and `typecheck`; it is excluded from the wheel and sdist.
- No production adapter, game-facing write, dependency change, loader trial or title-specific rule.

## Remaining before merge (coordinator-owned steps marked *)

1. Already done: #27 / #19 merged; only the #20 commits were replayed onto `main`, PR #25 was retargeted, and `task setup`, `task check` and the four manual scripts were rerun locally on the merged upstream. If `main` has moved since, rebase again and repeat.
2. Remote CI and Linux/macOS behaviour have not been observed; local evidence is Windows only. The FFmpeg wrapper's POSIX process-tree termination path (`start_new_session`/`killpg`) is unexercised on Linux/macOS. Preserve the outstanding infrastructure verification tracked in [#4](https://github.com/heaje/muteinous/issues/4).
3. Remove this handoff and its pointer in [`README.md`](README.md); retire or promote the two findings (`ast-pcm-roundtrip.md`, `vorbis-lossy-roundtrip.md`) per [the finding lifecycle](../README.md#reusable-findings).
4. *Decision-coverage ledger, coordination snapshot, merge and issue closure belong to the coordinator.

## Not established

Game-loader acceptance, engine banks (Wwise, FMOD, Unity, Unreal), independent decoder agreement, other FFmpeg builds, redistribution licensing of any FFmpeg build (the tested one is GPL-configured and must not be bundled), production bounded-memory streaming and installation safety.
