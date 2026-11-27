# M2.0 (#50) AMD hardware ASR investigation report

Temporary investigation record. Not an architecture decision, runtime/model selection, or production dependency change. D47 selection remains open. Three delegate-reviewer passes (same model, read-only) were completed and their corrections are incorporated. Date: 2026-11-26. The maintainer approved additional time beyond the original eight-hour budget after the first report.

Evidence levels: **L1** documented support, **L2** successful build/install, **L3** device enumeration, **L4** computation on the device, **L5** ASR inference. "GPU ran it" (L4/L5) is not "GPU result is correct" (see Moonshine on DirectML).

Scope limits for everything below: one machine (Ryzen 9 9900X + RX 7900 XT, Windows 11), English only, synthetic SAPI speech (not game dialogue). No NVIDIA or Intel evidence. Speed/RTF was deprioritized by the maintainer and incidental timings were taken under concurrent load, so no performance findings are claimed.

## 1. Repository and hardware state

| Item | Value |
|---|---|
| `main` | `a76f82d03fb021d096607d189c01498e66f433cf` |
| Spike branch / PR | `spike/issue-50-asr-dependency-probe`, draft PR #56 (unmerged) |
| whisper.cpp pin | `ggml-org/whisper.cpp@96ec4d9823e9d0211944172da35f9f29134af990` (1.9.6-dev) |
| CPU | AMD Ryzen 9 9900X, Zen 5, 12C/24T; AVX2, FMA, AVX-512 incl. VNNI; BF16 flag not reported |
| GPU | AMD Radeon RX 7900 XT, **discrete**, Navi 31 / RDNA3 / gfx1100, PCI 1002:744C; 20,420 MB dedicated + 16,201 MB shared; driver 32.0.32029.2010 |
| iGPU | not enumerated (Windows, dxdiag, Vulkan) |
| RAM / OS | 31.6 GiB; Windows 11 Pro build 26300 |
| APIs | D3D12 FL 12_2; Vulkan 1.4.359 (cooperative_matrix, fp16/int8, int dot); DirectML.dll present |
| Not installed | HIP SDK/ROCm, CMake, MSVC, Ninja, Vulkan SDK (nothing installed system-wide by this work) |
| Python / uv | CPython 3.14.10 via uv 0.13.9 (the whisper.cpp CLI driver script used system Python 3.12; the runtime under test is unaffected) |

## 2. Engineering time

Supervisor wall-clock 15:33 to 18:46 MT (about 3.2 h). Delegate effort is self-reported or estimated and ran in parallel: phase 1 (WP1-6 + review) about 2 h; phase 2 (WP7-14 + review 2) about 4.5 h; phase 3 (corpus v2, device guard, v2 re-runs, review 3) about 4 h. Approximate total 10 h of delegate effort plus 3.2 h supervisor wall-clock, **beyond the original eight-hour cap, which the maintainer extended** ("spend extra time"). Hours spent on #50 before this task were not provided.

## 3. Evidence and commands (reproducible)

- CI run [45908168976](https://github.com/heaje/muteinous/actions/runs/45908168976) builds whisper.cpp at the pin (CPU all-variants, Vulkan); workflow `.github/workflows/asr-whisper-backend-probe.yml`; diagnostic `spike/asr50/ggml-diag/devices.cpp`.
- Models: 31 approved files (3,106,591,908 bytes) downloaded from pinned revisions, staged, size and SHA-256 verified (`reports/WP7-download-results.json`); 7 reused local files from the older Hushpatch project verified against pinned hashes (`reports/WP13-hushpatch-model-copy.json`).
- Corpora: v1 (`generate_corpus.py`; 14 clips; lexical metrics valid, SAPI word times INVALID) and v2 (`benchmark/corpus_v2/`; 60 clips, 13.0 min, 2 voices; 30 constructed-boundary timing clips with exact sample boundaries verified acoustically on the speech-only tracks, 30 natural/silence/non-speech clips including 15-100 s clips). v2 was frozen read-only (manifest hashes verified) before evaluation. Regeneration is deterministic PCM-for-PCM from a SAPI WAV cache (libsndfile wrote a wall-clock timestamp into each WAV's PEAK chunk, which made whole-file hashes differ; fixed).
- Runners: `spike/asr50/runners/*`; device guard prototype: `spike/asr50/device_guard/` (13 tests pass per ORT wheel); all delegate reports and the three reviews: `spike/asr50/reports/`.
- Disposable envs: `uv venv --python 3.14.10`, `--only-binary :all:`, `HF_HUB_OFFLINE=1`.
- GPU proof method: ORT profiling JSON or verbose logs for node placement, Windows `GPU Engine(*)` and `GPU Process Memory(*)` counters filtered to the process ID, plus a CPU control; for whisper.cpp each Vulkan run had to log `using Vulkan0 backend` or the runner failed.

## 4. Runtime compatibility matrix (this machine)

| Runtime / artifact | CPU | AMD GPU path (RX 7900 XT) | Word timing |
|---|---|---|---|
| whisper.cpp, Turbo q5_0 and Small.en q5_1 | L5 | **Vulkan: L5, process GPU counters 31-56% engine, 1.04 GiB; 240/240 v2 Vulkan runs logged Vulkan0** | `-ml 1` and DTW (`-nfa`) native times |
| ORT + DirectML, Whisper Small.en fp16 (Hushpatch recipe) | L5 | **DirectML: L5; mixed DML/CPU placement; 59/60 v2 clips identical text to CPU** | none (text only) |
| ORT + DirectML, Whisper Large-v3 Turbo q4 | L5 | **DirectML: L5; MatMulNBits on DML; text identical to CPU on 60/60 clips; ~2.77 GiB** | none |
| sherpa-onnx 2.0.3 + Parakeet TDT 0.6B v2 int8 | L5 | none: `directml`/`cuda`/`dml` fall back to CPU with a warning; wheel has no DirectML | token times grouped to words |
| faster-whisper 1.2.1 / CT2 4.9.1, Small.en | L5 | none: `cuda` raises; `auto` -> CPU; no ROCm/HIP device | native DTW |
| Moonshine base int8 (HF ONNX) | L5 | **DirectML executes but output is corrupt** (see 8) | none |
| ORT Windows ML catalog providers | not tested (network + Windows App SDK; docs list CPython 3.10-3.13) | not tested | n/a |
| HIP/ROCm (whisper.cpp, CT2) | not tested (system HIP SDK not approved) | L1 only; CT2's Windows ROCm guide is a source-build recipe validated on RX 7900 XTX / Python 3.11 | n/a |

## 5. Lexical results (corpus v2, central rescore by reviewer 3)

WER is over the 40 transcript-bearing clips (1,208 words); target P/R over all 60 clips; hallucination over the 20 silence/non-speech clips. The timing set is isolated words (unnatural prosody), so WER differences of a few words are noise.

| Runner | Config / device | WER (S/D/I) | Target P/R | Hallucinated words/min | Clips with output |
|---|---|---:|---|---:|---:|
| Parakeet int8 | CPU | .0157 (16/3/0) | .980 / .853 | 0 | 0/20 |
| whisper.cpp Small.en | Vulkan | .0207 (16/6/3) | .980 / .836 | 16.6 | 10/20 |
| whisper.cpp Small.en | CPU | .0224 (17/5/5) | .980 / .828 | 37.6 | 10/20 |
| whisper.cpp Turbo | Vulkan | .0224 (18/0/9) | 1.000 / .853 | 6.3 | 16/20 |
| whisper.cpp Turbo | CPU | .0248 (21/0/9) | 1.000 / .828 | 5.8 | 16/20 |
| faster-whisper Small.en | beam5 + VAD | .0207 (19/4/2) | .970 / .828 | 0.7 | 1/20 |
| faster-whisper Small.en | beam5, no VAD | .0257 (23/0/8) | .970 / .828 | 7.6 | 16/20 |
| faster-whisper Small.en | beam1, no VAD | .0306 (26/1/10) | .969 / .810 | 6.0 | 13/20 |
| ORT Whisper Turbo q4 | CPU = DirectML | .0480 (19/37/2) | 1.000 / .845 | 3.1 | 13/20 |
| Moonshine base int8 | CPU | .0720 (41/16/30) | .967 / .750 | 0.2 | 1/20 |
| ORT Whisper Small.en fp16 | CPU = DirectML | .1233 (36/102/11) | .980 / .845 | 6.7 | 20/20 |

Corrections applied after review: WP10's originally reported target P/R did not reproduce (central values above are authoritative); WP13's earlier faster-whisper comparator (.2759) was withdrawn; v1 14-clip WER figures (e.g., Moonshine .224, faster-whisper no-VAD .224) are superseded by the larger set.

Observations (not rankings): Whisper-family models, without gating, emit text on silence/non-speech; faster-whisper's bundled Silero VAD removed almost all of it; an RMS energy gate prototype on Turbo q4 cut hallucination only from 3.1 to 2.0 words/min (it skipped pure-silence clips but not noise/music), and the generation config has no `no_speech_token_id`. whisper.cpp small.en hallucinated differently on CPU vs Vulkan (37.6 vs 16.6 words/min), so device changes can change silence behavior. ORT Whisper Small.en fp16 had the highest WER and the most deletions (102); the cause was not investigated (greedy decoding, fixed 30 s windows and the small model are candidates). Parakeet and whisper.cpp had the lowest WER. Whisper ONNX clips over 30 s used fixed non-overlapping 30 s windows (boundary words at risk).

## 6. Explicit-device and fallback behavior (D48/D49)

| Runtime | Behavior with a bad or unavailable GPU request |
|---|---|
| whisper.cpp `-dev 1`, `-dev 7`, nonexistent `GGML_VK_VISIBLE_DEVICES` | **exit 0, transcribes on CPU**, log only says `no GPU found`. Application must enforce no silent fallback |
| ORT DirectML, invalid `device_id` | DML-only provider list: raises. With `CPUExecutionProvider` also listed (the usual config): logs an error and returns a CPU session. Application must pick the provider list deliberately and verify actual placement |
| ORT `session.disable_cpu_ep_fallback=1` | fails whenever any node is CPU-assigned (all tested Whisper/Moonshine ONNX graphs have some), so strict mode is unusable as-is for these exports |
| sherpa-onnx | non-CPU provider request warns and runs on CPU; transcript still succeeds |
| faster-whisper | `device='cuda'` raises at construction; `device='auto'` resolves to CPU |

**Device guard prototype** (`spike/asr50/device_guard/`, 13 tests pass on both `onnxruntime-directml` 1.24.4 and `onnxruntime-windowsml` 1.30.1.202610302006): stable device keys from PCI vendor/device ids + name (via `ort.get_ep_devices()` metadata and `ggml-diag list`), ORT session factory with cpu/auto/explicit-gpu modes that disables ORT's retry and verifies DML profile events (raising typed errors on fallback), a whisper.cpp wrapper that validates the device before the run and parses logs after it (log parsing is the fragile signal; production should require a structured "actual device" API). Real-model guard test on the Whisper Small.en encoder (float32 input `(1,80,3000)`) succeeded on both wheels. The Windows ML wheel's import warning "Init provider bridge failed" did not block enumeration or guarded DML execution.

## 7. Word timing (corpus v2 exact boundaries)

Ground truth: 30 constructed clips, boundaries exact by construction (isolated SAPI words, amplitude-trimmed at 1e-4, digital-zero gaps of 40-300 ms), verified acoustically on speech-only tracks. These are reproducible trim edges, not human phonetic labels, so a systematic offset versus an aligner's notion of a word boundary is expected. v1's SAPI SpeakProgress times lag the audio by a growing amount and are withdrawn; all v1 timing numbers (273 ms Parakeet, 256/482 ms aligner, etc.) are invalid.

| Method | Matched words | Start error (mean / median / p95) | End error (mean / median / p95) | Notes |
|---|---:|---|---|---|
| Parakeet token times -> words (end = next-word start) | 75 | 61.9 / 48.5 / 160.0 ms | 137.8 / 137.0 / 298.2 ms | reproduced by review 3 |
| Parakeet (end = last token start + duration) | 75 | same starts | 132.6 / 136.2 / 281.2 ms | |
| faster-whisper DTW (beam5) | 71 | 74.5 / 23.8 / 280.8 ms | 168.7 / 170.2 / 319.2 ms | reproduced by review 3; VAD barely changes it |
| whisper.cpp DTW / `-ml 1` (all 8 configs) | see WP8 | median start 80-90 ms, median end 125-150 ms | | reproduced by review 3 |
| wav2vec2 CTC aligner on true transcript | 94 | mean abs 82 ms (signed +67 ms) | mean abs 147 ms (signed -147 ms) | WP14 figures, not independently recomputed by review 3 |
| Aligner vs native on identical ASR outputs (720 aligned outputs) | 434+ | 70.5 vs 91.6 ms | 130.9 vs 169.3 ms | WP14, not independently recomputed |

The aligner's asymmetric signed bias (starts late, ends early relative to trim edges) is consistent with trim-edge convention; a calibration could be tested on held-out data, none applied. The aligner's mean log-probability separated correctly recognized from inserted/substituted words with AUROC 0.934 (uncalibrated); empty text on silence returns nothing, but forced text on silence still receives an interval, so the score must gate hallucinated words. Caveat: timing clips are isolated words with large gaps, which is easier than natural speech; matcher ties on repeated words are deterministic but ambiguous.

## 8. Moonshine on DirectML: observed corruption, localized

On the 30 timing clips DirectML WER was 3.63 versus 0.54 on CPU (target P/R 0/0); the corruption varies per clip. A numerical probe found the first divergence on the **second decoder invocation (the first cached step): 14 NaN logits on DML, none on CPU**; the first step agrees. This localizes the failure to the cached-decoder execution on DML for this int8 export; it does not identify the operator or precision behavior. Treat as an unresolved provider/model defect, not proof of a general int8-on-DML problem.

## 9. Footprint

| Item | Bytes |
|---|---|
| whisper.cpp CPU all-variants build (exe+dll) | 11,703,296 |
| whisper.cpp Vulkan + CPU build | 54,137,344 (incl. 316,416 B build-only shader generator; `ggml-vulkan.dll` 42,117,632) |
| whisper.cpp runtime deps | MSVC runtime, OpenMP `vcomp140.dll`, driver `vulkan-1.dll`; no vendor SDK |
| ORT env sizes (post-install, incl. venv) | DirectML 170,074,007; Windows ML 142,340,453; CPU 121,507,852 |
| faster-whisper env | 267,087,721 (+ 486,098,798 model) |
| Earlier CI-measured installs | faster-whisper 262.85 MB, WinML 113.33 MB, Moonshine 82.71 MB, sherpa-onnx 52.94 MB |

## 10. Errors, warnings, unresolved blockers

- `onnxruntime-windowsml` prints "Init provider bridge failed" on import (the older project silenced it by redirecting stderr during import); DirectML still executes. The historical override remains a dependency-consistency failure (`uv pip check`); faster-whisper pulls `onnxruntime`, which conflicts by module name with the Windows ML wheel.
- whisper.cpp DTW requires flash attention off (`-nfa`), else it warns and returns no word times.
- ORT DirectML + `CPUExecutionProvider` in the provider list silently retries on CPU after a bad `device_id`.
- WP13's first report claimed a valid DirectML session failed; the corrected finding is that it failed only on the invalid-device retry path (and a later guard test failed from wrong input shape). Treat the first report as superseded.
- Untested: Windows ML catalog AMD provider, HIP/ROCm, NVIDIA and Intel hardware, iGPU, real game audio, whisper.cpp VAD (no VAD model approved), speed.
- The older Hushpatch project reported DirectML crashing when two sessions share a process, MIGraphX segfaulting on the second inference, and `add_provider_for_devices` running 4.5x slower; these were not independently tested here.
- Not independently verified by review 3: WP14's aggregate aligner numbers, WP15's header-vs-PCM determinism explanation (the report evidence is plausible and regen_a/regen_b match).

## 11. Model-artifact manifest (downloaded and verified; nothing further requested)

LFS SHA-256 values matched pinned metadata; small-file hashes observed on download are trust-on-first-use.

| Artifact | Repo @ revision | Bytes | License |
|---|---|---:|---|
| Whisper Large-v3 Turbo q5_0 (whisper.cpp) | `ggerganov/whisper.cpp@5359861c739e955e79d9a303bcbc70fb988958b1` | 574,041,195 | MIT |
| Whisper Small.en q5_1 (whisper.cpp) | same | 190,098,681 | MIT |
| Parakeet TDT 0.6B v2 int8 (sherpa-onnx) | `csukuangfj/sherpa-onnx-nemo-parakeet-tdt-0.6b-v2-int8@84b478d541cdbf0c296a7ab5f1e20a6f8f998114` | 661,288,526 | CC-BY-4.0 (attribution) |
| Moonshine base int8 ONNX | `onnx-community/moonshine-base-ONNX@b1e9b6aae3c3c7298f10c3798393fdf38e8fbbad` | 105,876,417 | MIT |
| Whisper Small.en CT2 (faster-whisper) | `Systran/faster-whisper-small.en@d1d751a5f8271d482d14ca55d9e2deeebbae577f` | 486,098,798 | MIT |
| Whisper Large-v3 Turbo q4 ONNX | `onnx-community/whisper-large-v3-turbo@360ebcde2559d60bb474678be3c1de9ef347d01a` | 1,089,188,291 | not stated in HF metadata |
| Whisper Small.en fp16 ONNX (reused from Hushpatch) | `onnx-community/whisper-small.en@482fb8ba081b6e906f92efe103622316b2a0cc69` | 766,415,222 | Apache-2.0 |
| wav2vec2-base-960h ONNX (reused from Hushpatch) | `onnx-community/wav2vec2-base-960h-ONNX@729c1a6730fb549c20a1c73a3d3f96f11020225e` | 377,912,249 | Apache-2.0 |

Moonshine Voice's own runtime fetches `.ort` files from `download.moonshine.ai` with no fixed commit or per-file SHA-256 (D144 would need a Muteinous-owned pinned manifest). Per issue #50, models are not to be mirrored in GitHub Releases.

## 12. Recommended next experiments

1. Obtain and test a speech-presence/VAD gate that works across runtimes (for example whisper.cpp's Silero VAD model, which needs maintainer approval to download); measure hallucination with and without it for each Whisper path.
2. Natural-speech timing ground truth (human-annotated or a licensed aligned corpus) to complement the isolated-word timing set; test aligner calibration on held-out clips.
3. Production-shaped wrapper experiments: device guard against real whisper.cpp and ORT use in a worker process, including the DirectML one-session-per-process claim.
4. A larger, more diverse lexical set (real-ish dialogue without game assets, more voices/accents, longer clips) before using small WER differences to choose.
5. If Moonshine stays a candidate: operator-level isolation of the cached-decoder NaN on DirectML.
6. Optional, needs approval: Windows ML catalog AMD provider; HIP SDK for whisper.cpp HIP / CT2 ROCm; NVIDIA and Intel runs on those machines; speed benchmarks on a quiet machine.

## 13. Decisions requiring maintainer approval

1. Whether to continue spending budget, and which of the next experiments.
2. Approval for system-level or new-download steps, if wanted: VAD model, HIP SDK, Windows ML catalog acquisition.
3. Whether to keep the temporary workflows on PR #56 (the maintainer chose "keep until selection").
4. Whether separate aligner-based word timing (wav2vec2 CTC, as the older project did) is acceptable under the SpeechAnalysisResult contract (D31/D66-D71), versus native ASR timestamps; the evidence above shows the aligner's starts at least as accurate as native DTW on isolated words, with per-word scores usable as a quality signal (D67-style).
5. Per-hardware model strategy (CPU, NVIDIA, AMD, Intel): this report supplies evidence only. On this AMD machine the working GPU routes are whisper.cpp Vulkan and ONNX Runtime DirectML with Whisper; Parakeet and faster-whisper are CPU-only here.
6. Runtime/model selection (D47) remains with the maintainer.
