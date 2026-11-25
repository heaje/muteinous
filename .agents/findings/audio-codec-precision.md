# Audio codec precision requires correct encoder parameters and decoded-byte checks
Status: active
Last verified: 2026-11-24
Related: [Issue #19](https://github.com/heaje/muteinous/issues/19), [Issue #20](https://github.com/heaje/muteinous/issues/20), [audio-storage benchmark](../../docs/audio-storage.md), [benchmark script](../../scripts/benchmark_audio.py), D05–D06, D164–D165
Retire/promote when: production native-tool paths validate their actual representation and layout, and the evidence is incorporated into implementation guidance.

## Finding and limitations

On FFmpeg 8.0.1-3ubuntu2, encoding raw s24 with `-sample_fmt s32p -bits_per_raw_sample 24` made WavPack report 24-bit metadata and round-trip byte-exactly. The earlier report of WavPack widening s24 to 32 bits was an invocation artifact.

The FFmpeg FLAC path round-trips u8 samples exactly but reports 16-bit precision (`-sample_fmt s16 -bits_per_raw_sample 8`), so sample fidelity and metadata preservation differ. FLAC s32 remains a real limitation in this tested build: even with `-sample_fmt s32 -bits_per_raw_sample 32`, it emits 24-bit metadata and fails the byte-exact check. FLAC floats and WavPack f64 are excluded rather than converted. These are tested encoder-path results, not universal codec claims.

## Reproduction / evidence

From a Linux/WSL checkout with FFmpeg/ffprobe and GNU time, run the seven cases using the command in [audio-storage.md](../../docs/audio-storage.md). Compare decoded hashes, reported rate/channels/layout/precision, and decoded frame count independently. The benchmark uses explicit, representation-derived sample-format and bit-depth options.

## Recommendation

Do not infer that a codec preserved the supplied representation from a successful encode or matching bytes alone. For #20, validate actual native PCM metadata and reject unsupported representations rather than passing converted analysis audio into the shared editor. The WavPack s24 result is supported only with the tested explicit invocation; neither FFmpeg benchmark evidence nor a lossless intermediate round trip establishes native reconstruction or loader compatibility. No codec tool has been selected as a production dependency.
