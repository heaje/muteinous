# AST PCM round-trip and loop metadata
Status: resolved for the narrow synthetic AST profile; arbitrary AST variants remain unsupported
Last verified: 2026-11-28
Related: [#20](https://github.com/heaje/muteinous/issues/20), D05–D08, [native AST experiment](https://github.com/heaje/muteinous/blob/ccaf315096509037e3784f1d73dca0d25841fdda/experiments/native_ast/README.md)
Code location: `poc/native-formats-issue-20`, [retained branch checkpoint `ccaf315`](https://github.com/heaje/muteinous/tree/ccaf315096509037e3784f1d73dca0d25841fdda). Evidence: [reviewed implementation `8b3b3ba`](https://github.com/heaje/muteinous/tree/8b3b3baa2ab9ca0312abc314f1b69b56c6fb6d3d) (Windows locked run and two independent reviewer reruns, as reported in the [verification handoff](https://github.com/heaje/muteinous/blob/ccaf315096509037e3784f1d73dca0d25841fdda/.agents/handoffs/issue-20.md)); reported evidence checkpoint [`f3e99f4`](https://github.com/heaje/muteinous/tree/f3e99f445c28d6ec5b60d60c09099471cd415365) and subsequent [retained branch checkpoint `ccaf315`](https://github.com/heaje/muteinous/tree/ccaf315096509037e3784f1d73dca0d25841fdda) change documentation only. For the 2026-11-25 evidence above, no fresh coordinator execution or independently retrieved reviewer transcript is claimed; see the 2026-11-28 verification supplement below for later reruns. The retained branch contains the original baseline and main through PR #32; subsequent main #33/#35 changed speech models/tests and coordination documentation only, not shared PCM or other common production source blobs. No further implementation merge needed for this pinned experiment. Keep the experiment outside main and out of distribution.
Retire/promote when: a production native adapter replaces the experiment with independent evidence.

## Finding and limitations

The canonical synthetic AST has 32 kHz stereo PCM16, 8,192 frames, four 2,048-frame blocks, 32,960 native bytes and loop frames 1,024–6,144. Real FFmpeg extraction/reconstruction through merged #19 PCMFormat/WaveStorage/Scratch.edit preserves decoded samples outside edits exactly, with stereo intermediate mask 3. The pure-Python parser/writer validates the supported structure, rejects noncanonical padding/partition/metadata/sample changes, and is cross-checked against FFmpeg. The grouped-edit scripts and deterministic tests verify one rebuild per affected asset, exclusion of untouched assets, exact requested edits, corrupt/unsupported/reconstruction refusal in either asset order and atomic source/scratch cleanup.

The encoded-fidelity probe compares the entire reconstructed native byte array against the original with only edited PCM positions zeroed. Asset a: 306 edited frames; 31,736 bytes outside edited sample positions identical. Asset b: 128 edited frames; 32,448 bytes outside edited sample positions identical. This establishes native-byte preservation for this profile, not a general AST editing algorithm.

Independent decoder: official [vgmstream r2168](https://github.com/vgmstream/vgmstream/releases/tag/r2168) uses its own [AST parser](https://github.com/vgmstream/vgmstream/blob/r2168/src/meta/ast.c), [blocked layout](https://github.com/vgmstream/vgmstream/blob/r2168/src/layout/blocked_ast.c) and PCM16BE decoding, not FFmpeg's AST decoder. The probe checks JSON metadata with `-I`, decodes with looping disabled (`-i -o OUTPUT INPUT`), and compares PCM16 WAV properties and every sample byte with expected original/edited PCM. Both reconstructed assets and source files passed at 32 kHz stereo, 8,192 frames, loop frames 1,024–6,144. The coordinator inspected the tagged AST parser and block layout; the supported PCM path selects coding_PCM16BE. The official Windows archive `vgmstream-win64.zip` was reported verified against release SHA-256 `692d45070852a35c1fa42726aa3c9de528e44eec925d37d99b1074256b99a229`.

FFmpeg AST loop options use integer milliseconds; arbitrary native frame positions are not presumed representable. AST does not supply an explicit speaker mask. No arbitrary AST variant, game-engine bank, loader/playback acceptance, installation safety, production bounded-memory native adapter or other decoder build is established. Prior Linux identity-only and Debian 13.3/CPython 3.13.5 partial-source runs are historical/supplemental, not locked Linux validation.

## Verification supplement (2026-11-28)

- The locked Windows rerun and native hosted Windows/Linux/macOS run 2 re-exercised the retained canonical synthetic AST profile; run 1's macOS vgmstream launch failure was resolved by installing/checking its Homebrew dependencies in run 2. See [run 1](https://github.com/heaje/muteinous/actions/runs/46113593828), [run 2](https://github.com/heaje/muteinous/actions/runs/46116057984), and [verification PR](https://github.com/heaje/muteinous/pull/61).
- The 2026-11-28 reruns were executed by AI subagent sessions under one supervising session; the consolidated verification report, independent review and raw logs/JSON are maintainer-local and unpublished, while the public evidence is the two linked Actions runs and PR #61.
- All three run-2 platforms reported matching encoded fidelity: asset `a`, 32,960 bytes / 306 edited frames / 31,736 unchanged bytes; asset `b`, 32,960 bytes / 128 edited frames / 32,448 unchanged bytes. Independent vgmstream r2168 decoding of both source and rebuilt assets was sample-exact: 32 kHz stereo, 8,192 frames, loops 1,024–6,144.
- Direct `FFmpegTools.decode` accepts a 64-byte header-only AST with zero output bytes, while `prepare()` rejects it in native validation before invoking the decoder. Treat this as an observation, not a confirmed defect or a substitute for structural validation.
- Hosted AST-harness timings are instance-specific, not repeatable baseline or pytest-suite timings. Native Linux/macOS POSIX `killpg` timeout checks and Ogg reproduction remain untested; package checks covered Windows-built artifacts only. Arbitrary AST variants, loader/game acceptance, installation safety and production-adapter behavior remain unverified.

## Reproduction / evidence

Reported Windows 11 build 10.0.26300, CPython 3.14.10, Task 3.54.0, uv 0.13.9; FFmpeg `n7.1.5-12-g1fdbca85aa-20260731` (WinGet `BtbN.FFmpeg.GPL.7.1`). In a separate checkout of the pinned branch checkpoint, run:

~~~powershell
task setup
$env:Path = [Environment]::GetEnvironmentVariable('Path','Machine') + ';' + [Environment]::GetEnvironmentVariable('Path','User') + ';' + $env:Path
$env:PYTHONPATH = "src;."
& .venv/Scripts/python.exe -m experiments.native_ast.probe
& .venv/Scripts/python.exe -m experiments.native_ast.shared_edit
& .venv/Scripts/python.exe -m experiments.native_ast.encoded_fidelity
& .venv/Scripts/python.exe -m experiments.native_ast.independent_decode --vgmstream-cli C:/path/to/private-vgmstream-dir/vgmstream-cli.exe
& .venv/Scripts/python.exe -m pytest tests/integration/test_native_ast_prepare.py tests/integration/test_native_ogg_prepare.py tests/unit/test_native_ast.py -q
task check
~~~

The handoff records all seven native commands successful, 30 targeted tests (1.74 s), full locked Windows task check (551 passed; 31.506 s pytest, 24 xdist workers), Ruff/format/mypy/decision IDs, sdist/wheel and isolated import, version preview. Two independent reviewers on the implementation SHA reported no actionable findings and reran the targeted suite, experiment lint/type checks and task check; AST reviewer reran vgmstream. See [deferred verification](../current-state.md#deferred-verification) for outstanding verification obligations.

FFmpeg tested GPL static build (`--enable-gpl --enable-version3`); vgmstream [COPYING](https://github.com/vgmstream/vgmstream/blob/r2168/COPYING) ISC plus third-party components. The Windows archive's third-party DLL inventory and source-tree notices are in the linked README and handoff; this is not a per-binary redistribution determination. No tool binary or new runtime dependency is shipped.

## Recommendation

Prefer preservation of unaffected encoded content and avoid additional lossy encoding where compatible, per the [fidelity amendment](../../docs/architecture/decisions.md#amendment-2026-11-25-native-reconstruction-fidelity). AST establishes lossless native reconstruction feasibility only. Future production adapters require their own format/engine evidence, bounded resources, licensing and installation/loader gates; no game-facing write or loader experiment was performed.
