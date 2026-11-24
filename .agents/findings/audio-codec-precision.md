# Audio codec precision is not implied by a matching decoded byte stream
Status: active
Last verified: 2026-11-24
Related: [#19](https://github.com/heaje/muteinous/issues/19), [#20](https://github.com/heaje/muteinous/issues/20), D05–D06, D164
Retire/promote when: a production native-tool/codec path validates its actual representation and layout, and the evidence is incorporated into its implementation guidance.

## Finding and limitations

The tested FFmpeg 7.1.5 WavPack path reproduced 24-bit sample bytes when explicitly decoded to s24 but reported 32-bit source precision. Its FLAC path changed u8 precision to 16 bits and truncated s32 precision to 24 bits; FLAC floats and WavPack f64 were excluded rather than converted. These results are limited to that tool build and synthetic cases, not universal codec limitations.

## Reproduction / evidence

See [audio-storage.md](../../docs/audio-storage.md) and [benchmark_audio.py](../../scripts/benchmark_audio.py). Compare hashes, reported precision and layout, not just rate/count or a successful conversion exit code.

## Recommendation

For #20, inspect actual native PCM metadata and reject unsupported representations rather than passing a converted analysis stream into the shared editor. Use the WAV scratch boundary for original-quality full-width PCM; don't infer native reconstruction or loader compatibility from intermediate round trips. No codec tool has been selected as a production dependency.
