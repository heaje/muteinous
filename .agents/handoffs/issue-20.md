# Issue #20 handoff — second native-format specimen

Related: [#20](https://github.com/heaje/muteinous/issues/20), [PR #25](https://github.com/heaje/muteinous/pull/25), [PR #27](https://github.com/heaje/muteinous/pull/27).

Branch: `m1/issue-20-native-format-poc`, stacked on `feat/m1-4-pcm-scratch-19` at `b2ee60a731e506fc2b34083eedf2edd59b947a67`. The AST first-round implementation is committed at `3bfd05d008c09703c3cede1e133acd45db6adf0c`. This second-round Ogg work is in the current working tree and was not committed or pushed by this implementer; the supervisor owns commit/push. `gh pr view 25` still shows an older PR body/base (`db091d4…`) and old “not executed” status; reconcile the PR description/base after the supervisor updates the branch. No upstream-owned source, scripts, existing tests, audio-storage docs, architecture/coverage docs, or `uv.lock` were changed.

## Implemented

- Added isolated `experiments/native_ogg/`: pure-Python Ogg/Vorbis page, CRC, lacing, sequence, packet, header, comment, profile, and granule validator; bounded FFmpeg/libvorbis wrapper; float-PCM preparation and lossy verification; synthetic-only `probe` and `shared_edit` scripts; and reproduction/evidence README.
- Generalized `experiments/native_ast/ast_core.py` minimally: optional `PCMFormat`, native suffix, profile-specific validation and decoded-reconstruction callbacks, and total-frame mapping. AST defaults remain strict/exact. Ogg reuses the existing private preparation, shared scratch, and pre-encode edit-completeness verifier; no adapter/plugin framework was introduced.
- Added portable fake-codec/parser tests in `tests/unit/test_native_ogg.py` and `tests/integration/test_native_ogg_prepare.py`. Tests do not call FFmpeg or skip.
- Reframed the AST README as the lossless structural specimen and cross-linked Ogg as the lossy Windows-relevant specimen. Added a focused Vorbis finding and updated this handoff.

## Local verification

Environment: Windows 11 build `10.0.26300`, CPython `3.14.10`, FFmpeg `n7.1.5-12-g1fdbca85aa-20260731` (BtbN GPL static; `--enable-gpl --enable-version3`). `task.cmd setup` resynchronized the stale editable environment with `uv sync --locked`; no dependency or lock changes.

- New Ogg tests: `39 passed in 0.49s`. Combined AST/Ogg focused tests: `82 passed in 1.31s`. No skips.
- `task.cmd lint`: passed, `All checks passed!`
- `task.cmd format-check`: passed, `38 files already formatted`
- `task.cmd typecheck`: passed, `Success: no issues found in 36 source files`
- `task.cmd test`: `253 passed in 27.44s`; no skips.
- `task.cmd build`: passed; wheel/sdist package validation succeeded and contained no `experiments/` entries.
- Both AST scripts passed; their exact output remains in the [AST README](../../experiments/native_ast/README.md).
- Both Ogg scripts passed; stdout and measured results are in the [Ogg README](../../experiments/native_ogg/README.md). Identity control: 66,150 frames, 128,000-bit/s nominal bitrate, 33.020 dB SNR, maximum absolute error `0.01706610`, Ogg size 27,390 → 26,507 bytes (−883). Edited outside regions: minimum SNR 31.636 dB, maximum absolute error `0.02047877`; both edited cores decoded to peak `0.00000000`.
- Negative controls (deliberately failing, restored afterward): disabling Ogg CRC verification made the named CRC case fail (`1 failed, 24 deselected`); removing the pre-encode edit-completeness call made all three named cases fail their required `EditError` assertion (`3 failed, 11 deselected`); disabling the maximum outside-error tolerance made the named outside-tolerance test fail because it no longer raised (`1 failed, 13 deselected`). Full required checks passed after restoration.

## Limits / supervisor follow-up

This is a loose standard Ogg Vorbis container, not Wwise/FMOD/Unity/Unreal or another engine bank. Only synthetic stereo/44.1-kHz input and this Windows FFmpeg build were exercised. The parser does not decode Vorbis setup/audio packets. No independent decoder, Linux/macOS shared-edit, other FFmpeg builds, game loader, installation, production support, or license/redistribution conclusion is verified. The tested FFmpeg binary is GPL-configured; do not redistribute it with Muteinous. Vendor strings may change (the pinned same-build run happened to keep `Lavf61.7.103`); re-encoding is lossy and must not be called bit-exact or perceptually transparent.

Supervisor should commit/push the working tree, refresh PR #25's stale base/body and report final commit/remote CI. Do not merge this stacked PR before #19/#27; do not modify upstream-owned files or the shared decision/coverage ledger in this handoff.
