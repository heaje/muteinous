# Reusable technical findings

Active findings:

- [Capacity changes during dispatch-time plan validation](job-dispatch-capacity-race.md) — preserve FIFO when resources become free during validation.
- [Audio codec precision requires correct encoder parameters and decoded-byte checks](audio-codec-precision.md) — verify actual representation and metadata; reject unsupported inputs.
- [AST PCM round-trip and loop metadata](ast-pcm-roundtrip.md) - synthetic AST profile works through the shared editor; code lives on `poc/native-formats-issue-20`, not `main`.
- [Vorbis lossy round-trip evidence](vorbis-lossy-roundtrip.md) - lossy re-encode needs padding and fidelity gates; code lives on `poc/native-formats-issue-20`, not `main`.
- [Streaming reads: `read(n)` at 1 MiB is slow; reuse a buffer](streaming-read-allocation.md) - buffer reuse and 256 KiB reads for source fingerprinting; warm-cache Windows evidence only.

This directory exists in Git so coding agents can discover where findings belong.
