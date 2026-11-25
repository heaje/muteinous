# Native Ogg Vorbis feasibility specimen (M1.5)

This is an isolated synthetic experiment for [Issue #20](https://github.com/heaje/muteinous/issues/20), not a production adapter, supported-format declaration, game compatibility claim, or completed censorship/Apply demonstration. It demonstrates a **loose Ogg Vorbis file**, not an engine bank, archive, or proprietary asset format.

## Why this second specimen

The sibling [AST experiment](../native_ast/README.md) is useful as a lossless structural specimen, but its uncompressed Nintendo-console PCM16 example does not exercise unavoidable lossy reconstruction. Ogg Vorbis adds a Windows-relevant PC-game audio container/codec example that can be rebuilt with a freely available FFmpeg/libvorbis toolchain. The specimen is deliberately a loose standard container: **it does not represent Wwise, FMOD, Unity, Unreal, or another engine bank**, and it makes no claim about any game's asset conventions, loader, playback, or compatibility.

Only generated deterministic stereo tone/noise-like audio is used. Nothing is read from or written to a game installation. No production adapter, game-facing writes, title-specific rules, loader test, new Python dependency, or distributable experiment package is introduced.

## Supported synthetic profile and pure-Python validation

[`ogg_core.py`](ogg_core.py) is independent of FFmpeg and validates page framing, lacing, packet assembly, packet-to-page placement, and the supported Vorbis headers:

- Ogg capture pattern and version; BOS, EOS, and continued-packet flags; first sequence zero and continuous sequence numbers; one logical-stream serial; and EOS only on the final page.
- Vorbis I encapsulation: the 30-byte identification packet is alone on the BOS page; identification, comment, and setup headers occur in order before audio; the first audio packet starts on a fresh page after setup; completed header-only pages have granule position zero (a page wholly spanned by an unfinished packet uses Ogg's `-1`); audio granules are sample positions.
- Exact page boundaries, segment-table/body lengths, packet completion across pages, no trailing bytes, bounded file/page/packet/comment lengths, and every page CRC-32 using a once-built table for the Ogg polynomial `0x04C11DB7` (non-reflected, initialized to zero).
- Vorbis version 0, stereo at 44.1 kHz, legal block sizes, identification framing bit, bounded UTF-8 vendor/comments and comment framing bit, a present opaque setup header, and audio packets. Comment field names follow the Vorbis ASCII range `0x20`–`0x7D` excluding `=` and compare ASCII-case-insensitively. Chained/multiplexed streams, non-Vorbis codecs (including Opus-in-Ogg), non-stereo profiles, and other sample rates are refused.
- Final Ogg granule position as frame count. The parser can compare it to the expected decoded frame count; the manual path also checks FFmpeg's decoded `f32le` byte count against that value.
- The parser receives the complete input as `bytes` (it is not a streaming parser). Input is capped at 64 MiB, page and total-packet counts at 100,000 each, and one unfinished packet at 16 MiB. The packet budget is about 35 minutes at this specimen's observed 70 packets per 1.5 seconds, while stopping million-scale one-byte-packet amplification. It retains the first three header packets only; completed audio packets are type-bit checked and counted, then discarded. Page checks use a temporary page copy, so memory still includes the full caller-owned file and retained headers/one in-progress packet; the parser does not hold a list of every audio packet.

The parser does not decode Vorbis or interpret setup/audio entropy data. Its fixture writer emits the conformant BOS/header/audio page layout with CRCs and opaque setup/audio packets; the manual scripts separately prove the parser accepts actual FFmpeg/libvorbis output.

`VorbisInfo` extracts channels, rate, final-granule frame count, vendor string, ordered user comments, nominal/minimum/maximum bitrate fields, block sizes, serial, page/packet counts, and setup-header size. Reconstruction checks rate, channel count, frame count, user comments (ASCII field names case-insensitive, values exact, duplicates retained), and nominal bitrate within 10% relative to the source value. A 32,000→48,000 bit/s nominal change is refused; the real libvorbis fixture retained 128,000 bit/s exactly. The encoder uses `-b:a` from the source nominal bitrate; an absent/nonpositive source nominal bitrate makes the request refuse before decode/rebuild. The vendor string is intentionally **not** a preservation invariant and may change; it happened to remain `Lavf61.7.103` in the measured same-build control.

## Shared-PCM path and loss semantics

[`ogg_prepare.py`](ogg_prepare.py) hands the native stream to the real shared `PCMFormat`, `WaveStorage`, `audio_scratch`, and `Scratch.edit` path. The supported PCM profile is stereo 44.1 kHz `f32le`, channel mask `3`, 66,150 frames (1.5 seconds). Vorbis is decoded to float so extraction introduces no integer quantization. Requested and padded edit boundaries are integer frames converted with `frame_boundary_seconds`; the shared editor's before/after/fade remain zero.

The experiment makes a small generalization to `native_ast.ast_core.prepare()`: optional PCM metadata, native suffix, native-validator callback, and decoded-reconstruction-verifier callback, plus a `total_frames` argument for `group_edits()`. AST retains its strict 32-kHz/stereo/s16/8,192-frame profile unless a caller supplies a validator. Ogg uses the same private temp directory, stage-typed errors naming the asset, one encode per affected asset, merged grouping, untouched-asset exclusion, snapshot-checked all-or-nothing result, and the independent pre-encode edit-completeness verifier. Before editing, Ogg pads each requested range outward by 224 frames, clamps at the clip bounds, and merges touching/overlapping spans. The verifier requires those entire padded spans to be zero and bit-identical samples outside them; after rebuild it independently checks silence across every frame of each original requested range.

The rebuilt Ogg is **not bit-exact**. Validation is decoded-domain and explicit:

- Every rebuilt Ogg is parsed again by the pure-Python validator.
- FFmpeg decode must preserve exactly 66,150 frames, 44.1 kHz, and stereo.
- Every frame of each **original requested range**, including both edges, must decode with peak at most `0.0005`. A lossy rebuild does not guarantee exact silence at a requested boundary without padding.
- The calibrated default expands requested spans by 224 frames (5.079 ms) per side; clipping the pad at frame 0 or the final frame is intentional because codec leakage cannot extend outside the clip. Touching/overlapping padded spans merge before editing.
- Padding widens the censored span: the measured default can widen by up to 224 frames per side. A conservative full `GUARD_FRAMES` pad would widen by up to 2,048 frames per side (46.440 ms at 44.1 kHz). A production adapter must size padding from its codec window/profile, apply the upstream before/after-margin and fade policy, and respect segment limits under D22/D32–D39; this zero-margin synthetic policy is not production guidance.
- Unedited samples farther than 2,048 frames from a **padded** edit boundary require at least 24 dB SNR and maximum absolute error at most `0.08` against the *original Ogg's decoded PCM*. The 2,048-frame outside/guard comparison is computed relative to padded ranges; guard bands use a separate looser SNR floor of 18 dB and maximum absolute error of `0.05`.
- If no unedited frames exist, verification refuses unless the requested edit legitimately covers the complete clip. A complete-clip edit still has to pass the edited-interior silence check.
- These are refusal thresholds calibrated for this synthetic signal/build, **not** claims of bit-exactness, perceptual transparency, or acceptable quality for every source.

### Edit-edge padding calibration

On the recorded Windows FFmpeg/libvorbis build, an unpadded real re-encode produced requested-range peaks of `0.02020272` (interior), `0.01467311` (clip start), and `0.00938927` (clip end), all above the `0.0005` limit. A measured 8-frame-step sweep from 192 through 224 frames found the first candidate meeting a tenfold margin target (peak `<= 0.00005`) at 224 frames: maximum peak `0.00001828` across interior/start/end (about 27× below the limit). At 216 frames, the maximum was `0.00005452`; it missed the chosen margin target. The default therefore uses 224 frames rather than the initial 2,048-frame guard width. The four-asset shared-edit run then measured requested-range peaks `a=0.00000000`, `b=0.00000000`, `start=0.00001420`, `end=0.00000000`; the last two edits touched and were clamped at the clip boundaries. A separate 2,048-frame calibration also yielded zero peaks on its three synthetic spans. These measurements establish only this codec build and generated signals.

### Measured Windows run

Verified locally on Windows 11 build `10.0.26300`, CPython `3.14.10`, and FFmpeg `n7.1.5-12-g1fdbca85aa-20260731` (BtbN GPL static build installed as `BtbN.FFmpeg.GPL.7.1`, configuration includes `--enable-gpl --enable-version3`). The scripts preflight the absolute FFmpeg executable, Ogg muxer/demuxer, `libvorbis` encoder, and Vorbis decoder. The AST sibling's shared wrapper launches a process group/session, redirects output to private temporary files, reads at most a 64-KiB tail per stream, and kills the process tree on timeout (Windows `taskkill /T /F`, POSIX process group); error excerpts remain capped at 400 characters and text decoding is explicitly UTF-8 with replacement. Do not redistribute this observed GPL FFmpeg binary with Muteinous. No LGPL/redistribution conclusion is made here; library/tool licensing review remains open.

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

The actual shared-edit script measured four affected assets (including clip-start and clip-end edits); each encoded once, while the untouched asset was not rebuilt. Outside regions were compared to each asset's original FFmpeg decode:

| Asset / outside frame region | SNR | Maximum absolute error |
| --- | ---: | ---: |
| `a` `[0, 8753)` | 33.358 dB | 0.01110106 |
| `a` `[32272, 66150)` | 31.778 dB | 0.01526757 |
| `b` `[0, 33008)` | 32.622 dB | 0.02047877 |
| `b` `[55192, 66150)` | 32.513 dB | 0.01435868 |
| `start` `[13297, 66150)` | 31.182 dB | 0.02681977 |
| `end` `[0, 52853)` | 30.949 dB | 0.03549913 |

The separately checked unedited guard bands around those edit boundaries measured:

| Asset / guard frame region | SNR | Maximum absolute error |
| --- | ---: | ---: |
| `a` `[8753, 10801)` | 32.183 dB | 0.02228758 |
| `a` `[30224, 32272)` | 31.455 dB | 0.02692842 |
| `b` `[33008, 35056)` | 30.487 dB | 0.02264281 |
| `b` `[53144, 55192)` | 31.562 dB | 0.02581745 |
| `start` `[11249, 13297)` | 33.463 dB | 0.02262057 |
| `end` `[52853, 54901)` | 25.690 dB | 0.02329308 |

Across the six reported guard regions, the minimum measured SNR was 25.690 dB and the maximum error was 0.02692842. The selected guard limits (18 dB and `0.05`) leave measurement margin while remaining bounded; they are not a universal codec guarantee.

| Edited file-size comparison | Source | Rebuilt | Delta |
| --- | ---: | ---: | ---: |
| `a` | 27,386 bytes | 20,764 bytes | −6,622 bytes |
| `b` | 27,432 bytes | 21,108 bytes | −6,324 bytes |
| `start` | 27,310 bytes | 22,785 bytes | −4,525 bytes |
| `end` | 27,381 bytes | 22,814 bytes | −4,567 bytes |

All four entire requested ranges met the `0.0005` gate; the largest measured requested-range peak was `0.00001420` at the clip-start edit. All observed outside-region values met the stated thresholds. FFmpeg's Ogg granule alignment returned exactly 66,150 decoded frames in the source, identity control, and edited outputs; this does not remove Vorbis overlap or generation loss around edit boundaries. The original and identity Ogg size difference is an observed example, not a promised size reduction.

## Reproduction

Run from the repository root in Windows PowerShell. If WinGet updated PATH after this shell opened, refresh it first:

~~~powershell
$env:Path = [Environment]::GetEnvironmentVariable('Path','Machine') + ';' + [Environment]::GetEnvironmentVariable('Path','User') + ';' + $env:Path
& .venv/Scripts/python.exe -m experiments.native_ogg.probe
& .venv/Scripts/python.exe -m experiments.native_ogg.shared_edit
~~~

The first manual script synthesizes a 1.5-second deterministic stereo tone/noise signal, encodes it with FFmpeg/libvorbis, cross-checks the real Ogg pages/CRC/headers with the pure parser, and measures the no-edit generation-loss control. The second creates five synthetic Ogg files, runs real decode → shared float scratch edit → libvorbis rebuild → pure structural parse and FFmpeg decode, including requested edits at both clip boundaries, then injects corrupt, unsupported, and `-n` destination-exists failures with the failing asset both first and second. Failure checks compare before/after snapshots and verify the failing encoder received the valid padded intermediate PCM. Both scripts use only disposable temporary directories.

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
POLICY: outside-region gates SNR>=24.0 dB and max_abs_error<=0.080; guard regions SNR>=18.0 dB and max_abs_error<=0.050; edit guard=2048 frames; nominal bitrate drift<=10%
PASS: identity control was read-only with respect to its source
PASS: disposable probe directory removed
~~~

~~~text
PASS: ffmpeg version n7.1.5-12-g1fdbca85aa-20260731 Copyright (c) 2000-2026 the FFmpeg developers
PASS: Ogg muxer/demuxer, libvorbis encoder, Vorbis decoder available
MEASURE: a outside [0,8753) SNR=33.358 dB max_abs_error=0.01110106
MEASURE: a outside [32272,66150) SNR=31.778 dB max_abs_error=0.01526757
MEASURE: a guard [8753,10801) SNR=32.183 dB max_abs_error=0.02228758
MEASURE: a guard [30224,32272) SNR=31.455 dB max_abs_error=0.02692842
MEASURE: a requested-range silence 0 peak=0.00000000
MEASURE: a Ogg bytes source=27386, rebuilt=20764, delta=-6622
MEASURE: b outside [0,33008) SNR=32.622 dB max_abs_error=0.02047877
MEASURE: b outside [55192,66150) SNR=32.513 dB max_abs_error=0.01435868
MEASURE: b guard [33008,35056) SNR=30.487 dB max_abs_error=0.02264281
MEASURE: b guard [53144,55192) SNR=31.562 dB max_abs_error=0.02581745
MEASURE: b requested-range silence 0 peak=0.00000000
MEASURE: b Ogg bytes source=27432, rebuilt=21108, delta=-6324
MEASURE: start outside [13297,66150) SNR=31.182 dB max_abs_error=0.02681977
MEASURE: start guard [11249,13297) SNR=33.463 dB max_abs_error=0.02262057
MEASURE: start requested-range silence 0 peak=0.00001420
MEASURE: end outside [0,52853) SNR=30.949 dB max_abs_error=0.03549913
MEASURE: end guard [52853,54901) SNR=25.690 dB max_abs_error=0.02329308
MEASURE: end requested-range silence 0 peak=0.00000000
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

The suite covers a conformant pure-Python Ogg fixture writer, table-driven CRC checked against a slow reference and known vector, CRC/page/header/lacing/parser reject cases (including Vorbis packet placement and granules), packet-count limits, metadata checks, ASCII comment-name rules, exact frame mapping, padded edit merging/clamping and whole-requested-range silence, actual shared float scratch editing with fake codecs, grouping and untouched assets, all-or-nothing snapshots in both failure orders, edit completeness, rebuilt-native rejection, and independent SNR/peak-error refusal cases.

## Limits and remaining evidence

- This is a loose Ogg Vorbis specimen, not an engine bank. No title, engine, game loader, playback acceptance, installation method, production support, or safety-to-install conclusion is established.
- The parser supports only Vorbis version 0, stereo/44.1 kHz, and bounded files; it does not parse the setup codebooks or decode audio. A valid CRC and header structure do not establish that FFmpeg or another decoder can decode arbitrary packets.
- Only the observed Windows FFmpeg build was run. Other FFmpeg builds, Linux/macOS shared editing, independent-decoder agreement, and real game-loader acceptance remain unverified.
- Lossy reconstruction changes decoded samples and file bytes even for an identity edit. Exact requested-boundary silence is not guaranteed without padding; the measured 224-frame pad is evidence only for these generated signals and this FFmpeg/libvorbis build. Production padding, margins/fades, and segment limits require codec/profile-specific design and evidence.
- Nominal bitrate and comment tags are preserved only for a stream whose source nominal bitrate is present and whose metadata the FFmpeg mapping can retain. A vendor string may legitimately change. Ogg/Vorbis loop tags are preserved as comments here; this does not validate how any consumer interprets them.
- No license conclusion is drawn for FFmpeg/libvorbis/libogg. The tested FFmpeg binary is GPL-configured; packaging and redistribution remain a separate review.
- The repository's source package discovery and sdist exclude `experiments/`; these modules are not a supported or installable API.
