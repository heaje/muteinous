# Native AST feasibility investigation (incomplete M1.5)

This isolated developer experiment is a checkpoint for [#20](https://github.com/heaje/muteinous/issues/20), not a production adapter, supported format declaration or completed censorship demonstration. The final experiment must use the real shared editor and selected lossless intermediate from [#19](https://github.com/heaje/muteinous/issues/19), which was open and absent from main at the initial checkpoint. The stacked integration below now targets the actual upstream implementation; no substitute censor algorithm is implemented.

## Format and tooling rationale

Nintendo Audio Stream (AST) is a real native game audio container with a STRM header, BLCK sections, planar audio, sample count and optional loop bounds. Select its uncompressed signed 16-bit big-endian stereo variant for the first structural experiment: no lossy re-encoding ambiguity, mature FFmpeg demuxer and muxer, and independently documented block layout. Detect structural evidence, not title or file extension alone. This is a low-risk technical specimen, not evidence of relevance to any Windows installation or speech role. Its console origin and common music use limit representativeness for the Windows-first release. Evaluate a Windows-relevant format separately before choosing production priorities. CRI ADX is another candidate with FFmpeg read/write support, but requires explicit lossy fidelity characterization. No encrypted, proprietary or third-party audio fixture is used.

References:
- [FFmpeg AST muxer documentation](https://ffmpeg.org/ffmpeg-formats.html#ast)
- [FFmpeg 7.1 AST muxer implementation](https://ffmpeg.org/doxygen/7.1/astenc_8c_source.html)
- [Independent AST structural description](https://wiibrew.org/wiki/AST_file)
- [vgmstream supported formats](https://github.com/vgmstream/vgmstream/blob/master/doc/FORMATS.md)
- [FFmpeg licensing](https://ffmpeg.org/legal.html)

The probe uses an externally installed FFmpeg executable (not bundled, no new Python dependencies). FFmpeg build options determine LGPL/GPL obligations; the tested Debian binary enables GPL components. Redistribution, executable discovery/trust, exact version pinning, packaging and Windows availability need review before production. vgmstream is a candidate additional independent decoder but was not installed or executed. The validator is independently implemented from documented layout and compares channel samples against the synthetic generator; it is intentionally limited to the tested profile and is not a general AST reader.

## Reproduction

From repository root with FFmpeg available on PATH (AST muxer/demuxer and pcm_s16be_planar codec required), run:

~~~shell
python experiments/native_ast/probe.py
~~~

All files are generated inside a fresh disposable temporary directory. The script accepts no game path or destination arguments, performs no install or loader operation, uses no shell, and refuses invalid structure/profile/sample content. It intentionally uses tiny in-memory fixture comparisons and raw interleaved PCM for an **identity** transport probe only; these are not the D06 bounded intermediate interface or a proposed production memory model. A missing tool or subprocess failure fails the probe rather than silently skipping it.

Observed locally on Linux with CPython 3.13.5 and FFmpeg 7.1.5-0+deb13u1:

~~~text
PASS: 8192 stereo PCM16 frames, 4 blocks, 32960 native bytes
PASS: exact native round trip; three malformed/unsupported/fidelity refusals
PASS: disposable scratch removed
~~~

The independent parser checks STRM size, codec/precision, channels, sample rate, total frames, loop bounds, BLCK sizes and complete interleaved sample equality. The original and identity-reconstructed native bytes are identical; the source is unchanged. Negative controls reject a truncated file, unsupported codec field, and altered sample. Loop metadata in the test is 1024–6144 frames (32–192 ms at 32 kHz). FFmpeg's loop options take integer milliseconds and round down to frames; arbitrary original frame positions may not be representable by those options. Preserve/verify exact native loop fields or refuse; do not infer that generic remuxing preserves them.

The exact fixture probe and Python compilation succeeded. The required repository validation is **not run**: Go Task is absent (attempted task check returned 127), CPython 3.14.10 is absent, and direct GitHub Git transport failed DNS resolution. GitHub connector access permits a branch checkpoint but not a complete local checkout with tags. No remote CI result claimed. Preserve [#4](https://github.com/heaje/muteinous/issues/4) infrastructure verification.

## Stacked integration (implementation added; not yet executed)

PR #25 is based on [PR #27](https://github.com/heaje/muteinous/pull/27), upstream commit `db091d4f97713178bf6ba2dd52cc4ed7cf3331cc`. Run from the repository root after `task setup`:

~~~shell
.venv/bin/python -m experiments.native_ast.shared_edit
~~~

On Windows use `.venv/Scripts/python.exe` instead. This separately provisioned native-tool experiment uses `PCMFormat`, `audio_scratch`, `WaveStorage`, and the actual shared `Scratch.edit` method. Three synthetic assets, two segment-relative requests mapped to one affected asset and one to a second, exercise grouped rebuilding; margins/fades are deliberately zero. The expected zeroed frames are an independent fixture oracle, not an alternative editor. A third asset is untouched. Native metadata and all decoded samples must match the expected output; original files must remain unchanged. A corrupt or unsupported second required asset or real reconstruction subprocess failure must prevent any staged result from escaping and remove disposable scratch. The probe is intentionally fixture-sized and uses temporary output bytes, not a production staging API. External FFmpeg remains separately provisioned. This new integrated script has not yet been executed in the available environment; the identity experiment above is the only executed native evidence at this point.

## Remaining work / acceptance gaps

- D05/D06/D08: execute and review the stacked shared-editor integration above; verify exact frames and fidelity outside intended edits. No lossy effects apply to the current PCM16 profile. Revalidate against merged #19.
- D07/D24: execute grouped-edit and whole-request refusal paths, add routine deterministic unit and representative safety integration tests independent of externally provisioned native tooling; do not substitute the identity probe for these.
- D16/D132–D135: keep the investigation outside production, no title-specific assumptions, loader execution, keys or installation writes. A structurally valid AST is not proof of a game loader accepting it, nor of safe placement, override precedence, verified originals, or reversible removal. Production adapter feasibility requires verified structural variants, exact metadata/channel layout preservation, a bounded streaming path, independent decoder validation, safe tool execution and a separate installation-method investigation under the shared installer. No D135 loader experiment without explicit approval.
- D160–D165: run documented Task validation on the pinned environment, add appropriate portable tests only when platform dependencies are verified, and report actual local/remote evidence separately.

Do not merge as completed M1.5 until the shared-editor experiment and remaining applicable criteria are verified.
