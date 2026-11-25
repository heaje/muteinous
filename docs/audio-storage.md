# M1.4 lossless audio working storage

Implementation evidence for [Issue #19](https://github.com/heaje/muteinous/issues/19) and the [D06 amendment](architecture/decisions.md#amendment-2026-11-24-replaceable-lossless-intermediate-encoding). This is an internal working format, not a native-format support or installation claim.

## Initial choice and limits

Use the standard-library WAVE extensible backend in [wav.py](../src/muteinous/core/audio/wav.py) for now. It preserves full-width unsigned 8-bit, signed 16/24/32-bit, and IEEE float32/float64 little-endian interleaved samples. The format value includes actual rate, channels, frame count, representation (which specifies precision), and a speaker mask in WAVE speaker-bit order (only speaker-position bits 0–17 are accepted, with one set bit per channel; 0 explicitly means unspecified). Do not invent a mask for a source whose layout is unknown. Nonrepresentable channel arrangements, non-full-width valid-bit precision, representations outside this list, and RIFF/byte-rate limits must be refused rather than converted to fit. No RF64, arbitrary input WAV parser, or native decoder is implemented here. Native adapters must establish the actual source representation and segment mapping; their own fidelity/structural validation is still required.

The [PCM editor](../src/muteinous/core/audio/pcm.py) consumes original-quality segment-local interleaved frame blocks, never encoded data. A block is at most 4096 frames, including all channels. Ranges are start-inclusive/end-exclusive seconds. Validate required ranges before padding, clip only padding to segment bounds, merge touching/overlapping padded ranges, then round outwards with the literal D33 float expressions `floor(start * rate)` and `ceil(end * rate)` (IEEE double arithmetic; the product is not compensated for sub-ulp representation error, so a boundary within about one ulp of a frame edge follows the rounded product). A required range ending exactly at the segment duration maps to the final frame count rather than to `ceil(duration * rate)`, which could otherwise round one frame past the segment. Coalesce additionally if rounding eliminates the gap at frame resolution. Fade lengths round down to frames, shortened independently at the outer margins. Fade-down starts at unity and reaches zero at the first fully censored frame; fade-up reaches unity at the last fade frame. Zero available margin means no fade; required words remain fully muted. Defaults are zero margins/duration at this low-level boundary and raised cosine when a fade is requested, not user-facing settings defaults. Integer scaling rounds to nearest, ties to even; float scaling retains the source representation. Unchanged frames are copied as bytes, including unusual IEEE bit patterns. Non-finite floats requiring arithmetic in a fade fail instead of silently producing invalid gain results.

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

[benchmark_audio.py](../scripts/benchmark_audio.py) is an optional experiment, not a routine pytest workload or a runtime dependency. On a Linux host with FFmpeg/ffprobe and GNU time, run:

~~~sh
.venv/bin/python scripts/benchmark_audio.py
# Repeat --case for selected zero-based cases; omit it to run cases 0–6:
.venv/bin/python scripts/benchmark_audio.py --case 0 --case 6
~~~

`--case` accepts one or more case indexes from 0 through 6 and may be repeated.
Unexpected tool failures are reported separately from explicit representation exclusions and make the script exit nonzero after printing all requested cases.

The generator alternates silence, tones and seeded noise (seed 19), in blocks; it does not use a speech or game corpus. Cases cover mono, stereo and 5.1, 8–96 kHz, all six full-width representations and a larger 20-second six-channel workload. WAV uses the actual production backend. FLAC and WavPack use FFmpeg encoders/decoders (one encoder thread), bounded raw spool files and the same PCM editor. The encoder requests a sample format and, for integer PCM, `bits_per_raw_sample` derived from the supplied `PCMFormat`: WavPack requests the FFmpeg sample formats `u8p`, `s16p`, `s32p` (also for s24 with `bits_per_raw_sample 24`) and `fltp`, while FLAC requests s16 for u8/s16 and s32 for s24/s32. The script hashes initial decoded PCM against the original and edited decoded PCM against the original passed through the editor. It reports byte-exactness separately from metadata preservation (rate, channels, layout, reported precision and decoded frame count); `exact-with-metadata-widening` means samples match but reported precision is wider, not that metadata was preserved.

Recorded 2026-11-24 in WSL2 Ubuntu 26.04.1 LTS, kernel `6.6.87.2-microsoft-standard-WSL2` (x86_64), CPython 3.14.4 (`/usr/bin/python3`), FFmpeg/ffprobe 8.0.1-3ubuntu2 and GNU time (`/usr/bin/time`; `--version` reports `UNKNOWN`). The WSL run used the checkout source via `PYTHONPATH`, not the Windows locked venv. All seven cases completed in one invocation. The previous recorded benchmark used a Debian container with FFmpeg/ffprobe 7.1.5-0+deb13u1 and CPython 3.13.5; those results are superseded by this run. Times below are single-run wall-clock seconds including process startup, not a throughput guarantee. Peak scratch is the maximum sum of logical file sizes after each measured phase, including simultaneous encoded source/output, decode/encode spool and verification files; the independent synthetic raw fixture and measurement log are excluded. RSS is the largest measured child-process peak, not aggregate application/job memory. The compressed workflows spool decoded PCM on disk for this experiment; a future streaming implementation could change their scratch peak. No comparison of hypothetical optimized streaming code is claimed.

Each row gives original round-trip exactness, metadata preservation, edited-reference exactness, outcome label, encoded bytes, peak scratch bytes, peak child RSS in KiB, and seconds for source encode / decode / edit / edited encode / edited decode. WAV edits directly into its storage backend, so its edited-encode column is `—`; compressed edit and edited encode are measured separately.

| Case | Backend | Exact | Metadata | Edited exact | Outcome | Encoded B | Peak B | RSS KiB | Seconds E/D/Edit/EE/D2 |
| --- | --- | --- | --- | --- | --- | ---: | ---: | ---: | --- |
| u8 8 kHz mono 2s | WAV | yes | yes | yes | exact | 16,080 | 48,160 | 22,464 | .2175/.2104/.2070/—/.2053 |
| | FLAC | yes | no (precision) | yes | exact-with-metadata-widening | 15,517 | 47,517 | 56,832 | .0375/.0227/.2035/.0215/.0205 |
| | WavPack | yes | yes | yes | exact | 8,124 | 40,124 | 56,064 | .0298/.0214/.2058/.0198/.0209 |
| s16 16 kHz mono 2s | WAV | yes | yes | yes | exact | 64,080 | 192,160 | 22,848 | .2046/.2030/.2053/—/.2053 |
| | FLAC | yes | yes | yes | exact | 33,295 | 161,295 | 56,640 | .0238/.0225/.2037/.0231/.0212 |
| | WavPack | yes | yes | yes | exact | 28,708 | 156,708 | 55,872 | .0202/.0207/.2051/.0210/.0210 |
| s24 48 kHz stereo 2s | WAV | yes | yes | yes | exact | 576,080 | 1,728,160 | 23,040 | .2013/.2035/.2103/—/.2045 |
| | FLAC | yes | yes | yes | exact | 262,529 | 1,414,529 | 57,216 | .0231/.0212/.2041/.0233/.0218 |
| | WavPack | yes | yes | yes | exact | 327,856 | 1,479,856 | 57,852 | .0218/.0215/.2063/.0226/.0226 |
| s32 96 kHz 5.1 2s | WAV | yes | yes | yes | exact | 4,608,080 | 13,824,160 | 23,232 | .2222/.2152/.2275/—/.2216 |
| | FLAC | no | no (precision) | no | not-exact | 1,576,558 | 10,792,558 | 65,280 | .0337/.0272/.2377/.0330/.0252 |
| | WavPack | yes | yes | yes | exact | 2,848,416 | 12,064,416 | 64,020 | .0416/.0327/.2325/.0419/.0341 |
| f32 48 kHz stereo 2s | WAV | yes | yes | yes | exact | 768,080 | 2,304,160 | 22,836 | .2207/.2077/.2211/—/.2104 |
| | FLAC | excluded (integer encoder) | — | — | — | — | — | — | — |
| | WavPack | yes | yes | yes | exact | 386,626 | 1,922,626 | 57,848 | .0251/.0235/.2105/.0245/.0228 |
| f64 44.1 kHz mono 2s | WAV | yes | yes | yes | exact | 705,680 | 2,116,960 | 23,040 | .2090/.2192/.2131/—/.2184 |
| | FLAC | excluded (integer encoder) | — | — | — | — | — | — | — |
| | WavPack | excluded (no f64 input) | — | — | — | — | — | — | — |
| s24 48 kHz 5.1 20s | WAV | yes | yes | yes | exact | 17,280,080 | 51,840,160 | 23,040 | .2200/.2177/.2169/—/.2145 |
| | FLAC | yes | yes | yes | exact | 8,143,888 | 42,703,888 | 64,128 | .0725/.0498/.2131/.0736/.0506 |
| | WavPack | yes | yes | yes | exact | 9,443,784 | 44,003,784 | 65,108 | .0807/.0785/.2254/.0794/.0792 |

With explicit `-sample_fmt s32p -bits_per_raw_sample 24`, WavPack reports 24-bit s24 metadata and reproduces the input bytes; the earlier WavPack s24 mismatch was an invocation artifact. FLAC u8 is also byte-exact, but `-sample_fmt s16 -bits_per_raw_sample 8` still probes as 16-bit: this is metadata widening, not sample loss. FLAC s32 was tested with `-sample_fmt s32 -bits_per_raw_sample 32`, yet FFmpeg 8.0.1 emitted 24-bit metadata and the decoded bytes differed. That is a limitation of this tested FFmpeg encoder path; it is not a universal FLAC claim. FLAC float and WavPack f64 were excluded without conversion.

For the 20-second s24 5.1 case, FLAC is 47.13% of WAV's encoded size (52.87% smaller) and WavPack is 54.65% (45.35% smaller). The benchmark's verification-inclusive WAV peak is 51,840,160 bytes, compared with 42,703,888 for FLAC and 44,003,784 for WavPack. Production WAV editing holds two working files (34,560,160 bytes, excluding tiny owner metadata); the compressed spool peaks are therefore 23.56% and 27.33% larger than that two-file WAV working set. The benchmark WAV peak includes its additional final-decode verification copy and is not the production scratch peak.

WAV remains the initial backend because it is the simplest verified choice that preserves all six tested representations and properties, using the standard library without an external codec runtime. The compressed alternatives offer meaningful encoded-size savings but neither covers all six representations in this FFmpeg build, and compressed spooling does not beat the production two-file WAV scratch peak in the larger case. Selecting either would additionally need verified streaming behavior and native executable/library distribution, licensing, integrity, Windows/Python 3.14 and portable-platform compatibility evidence under D164–D165. Do not silently convert unsupported formats; revisit alternatives when equivalent end-to-end fidelity and packaging evidence exists.

## Validation and remaining integration

Deterministic tests in [test_pcm.py](../tests/unit/core/audio/test_pcm.py), [test_wav.py](../tests/unit/core/audio/test_wav.py) and [test_audio_scratch.py](../tests/integration/test_audio_scratch.py) exercise D05–D06, D08, D22, D32–D39, D123–D124 and D160. On Windows with the locked CPython 3.14.10 environment, `task check` (lint, format, strict typing, decision IDs, the full required test suite, package build and version preview) passed locally. A separate local Linux run (WSL2 Ubuntu, locked CPython 3.14.10 from `uv sync --locked`) passed the portable subset and the full suite. This is not remote CI: the required Windows, Linux and macOS PR checks have not run, and macOS execution is unverified. Required checks and outstanding infrastructure evidence remain tracked by [Issue #4](https://github.com/heaje/muteinous/issues/4). Native decoding/reconstruction, storage bundle publication, cache eviction, settings persistence, native staging, game-facing writes and loader acceptance are explicitly outside this slice.
