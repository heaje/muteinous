# M1.4 lossless audio working storage

Implementation evidence for [Issue #19](https://github.com/heaje/muteinous/issues/19) and the [D06 amendment](architecture/decisions.md#amendment-2026-11-24-replaceable-lossless-intermediate-encoding). This is an internal working format, not a native-format support or installation claim.

## Initial choice and limits

Use the standard-library WAVE extensible backend in [wav.py](../src/muteinous/core/audio/wav.py) for now. It preserves full-width unsigned 8-bit, signed 16/24/32-bit, and IEEE float32/float64 little-endian interleaved samples. The format value includes actual rate, channels, frame count, representation (which specifies precision), and a speaker mask in WAVE speaker-bit order (0 explicitly means unspecified). Do not invent a mask for a source whose layout is unknown. Nonrepresentable channel arrangements, non-full-width valid-bit precision, representations outside this list, and RIFF/byte-rate limits must be refused rather than converted to fit. No RF64, arbitrary input WAV parser, or native decoder is implemented here. Native adapters must establish the actual source representation and segment mapping; their own fidelity/structural validation is still required.

The [PCM editor](../src/muteinous/core/audio/pcm.py) consumes original-quality segment-local interleaved frame blocks, never encoded data. A block is at most 4096 frames, including all channels. Ranges are start-inclusive/end-exclusive seconds. Validate required ranges before padding, clip only padding to segment bounds, merge touching/overlapping padded ranges, then round outwards. Coalesce additionally if rounding eliminates the gap at frame resolution. Fade lengths round down to frames, shortened independently at the outer margins. Fade-down starts at unity and reaches zero at the first fully censored frame; fade-up reaches unity at the last fade frame. Zero available margin means no fade; required words remain fully muted. Defaults are zero margins/duration at this low-level boundary and raised cosine when a fade is requested, not user-facing settings defaults. Integer scaling rounds to nearest, ties to even; float scaling retains the source representation. Unchanged frames are copied as bytes, including unusual IEEE bit patterns. Non-finite floats requiring arithmetic in a fade fail instead of silently producing invalid gain results.

Use [scratch.py](../src/muteinous/core/audio/scratch.py) as a context manager with a dedicated, private application-owned root and a chosen internal [Storage](../src/muteinous/core/audio/storage.py) implementation. One context processes one segment sequentially; callers must keep all reads/reconstruction within the context and never expose incomplete scratch as a valid result.

~~~python
from muteinous.core.audio.pcm import PCMFormat
from muteinous.core.audio.scratch import audio_scratch
from muteinous.core.audio.wav import WaveStorage

# decoded_blocks is a bounded original-quality PCM iterator supplied by a native adapter.
# root is an application-owned scratch directory, not a game directory.
with audio_scratch(root, WaveStorage()) as scratch:
    scratch.write_source(PCMFormat(48000, 2, "s24", frame_count, 3), decoded_blocks)
    edited = scratch.edit([(0.4, 0.8)], before=0.03, after=0.03, fade=0.02)
    with scratch.storage.open(edited) as reader:
        # The native adapter consumes reader.info and reader.blocks() here.
        reconstruct_and_validate(reader.info, reader.blocks())
~~~

Exclusive creation avoids overwriting existing paths. Each write checks the known output size against current filesystem availability (the existing source is already accounted for), then propagates actual write/decode failures and removes failed output. No optional cache implementation exists to evict. Storage availability is advisory and cannot reserve space. Scratch is distinct from result storage, backups and native staging. The context deletes its known audio files; startup cleanup reclaims recognized marker-bearing directories only after acquiring the nonblocking owner-file lock. Ambiguous entries, links, live locks and interrupted initialization without a valid marker are retained; do not use the API on arbitrary user directories. Cleanup failures remain failures or leave owned data eligible for later best-effort cleanup; no power-loss durability or protection against an adversarial writer inside the private root is claimed. The caller must not retain open scratch handles past context exit.

## Reproducible comparison

[benchmark_audio.py](../scripts/benchmark_audio.py) is an optional experiment, not a routine pytest workload or a runtime dependency. On a Linux host with FFmpeg/ffprobe and GNU time, after normal repository setup run:

~~~sh
.venv/bin/python scripts/benchmark_audio.py
# Or run selected zero-based cases, including the larger case 6:
.venv/bin/python scripts/benchmark_audio.py --case 0 --case 6
~~~

The generator alternates silence, tones and seeded noise (seed 19), in blocks; it does not use a speech or game corpus. Cases cover mono, stereo and 5.1, 8–96 kHz, all six full-width representations and a larger 20-second six-channel workload. WAV uses the actual production backend. FLAC and WavPack use the FFmpeg 7.1.5 encoders/decoders (one encoder thread), bounded raw spool files and the same PCM editor. Hash the initial decoded PCM against the original and edited decoded PCM against the original passed through the editor. Probe actual rate, channels, channel layout and reported precision, and compare decoded frame count. An exact byte round trip alone is not proof of identical precision metadata.

Recorded 2026-11-24, Linux container, CPython 3.13.5 (supplemental, **not** the supported locked 3.14 environment), FFmpeg/ffprobe 7.1.5-0+deb13u1, GNU time. Cases 0–5 completed in the initial invocation before its outer execution limit; case 6 completed separately. Times are single-run wall-clock seconds including process startup, not a throughput guarantee. Peak scratch is the maximum sum of logical sizes after each phase, including simultaneous encoded source/output, decode/encode spool and verification files; the independent synthetic raw fixture and measurement log are excluded. RSS is the largest measured child-process peak, not aggregate application/job memory. Python interpreter startup overhead dominated the measured 94–95 MiB peaks in this environment. The compressed workflows spool decoded PCM on disk for this experiment; a future streaming implementation could lower their scratch peak. No comparison of hypothetical optimized streaming code is claimed.

Each row gives original round-trip / metadata / edited-reference exactness, encoded bytes, peak scratch bytes, peak child RSS in KiB, and encode / decode / edit / edited-decode seconds (compressed edit includes shared PCM editing and re-encoding; its initial decode is listed separately).

| Case | Backend | Exact / metadata / edited | Encoded B | Peak B | RSS KiB | Seconds E / D / edit / D2 |
| --- | --- | --- | ---: | ---: | ---: | --- |
| u8 8 kHz mono 2s | WAV | yes/yes/yes | 16,080 | 48,160 | 96,404 | .811/.725/.646/.640 |
| | FLAC | yes/no/yes | 15,517 | 47,517 | 96,400 | .064/.060/.745/.060 |
| | WavPack | yes/yes/yes | 8,124 | 40,124 | 96,420 | .059/.058/.716/.082 |
| s16 16 kHz mono 2s | WAV | yes/yes/yes | 64,080 | 192,160 | 96,416 | .737/.669/.625/.634 |
| | FLAC | yes/yes/yes | 33,295 | 161,295 | 96,424 | .106/.064/.848/.062 |
| | WavPack | yes/yes/yes | 28,708 | 156,708 | 96,404 | .061/.067/.712/.079 |
| s24 48 kHz stereo 2s | WAV | yes/yes/yes | 576,080 | 1,728,160 | 96,404 | .733/.659/.738/.605 |
| | FLAC | yes/yes/yes | 262,529 | 1,414,529 | 96,408 | .067/.061/.775/.063 |
| | WavPack | yes/no/yes | 339,944 | 1,491,944 | 96,420 | .078/.075/.719/.060 |
| s32 96 kHz 5.1 2s | WAV | yes/yes/yes | 4,608,080 | 13,824,160 | 96,800 | .684/.669/.665/.753 |
| | FLAC | no/no/no | 1,576,558 | 10,792,558 | 96,784 | .085/.073/.809/.072 |
| | WavPack | yes/yes/yes | 2,848,416 | 12,064,416 | 96,804 | .097/.089/.879/.079 |
| f32 48 kHz stereo 2s | WAV | yes/yes/yes | 768,080 | 2,304,160 | 96,416 | .608/.703/.669/.672 |
| | FLAC | excluded (integer only) | — | — | — | — |
| | WavPack | yes/yes/yes | 386,626 | 1,922,626 | 96,424 | .069/.067/.754/.073 |
| f64 44.1 kHz mono 2s | WAV | yes/yes/yes | 705,680 | 2,116,960 | 96,424 | .648/.670/.691/.644 |
| | FLAC | excluded (integer only) | — | — | — | — |
| | WavPack | excluded (tested tool has no f64 input) | — | — | — | — |
| s24 48 kHz 5.1 20s | WAV | yes/yes/yes | 17,280,080 | 51,840,160 | 96,656 | .910/.760/.719/.669 |
| | FLAC | yes/yes/yes | 8,143,888 | 42,703,888 | 96,656 | .155/.103/.804/.102 |
| | WavPack | yes/no/yes | 10,023,422 | 44,583,422 | 96,660 | .255/.178/1.102/.160 |

The measured FLAC path widens u8 to 16-bit metadata and reduces s32 to 24 bits (not bit exact). The latter is an intentionally failing experimental probe, never a production conversion. FLAC cannot preserve float PCM. WavPack's tested path reports 32-bit precision for s24 even when decoding to s24 reproduces the bytes; f64 is excluded without conversion. These are specific encoder-path findings, not claims that every implementation of either codec has the same limits.

FLAC stored the larger s24 source at 47.1% of WAV size and WavPack at 58.0%, real savings worth revisiting. However, the production WAV edit holds only two files (34,560,160 bytes for that case, excluding tiny owner metadata); the compared compressed spool paths peaked at 42.7 and 44.6 MB respectively, with verification included. Thus encoded-size savings alone do not establish a better end-to-end working-set tradeoff. WAV covers all six measured representations with no external runtime dependencies or lockfile changes. Selecting compressed alternatives now would require a verified streaming boundary, precision/layout checks, and new native executable/library distribution, licensing, integrity and Windows/Python 3.14 plus portable-platform compatibility evidence under D164–D165. The measured Linux FFmpeg executable is not that evidence. Start with the simplest verified lossless backend; do not silently fall back from an unsupported format to a lossy conversion. Revisit FLAC/WavPack or other lossless codecs with equivalent fidelity and actual streaming scratch measurements once native-tool packaging and representative workloads are established.

## Validation and remaining integration

Deterministic tests in [test_pcm.py](../tests/unit/test_pcm.py) and [test_audio_scratch.py](../tests/integration/test_audio_scratch.py) exercise D05–D06, D08, D22, D32–D39, D123–D124 and D160. The isolated Linux supplemental test run passed 37 cases under Python 3.13.5; this is not locked Task or remote Windows/macOS evidence. Required checks and outstanding infrastructure evidence remain tracked by [Issue #4](https://github.com/heaje/muteinous/issues/4). Native decoding/reconstruction, storage bundle publication, cache eviction, settings persistence, native staging, game-facing writes and loader acceptance are explicitly outside this slice.
