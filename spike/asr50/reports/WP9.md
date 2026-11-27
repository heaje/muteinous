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
