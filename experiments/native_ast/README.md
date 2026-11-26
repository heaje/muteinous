# Native AST lossless structural specimen (M1.5)

This is an isolated synthetic experiment for [Issue #20](https://github.com/heaje/muteinous/issues/20), not a production adapter, supported-format declaration, game compatibility claim, or completed censorship/Apply demonstration. AST remains the narrow **lossless structural specimen**: one uncompressed PCM16 stereo profile exercises parsing, grouping and exact shared-PCM edits. It is not representative of the Windows-first release's broader lossy-audio risk; the sibling [Ogg Vorbis experiment](../native_ogg/README.md) is the Windows-relevant **lossy** specimen.

## What is exercised

[`ast_core.py`](ast_core.py) is the pure-Python implementation: a canonical AST fixture writer, strict parser/validator, asset grouping, exact integer-frame-to-time mapping, and private all-or-nothing preparation. Its encoder and decoder are injected callables. Required pytest coverage is deliberately limited to safety-critical shared-editor behavior: exhaustive frame-boundary mapping at 32 kHz, the exact `[1001, 2007)` `Scratch.edit` result, grouped edits with one rebuild per affected asset and no untouched-asset rebuild, representative independent edit-completeness refusals, and stage-typed all-or-nothing refusal/cleanup in both asset orders. Fake codecs keep these required tests independent of FFmpeg; they never skip.

The accepted fixture has 32 kHz, stereo signed PCM16, 8,192 frames, and exact loop bounds 1,024–6,144. AST uses a 64-byte STRM header and 32-byte BLCK headers. The observed FFmpeg `pcm_s16be_planar` packet layout is four blocks, each 4,096 bytes per channel (2,048 frames); only the final block may be shorter for another frame count. The validator rejects nonzero reserved/header padding, nonzero BLCK padding, unexpected partitions, inconsistent fields, extra bytes, and sample changes rather than accepting bytes that reconstruction would normalize. FFmpeg's muxer writes an unknown fixed little-endian `0x7f` marker at STRM bytes 40–43; other bytes in the checked header padding are zero.

Because AST establishes two channels but does not provide an explicit WAVE speaker mask, the intermediate uses the standard stereo WAVE mask `FL|FR = 3`. The manual script also checks that FFmpeg decodes rebuilt AST as `stereo`. Frame boundaries are nudged by adjacent float values until the upstream floor/ceil mapping selects the exact intended frames; the exact-duration end boundary uses upstream's `seconds == duration` special case.

[`ffmpeg_tools.py`](ffmpeg_tools.py) is used only by the manual scripts. It resolves FFmpeg once to an absolute path, checks its version, AST muxer/demuxer, and both decoder and encoder capabilities for `pcm_s16be_planar`. It uses argument lists without a shell and redirects stdout/stderr to private temporary files without a spool-size cap; reads are limited to a 64-KiB tail per stream, and failures include at most the last 400 stderr characters. On timeout, process-tree termination is best-effort: Windows attempts `taskkill /T /F` and falls back to killing the parent if needed; POSIX uses `killpg`, a path not exercised on Linux/macOS. The wrapper waits for the parent process and decodes diagnostic text with UTF-8 replacement. Missing or unsuitable FFmpeg fails loudly. Wrapper behavior is no longer routine pytest coverage: the manual probe checks real capability preflight and runs Python-backed negative controls for bounded tail reads/diagnostics and best-effort Windows timeout termination.

## Reproduction on Windows

Verified locally on Windows 11 (build `10.0.26300`), CPython 3.14.10, and FFmpeg `n7.1.5-12-g1fdbca85aa-20260731`. This FFmpeg is the BtbN GPL static build installed with WinGet package `BtbN.FFmpeg.GPL.7.1`; its configuration includes `--enable-gpl --enable-version3`. Do not redistribute that binary with Muteinous. Other FFmpeg builds are not established by this test.

Run from the repository root in PowerShell. WinGet may update the User/Machine PATH without updating an already-open PowerShell process; refresh that shell if `ffmpeg` is not found:

~~~powershell
$env:Path = [Environment]::GetEnvironmentVariable('Path','Machine') + ';' + [Environment]::GetEnvironmentVariable('Path','User') + ';' + $env:Path
& .venv/Scripts/python.exe -m experiments.native_ast.probe
& .venv/Scripts/python.exe -m experiments.native_ast.shared_edit
~~~

The first script compares actual FFmpeg output bytes against the independent pure-Python writer, performs an identity decode/rebuild, validates the decoded stereo layout, and checks refusals. The second invokes the actual shared PCM/scratch APIs; its fixtures include overlapping and touching segment-relative edits, checks one encoder call per affected asset and none for the untouched asset, and proves cleanup/unchanged originals on failures. Its reconstruction negative control leaves valid edited PCM in place and makes the output destination exist so FFmpeg `-n` refuses the encode.

The required deterministic checks cover only the safety-critical shared-editor boundary and do not need native tools:

~~~powershell
& .venv/Scripts/python.exe -m pytest tests/unit/test_native_ast.py tests/integration/test_native_ast_prepare.py -q
~~~

## Independent AST decoder verification

The closure-gate experiment [`independent_decode.py`](independent_decode.py) sends both original synthetic AST files and their edited reconstructions through the separate `vgmstream-cli` AST decoder. It checks vgmstream-reported sample rate, channel count, total samples and loop points, then decodes with looping disabled and requires WAV PCM16 bytes to match the known original/edited PCM exactly. The controlled edit includes two touching/overlapping ranges in asset `a` and a separate range in `b`; the untouched source is also decoded and checked. The normal FFmpeg/shared-editor path still prepares the edited AST, but FFmpeg does not validate the output samples in this independent check.

On Windows 11 build `10.0.26300`, CPython `3.14.10`, FFmpeg `n7.1.5-12-g1fdbca85aa-20260731`, and official vgmstream release `r2168` (`vgmstream-cli`, 2026-10-25), the independent decoder passed for both original and edited `a` and `b`: 32,000 Hz, stereo, 8,192 samples, loop frames 1,024–6,144, exact PCM16 sample bytes. The official `vgmstream-win64.zip` had SHA-256 `692d45070852a35c1fa42726aa3c9de528e44eec925d37d99b1074256b99a229`, matching the official release API digest.

### vgmstream license and archive contents

The upstream [`COPYING` at r2168](https://github.com/vgmstream/vgmstream/blob/r2168/COPYING) and the archive's `COPYING` contain an ISC license grant (permission to use, copy, modify and distribute for any purpose, with or without fee, provided the copyright and permission notices remain), and attribute third-party portions. The upstream README has no licensing section. The Windows CLI archive contains `avcodec-vgmstream-63.dll`, `avformat-vgmstream-63.dll`, `avutil-vgmstream-61.dll`, and `swresample-vgmstream-7.dll` (FFmpeg); `libcelt-0061.dll` and `libcelt-0110.dll` (CELT); `libmpg123-0.dll` (mpg123); `libspeex-1.dll` (Speex); and `libvorbis.dll` (Vorbis), as well as `vgmstream-cli.exe`. The archive has no separate bundled third-party license files/notices beyond `COPYING`. The source tree's [`ext_libs/licenses`](https://github.com/vgmstream/vgmstream/tree/r2168/ext_libs/licenses) contains texts named for FFmpeg LGPLv2.1/LGPLv3, mpg123 LGPLv2.1/GPLv2, and Xiph-style BSD terms for CELT, Speex, Vorbis and Ogg; these notice files are not present in the Windows CLI zip. This is a description of the checked notices and archive files, not a per-binary license determination. Separate review is needed before redistribution; no legal conclusion or redistribution recommendation is made. This validates only the stated AST profile, not arbitrary AST variants or game-loader behavior.

Download/extract the official release to its own new empty temporary directory, then pass the CLI path as an argument (do not place it in the repository):

~~~powershell
$env:PYTHONPATH = "src;."
& .venv/Scripts/python.exe -m experiments.native_ast.independent_decode `
  --vgmstream-cli C:/path/to/private-vgmstream-dir/vgmstream-cli.exe
~~~

Parser/header/padding/partition matrices and FFmpeg-wrapper timeout/output-bound tests are not routine required coverage. The manual probe retains malformed, unsupported, noncanonical, and zero-frame AST negative controls; the manual shared-edit script exercises native-stage refusals and real `-n` encoder failures. The manual probe's wrapper negative controls use Python child processes rather than FFmpeg and exercise bounded tail reads/diagnostics and best-effort Windows timeout termination.

Observed manual-script output on this Windows environment (including the retained malformed, unsupported, noncanonical, and zero-frame refusal controls):

~~~text
PASS: ffmpeg version n7.1.5-12-g1fdbca85aa-20260731 Copyright (c) 2000-2026 the FFmpeg developers
PASS: FFmpeg AST muxer/demuxer and pcm_s16be_planar decoder/encoder are available
PASS: 8192 stereo PCM16 frames, 4 canonical blocks, 32960 native bytes
PASS: FFmpeg output equals the pure-Python writer and identity rebuild
PASS: malformed, unsupported, and noncanonical AST inputs refused
PASS: zero-frame AST fixture refused
PASS: disposable scratch removed
~~~

~~~text
PASS: ffmpeg version n7.1.5-12-g1fdbca85aa-20260731 Copyright (c) 2000-2026 the FFmpeg developers
PASS: FFmpeg AST muxer/demuxer and pcm_s16be_planar decoder/encoder are available
PASS: real PCMFormat/WaveStorage/Scratch.edit preserved stereo mask 3
PASS: touching/overlapping edits merged; one rebuild per affected asset
PASS: untouched asset not rebuilt; decoded edited PCM is frame-exact
PASS: native refusals and real -n encoder failures are all-or-nothing
PASS: later-asset and first-asset failures preserve snapshots and clean scratch
PASS: disposable scratch removed
~~~

## Historical evidence and limitations

The earlier identity-only probe result on Linux (CPython 3.13.5, Debian FFmpeg `7.1.5-0+deb13u1`) is **historical**. It predates this shared-edit implementation and is not evidence that the current `shared_edit` script or current required tests run on Linux.

Not verified: current shared-edit behavior on Linux or macOS, remote CI results, other FFmpeg builds, arbitrary AST variants or loop positions, independent decoder agreement, actual game-loader acceptance/playback, installation safety, or production bounded-memory/native-adapter behavior. The 32 ms and 192 ms loop points are exactly representable in this fixture; FFmpeg AST loop options use integer milliseconds and arbitrary native frame positions must not be assumed preserved. A structurally valid AST or successful FFmpeg decode is not evidence of loader acceptance.

The source checkout's package discovery is restricted to `src/`, and the source-distribution manifest prunes `experiments/`; the experiment is not an installable package. See [D05–D08](../../docs/architecture/decisions.md) and [testing policy](../../docs/testing.md).
