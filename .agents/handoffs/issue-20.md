# Issue #20 handoff — implementation evidence, review pending

Related: [#20](https://github.com/heaje/muteinous/issues/20), [#19](https://github.com/heaje/muteinous/issues/19), [PR #25](https://github.com/heaje/muteinous/pull/25), [PR #27](https://github.com/heaje/muteinous/pull/27).

Branch: `m1/issue-20-native-format-poc`, stacked on `feat/m1-4-pcm-scratch-19` at `db091d4f97713178bf6ba2dd52cc4ed7cf3331cc`. The checked-out base before this fix round was `eb1ae9038f9866304c18c57be9a69735d8d9455c`; this work is intentionally uncommitted for the supervisor to commit and push.

## Implemented in this round

- `experiments/native_ast/ast_core.py` contains pure-Python fixture writing and canonical validation, per-asset stage exceptions, exact frame-boundary mapping, merged asset grouping, and all-or-nothing preparation with injected codec callables.
- `experiments/native_ast/ffmpeg_tools.py` is the manual-only absolute-path FFmpeg wrapper and capability/version preflight.
- The manual `probe` and `shared_edit` scripts are importable modules. They use the actual FFmpeg build only when run manually, cross-check FFmpeg's native bytes against the pure writer, check decoded stereo layout, and inject a genuine `-n` reconstruction refusal while edited PCM remains valid.
- Added portable required tests in `tests/unit/test_native_ast.py` and `tests/integration/test_native_ast_prepare.py`. Tests exercise the real upstream PCM/WAVE/scratch boundary with fake codecs; no test imports FFmpeg or has a skip path.
- Supervisor review F10 is fixed: `prepare()` now independently checks edited PCM against verified original PCM and merged integer frame ranges before encoding. It requires every in-range frame to be silent, every out-of-range frame to be byte-identical, and the frame count to remain fixed. Four storage-seam tampering cases assert stage-specific `EditError`, no encoder call, and unchanged directory snapshots.
- Expanded routine lint/format/typecheck targets to `experiments`, added pytest's local import path, and excluded experiments from the sdist manifest. No upstream-owned `src/`, `scripts/`, existing tests, or audio-storage docs were changed.

## Local evidence

Verified on Windows 11 build `10.0.26300`, CPython 3.14.10, FFmpeg `n7.1.5-12-g1fdbca85aa-20260731` (BtbN GPL static, WinGet `BtbN.FFmpeg.GPL.7.1`, configured with `--enable-gpl --enable-version3`). See the [experiment README](../../experiments/native_ast/README.md) for the exact PowerShell commands and script stdout.

Exact checks:

- New required tests: `43 passed in 0.88s`; no skips. The four F10 tamper cases separately passed (`4 passed, 8 deselected`).
- `task.cmd test`: `165 passed in 22.40s`; no skips.
- The two manual native scripts passed on Windows; their stdout is recorded in the experiment README. Refresh PATH from the User and Machine environment variables in an already-open PowerShell process if FFmpeg is not found.
- Targeted Ruff lint and format-check plus mypy for `experiments/` and the new tests passed (`All checks passed`; `9 files already formatted`; `Success: no issues found in 8 source files`).
- Full `task.cmd lint`, `format-check`, and `typecheck` still fail only on the known upstream baseline findings: `scripts/benchmark_audio.py` (Ruff import order/format), `src/muteinous/core/audio/pcm.py` (format), and `tests/integration/test_audio_scratch.py` (two mypy errors). No upstream-owned files were changed.
- `task.cmd build` passed. The build check verified the wheel installs; the prior explicit archive inspection found zero `experiments/` entries in both wheel and sdist.
- Negative control: disabling the BLCK-padding check caused its named test to fail (`1 failed, 20 passed`); the check was restored and all final checks were rerun.
- F10 negative control: temporarily removing the independent PCM verifier caused all four new tampering cases to fail (`4 failed`); after restoring it, the four cases and full suite passed.

Task readiness initially found a stale local editable install; `task.cmd setup` resynchronized the locked environment without changing dependencies or `uv.lock`.

The earlier Linux identity-probe output is historical only. Linux/macOS shared-edit behavior, remote CI, and game-loader acceptance/playback remain unverified. This does not establish a supported production adapter or installation path.

## Supervisor follow-up

- The final PR/commit SHA and remote CI must be recorded by the supervisor after commit/push. Do not modify upstream-owned files or the shared architecture/coverage documents as part of this handoff.
