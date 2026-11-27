# WP9 — sherpa-onnx Parakeet TDT 0.6B v2 int8

**Date:** 2026-11-26  
**Scope:** CPU recognition, word-time conversion and provider-selection probe on the approved benchmark artifacts. Timing/RTF work was deprioritized by the maintainer; no performance conclusion is reported.

## Outcome

The CPython 3.14.10 Windows wheel for `sherpa-onnx==2.0.3` loaded the approved int8 Parakeet artifact and transcribed all 14 canonical 16 kHz mono clips on CPU. The installed API signature and source confirmed `OfflineRecognizer.from_transducer(encoder, decoder, joiner, tokens, ..., provider=..., model_type=...)`; the runtime result exposes `tokens`, `timestamps` and `durations`. The runner uses `model_type="nemo_transducer"`, English audio, greedy decoding, 16 kHz, feature dimension 80 and no hotwords.

### Benchmark score

Scored with the repository's unchanged `benchmark/score.py` normalization/tokenization and alignment conventions:

| Measure | Result |
|---|---:|
| WER | **12.07%** (6 substitutions, 1 deletion, 0 insertions / 58 reference words) |
| Target precision | **96.67%** (29 TP, 1 FP) |
| Target recall | **82.86%** (29 TP, 6 FN) |
| Silence + non-speech hallucinations | **0 words/minute; 0/2 clips emitted words** |

Both very quiet clips (-30 and -40 dBFS) transcribed exactly. The 10 dB noise clip retained the three target words; at 0 dB the output was “Bananco Balt Harbor”; at -5 dB it was “America Province.” Similar-sounding `cobol` was recognized as `Cobalt`. Clean speech and effects, rapid/repeated speech, and both edge-placement clips were otherwise transcribed correctly.

### Word timestamps

The conversion works: token timestamps and durations were populated and all **57/57 hypothesized words** had finite start/end values. Rule used: a token beginning with SentencePiece `▁` or leading whitespace starts a word (the installed result represents these boundaries as leading whitespace); remove that boundary marker and append subsequent pieces. A word starts at its first token timestamp. Its end is the first token timestamp of the next word; for the final word, use its final token's timestamp plus that token's duration. Punctuation is retained in `text` but excluded from lexical word entries.

Across **51 correctly matched words**, against approximate SAPI event-derived ground truth, start error was mean **273 ms**, median **210 ms**, p95 **697 ms**; end error was mean **336 ms**, median **310 ms**, p95 **697 ms**. This is coarse alignment: token times advance in approximately 80 ms steps, and SAPI boundaries are not forced-alignment truth.

## Provider/hardware evidence

Machine: Windows 11 build 26300; AMD Ryzen 9 9900X; Radeon RX 7900 XT (driver 32.0.32029.2010 / Adrenalin 26.20.29.02).

| Requested provider | Observed behavior | Actual |
|---|---|---|
| `cpu` | Normal CPU run; all 14 clips decoded | CPU (L5: actual ASR inference) |
| `directml` | `DirectML is for Windows only. Fallback to cpu!` | CPU |
| `cuda` | `Please compile with -DSHERPA_ONNX_ENABLE_GPU=ON. Available providers: CPUExecutionProvider, . Fallback to cpu!` | CPU |
| `dml` | `Unsupported string: dml. Fallback to cpu` | CPU |

Each non-CPU request still returned a successful transcript, but the native runtime emitted an explicit fallback warning; fallback was not silent. Windows PDH `GPU Engine(*)\Utilization Percentage` and `GPU Process Memory(*)\Dedicated Usage` were polled at approximately 300 ms intervals and filtered to the candidate PIDs. The CPU control (PID 23612) and `directml` probe (PID 12416) each had **zero matching PID samples**. No GPU computation or GPU ASR inference was observed; VRAM is **unavailable/null, not zero**. CUDA's provider log enumerated only `CPUExecutionProvider` (L2 wheel installed; no GPU L3/L4/L5 evidence).

Because no GPU provider could be selected, placement/fallback of individual unsupported ONNX operators on a GPU was not testable.

The `directml` warning is consistent with a build lacking DirectML enablement, not with DirectML being unavailable on Windows generally. A documentation-only route would be a sherpa-onnx Windows CPython 3.14 x64 rebuild with `SHERPA_ONNX_ENABLE_DIRECTML=ON`, the required Windows SDK/toolchain, and a DirectML-enabled ONNX Runtime packaged with its runtime dependencies; then verify actual PID-filtered GPU execution and test model operator coverage. No build or SDK installation was attempted; CMake/MSVC are not installed in this environment. Upstream documents the CMake option and DirectML build requirements [here](https://github.com/k2-fsa/sherpa-onnx/blob/master/CMakeLists.txt) and [here](https://onnxruntime.ai/docs/execution-providers/DirectML-ExecutionProvider.html). DirectML's documented generic hardware support is not evidence this sherpa wheel or this model runs on the GPU (L1 only for the upstream provider).

## Reproduction and deliverables

Environment was disposable at `C:\scratch\asr50\WP9\venv`; offline flags `HF_HUB_OFFLINE=1`, `TRANSFORMERS_OFFLINE=1`, and `HF_HUB_DISABLE_TELEMETRY=1` were set. The supplied model/audio assets were read-only; no additional weights were downloaded.

```powershell
uv venv --python 3.14.10 C:\scratch\asr50\WP9\venv
uv pip install --python C:\scratch\asr50\WP9\venv\Scripts\python.exe --only-binary :all: sherpa-onnx==2.0.3 numpy psutil
uv pip install --python C:\scratch\asr50\WP9\venv\Scripts\python.exe --only-binary :all: soundfile
```

Installed support versions: NumPy 2.5.5, psutil 7.2.2, soundfile 0.14.0; `sherpa-onnx-core==2.0.3`. All 14 raw outputs are at `C:\scratch\asr50\results\sherpa-parakeet\cpu\`; `results.jsonl` and `score-summary.json` are at `C:\scratch\asr50\results\sherpa-parakeet\`. Runner and score adapter are under [`spike/asr50/runners/sherpa-parakeet/`](../../code/muteinous-spike50/spike/asr50/runners/sherpa-parakeet/) in the spike worktree. The model bundle totals **661,288,526 bytes**. Its recorded bundle digest is `63253c89bad0f27d7937480627131c96745ae3974d68a7c1f2e36cd32348be97`, computed as SHA-256 over the concatenated lowercase SHA-256 strings for encoder, decoder, joiner, then tokens; the individual source-file hashes are in `C:\scratch\asr50\reports\WP7-download-results.json`.

**Attribution / license:** The underlying model is NVIDIA's *Parakeet TDT 0.6B v2*, governed by **CC-BY-4.0**. Any redistribution or product use must provide appropriate credit to NVIDIA, link the [CC-BY-4.0 license](https://creativecommons.org/licenses/by/4.0/), and identify the sherpa-onnx ONNX/int8 export and other changes; do not imply NVIDIA endorsement. Source: [NVIDIA model card](https://huggingface.co/nvidia/parakeet-tdt-0.6b-v2), accessed 2026-11-26. The sherpa API example used to confirm construction and token timing is [offline-nemo-parakeet-decode-file.py](https://github.com/k2-fsa/sherpa-onnx/blob/master/python-api-examples/offline-nemo-parakeet-decode-file.py), accessed 2026-11-26.

## Summary (<300 words)

CPU functional support is confirmed (L5) for the approved Parakeet TDT 0.6B v2 int8 artifact using the CPython 3.14.10 `sherpa-onnx==2.0.3` Windows wheel. All 14 clips ran; WER was 12.07%, target precision 96.67%, target recall 82.86%, and silence/non-speech hallucination was 0 words/minute. Token timestamps/durations converted to finite word boundaries for all 57 hypothesis words; matched-word timing errors were roughly 273 ms mean start and 336 ms mean end, with the SAPI ground truth itself approximate.

No tested GPU provider was selected: `directml`, `cuda`, and `dml` all warned and fell back to CPU. The CPU-only provider listing and zero PID-filtered GPU-engine/dedicated-memory samples show no GPU use (no GPU L4/L5 evidence). A DirectML-enabled sherpa Windows wheel would require a source rebuild with `SHERPA_ONNX_ENABLE_DIRECTML=ON` and the Windows SDK/toolchain plus compatible packaged ONNX Runtime. Commands: created a disposable uv environment, installed binary wheels only, ran the 14-clip offline recognizer, and scored with unmodified `score.py`. Performance conclusions are omitted per maintainer priority. Estimated wall-clock effort: about 45 minutes, including serialized counter capture. No blocker remains; no build or maintainer approval is requested.

## Corpus v2

**Scope:** Re-ran the CPU recognizer over the frozen, read-only 60-clip `C:\scratch\asr50\corpus_v2_frozen\` corpus. Every WAV's supplied SHA-256 was verified before inference. No v1 raw results or scores were changed. The v1 SAPI timing results in the earlier sections are **withdrawn** because those boundaries are invalid; use only the exact constructed v2 timing set below.

### Lexical results

| Measure | Corpus v2 result |
|---|---:|
| Clips | 60 total: 30 `timing`, 30 `natural` |
| Speech clips scored for WER | 40; 1,208 reference words |
| WER | **1.57%** (16 substitutions, 3 deletions, 0 insertions) |
| Target metrics, all 60 clips | **99 TP, 2 FP, 17 FN** |
| Target precision / recall | **98.02% / 85.34%** |
| Silence/non-speech hallucination | **0 words/minute; 0/20 clips with output** |

WER is summed over transcript-bearing speech clips only. Target precision/recall includes all clips, including silence/non-speech negatives, using exact target occurrences. Silence/non-speech words/minute uses their combined audio duration.

### Exact-boundary timing results

Timing metrics use only the 30 `set="timing"` clips and exact `start_sample`/`end_sample` divided by 16,000. The unmodified `score.py` `matched_word_pairs()` helper supplied exact-word alignment pairs; errors below include only those matched pairs (**75 pairs**). There were **91 hypothesized timing-set words**; missing/non-finite alignments: **0/91 (0%)**.

| Boundary | End rule | Mean ms | Median ms | p95 ms | Within 50 ms | Within 100 ms | Within 200 ms |
|---|---|---:|---:|---:|---:|---:|---:|
| Start | First subtoken timestamp (common to both) | 61.94 | 48.50 | 160.00 | 50.67% | 84.00% | 100.00% |
| End | First token timestamp of next word; final word uses last token start + duration | 137.84 | 137.00 | 298.19 | 16.00% | 38.67% | 76.00% |
| End alternative | Last subtoken start + its duration for every word | 132.56 | 136.19 | 281.19 | 20.00% | 41.33% | 76.00% |

The end alternative modestly improved the aggregate mean/p95 and the 50/100 ms fractions on this timing set. It does not change starts or matched-pair selection.

### Long-clip behavior and artifacts

All 60 clips completed without a length error, truncation exception, or chunking. This included `natural_long` clips through 42.16 s and two transcript-only `natural_sentences` clips of 103.49 and 104.83 s. The process peak working set was **2,231,074,816 bytes** (parent process); no fixed chunking policy was needed. All inputs were passed as one full waveform to the offline recognizer.

Raw outputs, including `clip_set` and both word-end variants, are in `C:\scratch\asr50\results_v2\sherpa-parakeet\cpu\<clip>.json`; the 60-record `results.jsonl` and `score-summary.json` are in `C:\scratch\asr50\results_v2\sherpa-parakeet\`. Runner: `spike/asr50/runners/sherpa-parakeet/run_v2.py`; scorer: `spike/asr50/runners/sherpa-parakeet/score_v2.py`.

### Corpus v2 summary (<250 words)

Parakeet TDT 0.6B v2 int8 completed all 60 frozen corpus-v2 clips on CPU after SHA-256 validation. On 40 transcript-bearing clips (1,208 reference words), WER was 1.57%; target precision/recall across all clips were 98.02%/85.34%. The 20 silence/non-speech clips produced no text (0 words/minute, 0 clips with output). Exact timing was scored only on the 30 constructed clips using sample-index boundaries and `score.py`'s `matched_word_pairs`: 75 correctly matched words, 0/91 words missing alignments. Mean start error was 61.94 ms. For end boundaries, next-word-start gave mean 137.84 ms / p95 298.19 ms; last-subtoken-start-plus-duration gave mean 132.56 ms / p95 281.19 ms. Both rules and threshold fractions are tabulated above. No length failure occurred, even for the two ~104-second natural-sentence clips; peak parent working set was 2.23 GB and no chunking was needed. The previous v1 timing figures are withdrawn; no v1 result files were changed.

## VAD-masked v2

Ran Parakeet CPU on all 60 timeline-preserving masked clips (view A, **masked-run**), and computed view B (**gated-skip**) by replacing every manifest `gate_no_speech=true` output with empty text/words without invoking ASR for that clip. The unmasked-v2 column uses the existing `results_v2` outputs as baseline. The v1 and unmasked-v2 files remain unchanged. VAD flags: 20/60 clips; 19 were negative clips and one was the real-speech false negative `timing_noise_pink_-5_01`. The non-speech `nonspeech_pink_noise_30s` was passed by the gate.

### Lexical and hallucination comparison

| Pipeline view | Speech WER (S/D/I; 1,208 ref words) | Target P / R (TP/FP/FN; all clips) | Negative hallucination (words/min; clips with output) |
|---|---|---|---|
| Unmasked v2 | **1.57%** (16/3/0) | **98.02% / 85.34%** (99/2/17) | 0; **0/20** |
| A — masked-run | **1.82%** (15/7/0) | **97.96% / 82.76%** (96/2/20) | 0; **0/20** |
| B — gated-skip | **1.82%** (15/7/0) | **97.96% / 82.76%** (96/2/20) | 0; **0/20** |

The VAD false negative `timing_noise_pink_-5_01` has reference `banana cobalt harbor`. Unmasked ASR emitted three incorrect words; masking silenced the missed-speech interval, so A emitted nothing and B skips it: all three reference words are deletions in both views. The passed 30-second pink-noise clip produced no ASR text, so it did not add a hallucination.

### Timing comparison

Only the 30 `timing` clips were scored, against exact sample-index boundaries with `matched_word_pairs`. Error distributions are conditional on matched words; a gate-skipped clip has no matched words, rather than fabricated timing errors.

| View | Matched / hypothesis words; missing | Start mean / median / p95 ms | End: next-word-start mean / median / p95 ms | End: last-token-start + duration mean / median / p95 ms |
|---|---:|---:|---:|---:|
| Unmasked v2 | 75 / 91; 0 | 61.94 / 48.50 / 160.00 | 137.84 / 137.00 / 298.19 | 132.56 / 136.19 / 281.19 |
| A — masked-run | 72 / 87; 0 | 60.81 / 45.91 / 160.00 | 139.96 / 130.41 / 315.19 | 127.25 / 124.06 / 281.19 |
| B — gated-skip | 72 / 87; 0 | 60.81 / 45.91 / 160.00 | 139.96 / 130.41 / 315.19 | 127.25 / 124.06 / 281.19 |

For transparency, start-boundary fractions within 50/100/200 ms were 50.67/84.00/100.00% unmasked and 52.78/84.72/100.00% in both masked views. Next-word-start end fractions were 16.00/38.67/76.00% unmasked and 18.06/41.67/75.00% masked/gated. Last-token-duration end fractions were 20.00/41.33/76.00% unmasked and 25.00/44.44/76.39% masked/gated. The three fewer matched words in A/B include the missed-speech clip; apparent conditional-error improvement is not evidence the gate improved alignment.

Masked raw files, each with `clip_set` and `gate_no_speech`, are at `C:\scratch\asr50\results_v2_vadmasked\sherpa-parakeet\cpu\<clip>.json`; `results.jsonl` and `score-comparison.json` are alongside the `cpu` directory. The comparison JSON contains per-clip outputs for all three views. Runner/scorer: `run_vadmasked_v2.py` and `score_vadmasked_v2.py` in the sherpa-parakeet runner directory.

### VAD-masked v2 summary (<250 words)

All 60 timeline-preserving masked clips were decoded on CPU for A; B applies the manifest gate and skips all 20 flagged clips. Relative to unmasked v2, masked-run and gated-skip both move speech WER from 1.57% to 1.82%, and target recall from 85.34% to 82.76% (target precision 97.96%). Both views have zero negative-audio hallucinations. The VAD's real-speech miss, `timing_noise_pink_-5_01`, contains three reference words: unmasked ASR substituted three wrong words, while the masked audio is silent and B skips it, so A and B both count three deletions. The gate-passed 30-second non-speech pink-noise clip still yields empty ASR output. Timing on exact-boundary clips has 72 matched words in A/B versus 75 unmasked; the skipped clip is not assigned invented timing errors. Mean start error is 60.81 ms for A/B. End means are 139.96 ms using next-word-start and 127.25 ms using final-token-start-plus-duration. All timing clips finished with no alignment fields missing; the metrics are conditional on matched words, so the smaller match count must be considered alongside the error distributions. No v1 or unmasked-v2 outputs were modified.

## Corpus v3 — raw and VAD-masked CPU comparison

**Scope and method:** Parakeet TDT 0.6B v2 int8 was run on all 380 frozen v3 clips from raw audio and the timeline-preserving WP18 VAD-masked audio. Each input was SHA-256 checked against the raw ground truth or masked manifest before inference. CPU, four threads, greedy decoding, and 16 kHz mono were used. The VAD gate marks exactly 40/380 clips: all 40 non-speech clips; it flags no speech clip and passes no non-speech clip. View B-gated-skip is simulated by replacing masked text/words with empty output for flagged clips. Because no speech is gated, B-masked-run and B-gated-skip are identical on lexical speech metrics; the two non-speech views differ in that gated-skip avoids ASR output for the 40 negative clips.

### Overall lexical, target, and hallucination results

WER uses `benchmark/score.py` normalization and edit-distance conventions; speech WER excludes the 40 authored non-speech clips. Target-word counts cover all 380 clips.

| View | Speech WER (S/D/I; 2,807 reference words) | Target P / R / F1 (TP/FP/FN) | Non-speech hallucinations (words/min; clips with output) |
|---|---|---|---|
| A — raw | **6.16%** (130/34/9) | **90.32% / 84.85% / 87.50%** (56/6/10) | 0; **0/40** |
| B — masked-run | **6.31%** (131/37/9) | **90.32% / 84.85% / 87.50%** (56/6/10) | 0; **0/40** |
| B — gated-skip | **6.31%** (131/37/9) | **90.32% / 84.85% / 87.50%** (56/6/10) | 0; **0/40** |

### Speech WER by condition

Counts are reference words; each WER uses the same normalization as overall scoring. Gated-skip equals masked-run for all these conditions since the gate flags no speech.

| Speech condition | Clips / reference words | Raw WER | Masked-run / gated-skip WER |
|---|---:|---:|---:|
| Clean | 300 / 2,482 | 5.40% | 5.40% |
| Babble 10 dB | 4 / 34 | 5.88% | 5.88% |
| Babble 0 dB | 4 / 34 | 50.00% | 50.00% |
| Radio 8-bit | 5 / 41 | 12.20% | 9.76% |
| Pink noise 15 dB | 3 / 25 | 0.00% | 4.00% |
| Pink noise 5 dB | 3 / 26 | 0.00% | 0.00% |
| Pink noise 0 dB | 3 / 26 | 15.38% | 19.23% |
| White noise 15 dB | 3 / 26 | 7.69% | 7.69% |
| White noise 5 dB | 3 / 23 | 13.04% | 8.70% |
| White noise 0 dB | 3 / 21 | 4.76% | 14.29% |
| Reverb | 3 / 25 | 20.00% | 28.00% |
| Music loop | 3 / 22 | 0.00% | 0.00% |
| Game effects | 3 / 22 | 0.00% | 0.00% |

### Non-speech categories and gate results

| Negative category | Clips | Raw hallucination (words/min; clips with output) | Masked-run | Gated-skip |
|---|---:|---:|---:|---:|
| Silence + dither | 8 | 0; 0/8 | 0; 0/8 | 0; 0/8 |
| Room tone | 8 | 0; 0/8 | 0; 0/8 | 0; 0/8 |
| Music only | 8 | 0; 0/8 | 0; 0/8 | 0; 0/8 |
| Effects only | 8 | 0; 0/8 | 0; 0/8 | 0; 0/8 |
| Babble/noise only | 8 | 0; 0/8 | 0; 0/8 | 0; 0/8 |
| **All non-speech** | **40** | **0; 0/40** | **0; 0/40** | **0; 0/40** |

### Artifacts and interpretation

Raw per-clip JSON and 380-row JSONL are under `C:\scratch\asr50\results_v3\sherpa-parakeet\raw\cpu\`; masked equivalents are under `...\masked\cpu\`. JSONL files are in their respective `raw` and `masked` directories. `score-comparison.json` at the candidate root includes all views, by-condition/by-voice/by-rate summaries, and per-clip transcripts. Reproduction scripts are `run_v3.py --source raw|masked` and `score_v3.py` in `spike/asr50/runners/sherpa-parakeet/`. Peak process working set recorded on raw inference was 1,584,844,800 bytes. No speed conclusions are drawn.

### Corpus v3 summary (<250 words)

All 380 frozen v3 clips were decoded on CPU from raw and VAD-masked audio after source-hash checks. On 340 speech clips (2,807 reference words), raw WER was 6.16%; masked-run and gated-skip WER were 6.31%. Target precision/recall/F1 across all clips were 90.32%/84.85%/87.50% in each view (56 TP, 6 FP, 10 FN). Neither raw nor masked ASR hallucinated on any of the 40 authored non-speech clips; each of five negative categories had 0 words/minute and 0 clips with output. The gate flagged exactly those 40 negative clips and no speech clips, so gated-skip avoided decoding the negatives without changing speech metrics. By-condition results varied: masking matched raw on clean speech, babble, pink-noise 5/15 dB (apart from one new error at 15 dB), music, and game effects, while helping radio 8-bit and white-noise 5 dB and worsening several other noisy conditions. There are only three to five clips in most non-clean conditions, so these subgroup rates are descriptive, not stable comparative estimates. Peak working set was 1.58 GB. No speed/timing conclusions were requested or made.
