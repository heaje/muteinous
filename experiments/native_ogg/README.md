# Native Ogg Vorbis feasibility specimen (M1.5)

This is an isolated synthetic experiment for [Issue #20](https://github.com/heaje/muteinous/issues/20), not a production adapter, supported-format declaration, game compatibility claim, or completed censorship/Apply demonstration. It demonstrates a **loose Ogg Vorbis file**, not an engine bank, archive, or proprietary asset format.

## Why this second specimen

The sibling [AST experiment](../native_ast/README.md) is useful as a lossless structural specimen, but its uncompressed Nintendo-console PCM16 example does not exercise unavoidable lossy reconstruction. Ogg Vorbis adds a Windows-relevant PC-game audio container/codec example that can be rebuilt with a freely available FFmpeg/libvorbis toolchain. The specimen is deliberately a loose standard container: **it does not represent Wwise, FMOD, Unity, Unreal, or another engine bank**, and it makes no claim about any game's asset conventions, loader, playback, or compatibility.

Only generated deterministic stereo tone/noise-like audio is used. Nothing is read from or written to a game installation. No production adapter, game-facing writes, title-specific rules, loader test, new Python dependency, or distributable experiment package is introduced.

## Supported synthetic profile and pure-Python validation

[`ogg_core.py`](ogg_core.py) is independent of FFmpeg and validates page framing, lacing, packet assembly, and the supported Vorbis headers:

- Ogg capture pattern and version; BOS, EOS, and continued-packet flags; first sequence zero and continuous sequence numbers; one logical-stream serial; and EOS on the final page only.
- Exact page boundaries, segment-table/body lengths, packet completion across pages, no trailing bytes, bounded file/page/packet/comment lengths, and every page CRC-32 using the Ogg polynomial `0x04C11DB7`, non-reflected, initialized to zero.
- Vorbis version 0, stereo at 44.1 kHz, legal block sizes, identification framing bit, bounded UTF-8 vendor/comments and comment framing bit, a present opaque setup header, and audio packets. Chained/multiplexed streams, non-Vorbis codecs (including Opus-in-Ogg), non-stereo profiles, and other sample rates are refused.
- Final Ogg granule position as frame count. The parser can compare it to the expected decoded frame count; the manual path also checks FFmpeg's decoded `f32le` byte count against that value.

The parser does not decode Vorbis or interpret setup/audio entropy data. Its fixture writer creates structurally valid pages and CRCs with opaque setup/audio packets; the manual scripts separately prove the parser accepts actual FFmpeg/libvorbis output.

`VorbisInfo` extracts channels, rate, final-granule frame count, vendor string, ordered user comments, nominal/minimum/maximum bitrate fields, block sizes, serial, page/packet counts, and setup-header size. Reconstruction checks rate, channel count, frame count, user comments (field names case-insensitive, values exact, duplicates retained), and bitrate class. The encoder uses `-b:a` from the source nominal bitrate; an absent/nonpositive source nominal bitrate makes the request refuse before decode/rebuild. The vendor string is intentionally **not** a preservation invariant and may change; it happened to remain `Lavf61.7.103` in the measured same-build control.

## Shared-PCM path and loss semantics

[`ogg_prepare.py`](ogg_prepare.py) hands the native stream to the real shared `PCMFormat`, `WaveStorage`, `audio_scratch`, and `Scratch.edit` path. The supported PCM profile is stereo 44.1 kHz `f32le`, channel mask `3`, 66,150 frames (1.5 seconds). Vorbis is decoded to float so extraction introduces no integer quantization. Integer-frame edges reuse `frame_boundary_seconds`; zero margins/fades are used.

The experiment makes a small generalization to `native_ast.ast_core.prepare()`: optional PCM metadata, native suffix, native-validator callback, and decoded-reconstruction-verifier callback, plus a `total_frames` argument for `group_edits()`. AST keeps its original strict defaults. Ogg uses the same private temp directory, stage-typed errors naming the asset, one encode per affected asset, merged grouping, untouched-asset exclusion, snapshot-checked all-or-nothing result, and the independent pre-encode edit-completeness verifier. That verifier still requires the intermediate edited `f32` frames to be zero inside requested ranges and byte-identical to the extracted original outside them.

The rebuilt Ogg is **not bit-exact**. Validation is decoded-domain and explicit:

- Every rebuilt Ogg is parsed again by the pure-Python validator.
- FFmpeg decode must preserve exactly 66,150 frames, 44.1 kHz, and stereo.
- In each edited span's interior, excluding 2,048 frames (46.440 ms) at both edges for Vorbis overlap/pre-echo, decoded peak must be at most `0.0005`.
- Outside the edit plus the same edge guard regions, each contiguous region must have at least 24 dB SNR against the *original Ogg's decoded PCM* and maximum absolute sample error at most `0.08`.
- These are refusal thresholds calibrated for this synthetic signal/build, **not** claims of bit-exactness, perceptual transparency, or acceptable quality for every source.

### Measured Windows run

Verified locally on Windows 11 build `10.0.26300`, CPython `3.14.10`, and FFmpeg `n7.1.5-12-g1fdbca85aa-20260731` (BtbN GPL static build installed as `BtbN.FFmpeg.GPL.7.1`, configuration includes `--enable-gpl --enable-version3`). The scripts preflight the absolute FFmpeg executable, Ogg muxer/demuxer, `libvorbis` encoder, and Vorbis decoder. They use argument lists without a shell, 30-second default subprocess timeouts, and at most the last 400 stderr characters in errors. Do not redistribute this observed GPL FFmpeg binary with Muteinous. No LGPL/redistribution conclusion is made here; library/tool licensing review remains open.

The identity control decodes and re-encodes without an edit at the source nominal bitrate. It shows generation loss from re-encoding alone:

| Measurement | Observed |
| --- | ---: |
| Source/rebuilt decoded frames | 66,150 / 66,150 |
| Source/rebuilt nominal bitrate | 128,000 / 128,000 bit/s |
| Identity-control SNR vs original decoded PCM | 33.020 dB |
| Identity-control maximum absolute sample error | 0.01706610 |
| Source/identity Ogg file size | 27,390 / 26,507 bytes |
| Identity-control size change | −883 bytes (−3.224%) |
| Source/identity vendor | `Lavf61.7.103` / `Lavf61.7.103` |

The actual shared-edit script measured two affected assets; each encoded once, while the untouched asset was not rebuilt. Outside regions were compared to each asset's original FFmpeg decode:

| Asset / outside frame region | SNR | Maximum absolute error |
| --- | ---: | ---: |
| `a` `[0, 8977)` | 33.373 dB | 0.01110106 |
| `a` `[32048, 66150)` | 32.261 dB | 0.01278514 |
| `b` `[0, 33232)` | 32.622 dB | 0.02047877 |
| `b` `[54968, 66150)` | 31.636 dB | 0.01443876 |

| Edited file-size comparison | Source | Rebuilt | Delta |
| --- | ---: | ---: | ---: |
| `a` | 27,386 bytes | 20,881 bytes | −6,505 bytes |
| `b` | 27,432 bytes | 21,145 bytes | −6,287 bytes |

The decoded peak in both edited interiors was `0.00000000`. All observed outside-region values met the stated thresholds. FFmpeg's Ogg granule alignment returned exactly 66,150 decoded frames in the source, identity control, and edited outputs; this does not remove Vorbis overlap or generation loss around edit boundaries. The original and identity Ogg size difference is an observed example, not a promised size reduction.

## Reproduction

Run from the repository root in Windows PowerShell. If WinGet updated PATH after this shell opened, refresh it first:

~~~powershell
$env:Path = [Environment]::GetEnvironmentVariable('Path','Machine') + ';' + [Environment]::GetEnvironmentVariable('Path','User') + ';' + $env:Path
& .venv/Scripts/python.exe -m experiments.native_ogg.probe
& .venv/Scripts/python.exe -m experiments.native_ogg.shared_edit
~~~

The first manual script synthesizes a 1.5-second deterministic stereo tone/noise signal, encodes it with FFmpeg/libvorbis, cross-checks the real Ogg pages/CRC/headers with the pure parser, and measures the no-edit generation-loss control. The second creates three synthetic Ogg files, runs real decode → shared float scratch edit → libvorbis rebuild → pure structural parse and FFmpeg decode, then injects corrupt, unsupported, and `-n` destination-exists failures with the failing asset both first and second. Failure checks compare before/after snapshots and verify the failing encoder received the valid edited intermediate PCM. Both scripts use only disposable temporary directories.

Observed stdout from the two manual scripts on the environment above:

~~~text
PASS: ffmpeg version n7.1.5-12-g1fdbca85aa-20260731 Copyright (c) 2000-2026 the FFmpeg developers
PASS: Ogg muxer/demuxer, libvorbis encoder, Vorbis decoder available
PASS: pure-Python parser validated real libvorbis output (4 source pages, 70 audio packets)
PASS: identity control preserved 66150 decoded frames, 2 channels at 44100 Hz
MEASURE: identity generation loss SNR=33.020 dB, max_abs_error=0.01706610
MEASURE: source nominal=128000 bit/s, rebuilt nominal=128000 bit/s
MEASURE: Ogg bytes source=27390, identity=26507, delta=-883
MEASURE: source vendor='Lavf61.7.103'; identity vendor='Lavf61.7.103'
POLICY: outside-region gates SNR>=24.0 dB and max_abs_error<=0.080; edit guard=2048 frames
PASS: identity control was read-only with respect to its source
PASS: disposable probe directory removed
~~~

~~~text
PASS: ffmpeg version n7.1.5-12-g1fdbca85aa-20260731 Copyright (c) 2000-2026 the FFmpeg developers
PASS: Ogg muxer/demuxer, libvorbis encoder, Vorbis decoder available
MEASURE: a outside [0,8977) SNR=33.373 dB max_abs_error=0.01110106
MEASURE: a outside [32048,66150) SNR=32.261 dB max_abs_error=0.01278514
MEASURE: a edited core 0 peak=0.00000000
MEASURE: a Ogg bytes source=27386, rebuilt=20881, delta=-6505
MEASURE: b outside [0,33232) SNR=32.622 dB max_abs_error=0.02047877
MEASURE: b outside [54968,66150) SNR=31.636 dB max_abs_error=0.01443876
MEASURE: b edited core 0 peak=0.00000000
MEASURE: b Ogg bytes source=27432, rebuilt=21145, delta=-6287
PASS: shared PCMFormat/WaveStorage/Scratch.edit used f32le mask 3
PASS: exact frame mapping, merged ranges, and one rebuild per asset
PASS: rebuilt Ogg structure/comments/bitrate/frame count independently checked
PASS: untouched asset bytes remained unchanged
PASS: corrupt Ogg refused at native-validation stage (second)
PASS: six-channel Vorbis refused at native-validation stage (second)
PASS: valid edited PCM + FFmpeg -n encode refusal was atomic (second)
PASS: corrupt Ogg refused at native-validation stage (first)
PASS: six-channel Vorbis refused at native-validation stage (first)
PASS: valid edited PCM + FFmpeg -n encode refusal was atomic (first)
PASS: all manual Ogg scratch removed
~~~

Routine tests are portable pure-Python tests and do not call FFmpeg or skip:

~~~powershell
& .venv/Scripts/python.exe -m pytest tests/unit/test_native_ogg.py tests/integration/test_native_ogg_prepare.py -q
~~~

The suite covers a pure-Python Ogg fixture writer, CRC/page/header/lacing/parser reject cases, metadata and granule checks, exact frame mapping, actual shared float scratch editing with fake codecs, grouping and untouched assets, all-or-nothing snapshots in both failure orders, edit completeness, and lossy tolerance rejection for a fake rebuilt stream that is not silent or changes outside tolerance.

## Limits and remaining evidence

- This is a loose Ogg Vorbis specimen, not an engine bank. No title, engine, game loader, playback acceptance, installation method, production support, or safety-to-install conclusion is established.
- The parser supports only Vorbis version 0, stereo/44.1 kHz, and bounded files; it does not parse the setup codebooks or decode audio. A valid CRC and header structure do not establish that FFmpeg or another decoder can decode arbitrary packets.
- Only the observed Windows FFmpeg build was run. Other FFmpeg builds, Linux/macOS shared editing, independent-decoder agreement, and real game-loader acceptance remain unverified.
- Lossy reconstruction changes decoded samples and file bytes even for an identity edit. Boundary guard regions are intentionally not quality-checked; the chosen thresholds are synthetic-fixture evidence, not universal codec-quality limits.
- Nominal bitrate and comment tags are preserved only for a stream whose source nominal bitrate is present and whose metadata the FFmpeg mapping can retain. A vendor string may legitimately change. Ogg/Vorbis loop tags are preserved as comments here; this does not validate how any consumer interprets them.
- No license conclusion is drawn for FFmpeg/libvorbis/libogg. The tested FFmpeg binary is GPL-configured; packaging and redistribution remain a separate review.
- The repository's source package discovery and sdist exclude `experiments/`; these modules are not a supported or installable API.
