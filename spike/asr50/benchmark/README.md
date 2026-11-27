# ASR benchmark contract and synthetic corpus

This directory defines a repeatable, inference-free benchmark harness and a
deterministic synthetic evaluation corpus. It does not choose or download ASR
models. Corpus audio is generated outside the repository at
`C:\scratch\asr50\WP6\audio`; only the generator, scorer, tests, and this
specification belong in source control.

## Scope and categories

The placeholder target list is `banana`, `cobalt`, and `harbor`. It deliberately
includes similar-sounding confusions `cobalt`/`cobol` and `harbor`/`arbor`.
These are innocuous benchmark tokens, not a product profanity list. The corpus
contains clean English speech; speech mixed with deterministic noise at several
SNRs; speech with synthetic music/game-like tones and effects; quiet speech at
-30 and -40 dBFS; silence; non-speech effects only; rapid speech; repeated
targets; similar-sounding words; and target words placed near clip starts and
ends. `ground_truth.json` records the actual generated clips and their source
parameters.

## Metrics and scoring conventions

Scoring is case-insensitive and Unicode-normalizes text with NFKC. Tokenization
extracts Unicode alphanumeric runs and retains internal apostrophes. Punctuation
is discarded; there is no stemming, number-word conversion, homophone
equivalence, or semantic matching. Thus `cobalt` and `cobol` are distinct.
WER is `(substitutions + deletions + insertions) / reference_word_count`;
an empty reference has WER 0 only when the hypothesis is also empty, otherwise
WER is undefined (`null`) and insertions are reported.

Target-word recall, precision, and F1 use exact normalized target occurrences:
true positives are matched target tokens, false negatives are omitted reference
targets, and false positives are extra hypothesized target tokens (including
targets emitted when absent from the reference). Duplicate occurrences count
individually. General WER insertions/deletions/substitutions are also reported.

For each correctly matched reference/hypothesis word pair with timestamps,
start and end timing error are absolute differences in milliseconds. Report
mean, median, and nearest-rank p95 separately for starts and ends. Also report
the fraction of these boundaries within 50, 100, and 200 ms. Missing or
non-finite timestamps do not enter the timing-error distribution.

Call `matched_word_pairs(reference_words, hypothesis_words)` from `score.py`
to reuse the WER Levenshtein path and get exact-word `(reference_index,
hypothesis_index)` pairs. Pass those pairs to `timing_metrics(..., matches=...)`
when timing word arrays differ; substitutions and insertions are intentionally
not timed as correct word matches.
Missing-alignment rate is the proportion of hypothesized words without a
complete finite start/end pair. A word error without a matched word is not
timed.

Hallucination on silence/non-speech is measured only on clips labeled
`silence` or `non_speech`: emitted word count per total such audio minute and
fraction of such clips with at least one emitted word. Real-time factor (RTF)
is inference wall time divided by clip audio duration (lower is faster).
Cold and warm runs are separate process launches: cold means the first measured
run in a fresh candidate process; warm means a subsequent process launch after
the candidate has been exercised once, with cache policy documented. Do not
conflate a fresh process with a guaranteed cold OS/filesystem cache.

Report peak process RAM as Windows `GetProcessMemoryInfo`'s
`PeakWorkingSetSize`, sampled/read for each process in the candidate's Windows
Job Object (or explicitly state that only the parent process was measured).
Report peak VRAM by sampling Windows PDH `GPU Process Memory(*)\Dedicated
Usage` and `Shared Usage` counters for candidate PID(s), at a stated interval;
reconcile with vendor/runtime telemetry when available. State the tool,
version, interval, and whether the number is per-process or adapter-wide.
A missing/unavailable reading is `null`, not zero. Runtime and model footprint
are separate: record runtime
package/version and installed footprint, model artifact byte size, and any
additional on-disk cache footprint. Measure model footprint by summing the
candidate's identified artifact files; identify the paths or artifact
manifest. These measurement definitions do not imply a GPU capability claim.

## Result record schema

Each JSON Lines record is one **candidate × clip × run** observation. The
following keys are required (values may be `null` only where specified):

```json
{
  "schema_version": 1,
  "candidate": "placeholder-name",
  "clip_id": "clean_001",
  "category": "clean_speech",
  "run": {"kind": "cold", "index": 0, "process_id": 1234},
  "hardware": {
    "cpu": "string", "gpu": "string or null", "ram_bytes": 0,
    "os": "string", "driver": "string or null"
  },
  "device": {"requested": "cpu", "actual": "cpu"},
  "runtime": {
    "name": "string", "version": "string", "package_version": "string",
    "installed_bytes": 0
  },
  "model": {
    "artifact_id": "string", "sha256": "64 lowercase hex characters",
    "bytes": 0, "cache_bytes": 0
  },
  "settings": {
    "language": "en", "sample_rate_hz": 16000, "channels": 1,
    "threads": 1, "decoding": {}
  },
  "input": {
    "sample_rate_hz": 16000, "channels": 1, "dtype": "float32",
    "clip_sha256": "64 lowercase hex characters"
  },
  "measurements": {
    "audio_duration_s": 0.0, "runtime_s": 0.0, "rtf": 0.0,
    "peak_ram_bytes": 0, "peak_vram_bytes": null,
    "peak_vram_method": "tool/version/interval or unavailable",
    "model_footprint_bytes": 0
  },
  "hypothesis": {"text": "", "words": []},
  "metrics": {}
}
```

Hypothesis word entries, when supplied, have `text`, `start_s`, and `end_s`;
timestamps can be null. Record exact requested versus actual device rather
than inferring actual execution from configuration or provider enumeration.
Store results as UTF-8 JSON Lines, one object per line, with the full settings
and artifact identity repeated on each record for standalone auditability.

## Equivalent-input rules

All candidates receive the same clip samples, segmentation, and thread count.
Decode/resample once in the harness to 16 kHz mono float32 PCM; provide the
same array values (and record a canonical input SHA-256) to every candidate.
No candidate-specific denoising, segmentation, language detection, or
pre/post-processing unless it is an explicitly evaluated setting applied
equivalently. English only (`en`). State any unavoidable adapter conversion.
Run order should be balanced/randomized and logged; do not change clips between
candidates. Corpus source audio may be WAV at the SAPI output rate, but this
canonical benchmark input transformation is identical for every candidate.

## Corpus generation and ground truth

Use `generate_corpus.py` with NumPy and the Windows built-in
`System.Speech.Synthesis` voices only; there are no downloaded speech assets.
SAPI `SpeakProgress` events provide independent word-boundary events, mapped
back to the known utterance words. The script cross-checks event positions
against a frame-RMS envelope on the speech-only SAPI waveform (before any
noise/effects mix) and records the check and raw event-derived word
intervals in `ground_truth.json`. SAPI boundaries are synthesized speech
progress callbacks, not a phonetic forced aligner; precision can be coarse or
voice-dependent. TTS lacks spontaneous delivery, accents, overlapping
speakers, and real game dialogue, so results do not establish performance on
game audio. Synthetic noise/effects are not representative game sound design.
Quiet scaling, mixing, event timing and RMS checks are documented per clip.

Example:

```powershell
uv run --python 3.14.10 --with numpy -- python -I `
  C:\code\muteinous-spike50\spike\asr50\benchmark\generate_corpus.py `
  --output C:\scratch\asr50\WP6\audio --seed 5017
uv run --no-project --with pytest `
  C:\code\muteinous-spike50\spike\asr50\benchmark\tests
```

The delegated preparation run uses a disposable uv environment under
`C:\scratch\asr50\WP6\venv`; no repository dependency manifest is changed.

## Corpus v2

The v1 `SpeakProgress` word timestamps drift relative to the synthesized audio;
they remain useful for transcript/lexical scoring only, not timing metrics.
Corpus v2 is generated by `corpus_v2/generate_corpus_v2.py` into scratch space
and does not change v1. The constructed timing set synthesizes each target or
distractor word independently with Microsoft Zira and Microsoft David, resamples
each isolated word to 16 kHz first, trims samples below absolute amplitude
`1e-4`, then concatenates the retained samples and digital-zero gaps directly
at 16 kHz (35 ms rapid; otherwise deterministic 40–300 ms gaps). Word start/end
times are exact sample indices / 16000. Every constructed clip has a separate
unmixed speech-only track under `C:\scratch\asr50\WP15\speech_only16k\`.
Generation asserts exact zero gap samples before writing. Noise/effects are
added only to word intervals in the benchmark mix; generation asserts the mix
is sample-aligned additive audio. Categories include clean, white/pink noise
at 10/0/-5 dB SNR, music/effects, -30/-40 dBFS, rapid, repetitions, similar
words (`cobalt`/`cobol`, `harbor`/`arbor`, and `banana`/`bandana`), and start/end
edge cases. `verify_corpus_v2.py` checks speech-only word/gap energy using 10 ms
RMS frames (excluding a 5 ms guard around boundaries); gap RMS must be below
1% of median word RMS, and it checks mixed-track sample alignment.

The natural set has 30 continuous sentences per voice synthesized in one pass,
four additional continuous multi-sentence clips per voice (approximately
15–45 seconds), plus silence, noise and effect-only clips from 2–30 seconds. It has transcript
ground truth but no word boundaries. Therefore lexical/WER, target-word and
silence-hallucination metrics apply to both sets; timing metrics apply only to
the constructed set. SAPI isolated-word prosody is unnatural, coarticulation is
absent, and neither set represents spontaneous speech or game dialogue.
Outputs are 16 kHz mono float32 WAVs; `ground_truth_v2.json` contains the
per-clip voice, category, seed, exact word times where available and WAV SHA-256.

### Reproducibility and source cache

SAPI input WAVs are stored once under
`C:\scratch\asr50\WP15\sapi_cache\`, named by SHA-256, and indexed by
voice+text in `manifest.json`. This content-addressed cache is the source
artifact for regenerations; generation from an existing cache does not call
SAPI again. Cache creation itself invokes the installed Windows SAPI voices and
is not promised reproducible across independent cache rebuilds.

`generate_corpus_v2.py --output-root <new-dir> --sapi-cache <cache-dir>`
creates separate outputs. To compare builds, use
`compare_generations.py <root-a> <root-b>`. Generation canonicalizes libsndfile
WAV `PEAK` chunk timestamps to zero because those fields otherwise contain the
wall-clock time even when PCM data is identical. It records layer hashes,
SAPI raw-WAV SHA-256, WAV chunk layout, and audio/header properties in
`diagnostics_v2.json`. Never regenerate in place over a frozen corpus.

Run using a disposable environment containing NumPy, SciPy and SoundFile:

```powershell
uv run --no-project --python 3.14.10 --with numpy --with scipy --with soundfile `
  python -I C:\code\muteinous-spike50\spike\asr50\benchmark\corpus_v2\generate_corpus_v2.py
uv run --no-project --python 3.14.10 --with numpy --with soundfile `
  python -I C:\code\muteinous-spike50\spike\asr50\benchmark\corpus_v2\verify_corpus_v2.py
```
