# M2.0 (#50) AMD hardware ASR investigation report

Temporary investigation record. Not an architecture decision, runtime/model selection, or production dependency change. D47 selection remains open. Four delegate-reviewer passes (same model, read-only) were completed and their corrections are incorporated; section 5 numbers are central rescores, not delegate self-reports. Date: 2026-11-26. The maintainer approved additional time beyond the original eight-hour budget after the first report.

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

Supervisor wall-clock 15:33 to about 21:40 MT (about 6.1 h). Delegate effort is self-reported or estimated and ran in parallel: phase 1 (WP1-6 + review) about 2 h; phase 2 (WP7-14 + review 2) about 4.5 h; phase 3 (corpus v2, device guard, v2 re-runs, review 3) about 4 h; phase 4 (VAD gate, corpus v3, masked/v3 re-runs, DirectML stability, timing-convention analysis, review 4 and reconciliations) about 5 h. Approximate total 15 h of delegate effort plus 6.1 h supervisor wall-clock, **beyond the original eight-hour cap, which the maintainer extended** ("spend extra time", "keep going"). Hours spent on #50 before this task were not provided.

## 3. Evidence and commands (reproducible)

- CI run [45908168976](https://github.com/heaje/muteinous/actions/runs/45908168976) builds whisper.cpp at the pin (CPU all-variants, Vulkan); workflow `.github/workflows/asr-whisper-backend-probe.yml`; diagnostic `spike/asr50/ggml-diag/devices.cpp`.
- Models: 31 approved files (3,106,591,908 bytes) downloaded from pinned revisions, staged, size and SHA-256 verified (`reports/WP7-download-results.json`); 7 reused local files from the older Hushpatch project verified against pinned hashes (`reports/WP13-hushpatch-model-copy.json`).
- Corpora: v1 (`generate_corpus.py`; 14 clips; lexical metrics valid, SAPI word times INVALID) and v2 (`benchmark/corpus_v2/`; 60 clips, 13.0 min, 2 voices; 30 constructed-boundary timing clips with exact sample boundaries verified acoustically on the speech-only tracks, 30 natural/silence/non-speech clips including 15-100 s clips). v2 was frozen read-only (manifest hashes verified) before evaluation. Regeneration is deterministic PCM-for-PCM from a SAPI WAV cache (libsndfile wrote a wall-clock timestamp into each WAV's PEAK chunk, which made whole-file hashes differ; fixed). Corpus v3 (`benchmark/corpus_v3/`; 380 clips, 27 min 18 s; transcript-only): 300 clean clips from 150 authored sentences in two SAPI voices at varied rate/volume, 40 noisy/acoustic variants (white/pink noise, babble, music loop, game effects, reverb, radio/8-bit; 3-5 clips per condition), and 40 non-speech clips; generated twice byte-identically and frozen.
- VAD gate: the Silero VAD ONNX model bundled inside the faster-whisper 1.2.1 wheel (package asset, not a download) was run by an independent NumPy/ORT implementation (`vad_gate/apply_gate.py`; segments identical to faster-whisper's on 8 checked clips) and used to produce time-aligned "masked" copies of v2 and v3 (non-speech samples set to digital zero, same length). "Gated-skip" means ASR is skipped for clips with no detected speech.
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

Observations (not rankings): Whisper-family models, without gating, emit text on silence/non-speech; faster-whisper's bundled Silero VAD removed almost all of it; an RMS energy gate prototype on Turbo q4 cut hallucination only from 3.1 to 2.0 words/min (it skipped pure-silence clips but not noise/music), and the generation config has no `no_speech_token_id`. whisper.cpp small.en hallucinated differently on CPU vs Vulkan (37.6 vs 16.6 words/min), so device changes can change silence behavior. ORT Whisper Small.en fp16 had the highest WER and the most deletions (102); WP13 audited the worst chunks and found no runner bug: the decoder was active, below its token cap, and emitted a single token followed by EOS (early end-of-text), so the deletions are model behavior under greedy decoding and fixed 30 s windows (the underlying reason is not established). Parakeet and whisper.cpp had the lowest WER. Whisper ONNX clips over 30 s used fixed non-overlapping 30 s windows (boundary words at risk).

### 5.1 Speech-presence gate (Silero VAD) on corpus v2

Recommended setting (threshold 0.5, 100 ms speech pad, 200 ms minimum silence). On the 30 exact-boundary timing clips it covered 93.4% of word samples (4 words had no overlap) with 97.3% of gated speech inside words +/-40 ms. It returned zero segments on 19/20 v2 silence/non-speech clips; the exception was `nonspeech_pink_noise_30s` (pink noise briefly classified as speech). It also wrongly flagged real speech in `timing_noise_pink_-5_01` (speech at -5 dB SNR in pink noise). Threshold 0.3/pad 200 ms raised recall to 98.3% and cut 1 word but let 3/20 non-speech clips trigger; threshold 0.7 silenced all non-speech but cut 5 words. Quiet (-40 dBFS) synthetic speech was retained. On corpus v3 the gate flagged 0/340 speech clips and all 40/40 non-speech clips, but v3 non-speech clips are silence, dither, noise, music and effects without a speech-like decoy, and real game audio is not tested. The v2 miss and the v2 pass show the gate is not perfect on noisy speech and on noise at the speech level.

### 5.2 VAD-masked v2 (central rescore, review 4)

"Masked" = ASR on every masked clip; "gated" = flagged clips skipped. v2 non-speech: 20 clips.

| Runner / config | View | WER (S/D/I) | Target P/R | Halluc. words/min; clips with output |
|---|---|---:|---|---:|
| Parakeet CPU | masked / gated | .0182 (15/7/0) | .980 / .828 | 0; 0/20 |
| whisper.cpp Small.en CPU | masked / gated | .0190 (15/6/2) | .980 / .836 | 0.22; 1/20 |
| whisper.cpp Small.en Vulkan | masked / gated | .0224 (19/6/2) | .980 / .828 | 0.22; 1/20 |
| faster-whisper beam5, VAD off | masked | .0224 (17/5/5) | .970 / .836 | 4.25; 19/20 |
| faster-whisper beam5, VAD off | gated | .0224 (16/6/5) | .970 / .836 | 0; 0/20 |
| whisper.cpp Turbo Vulkan | masked / gated | .0306 (20/1/16 / 18/3/16) | 1.000 / .828 | 8.73; 20/20 / 0.22; 1/20 |
| whisper.cpp Turbo CPU | masked / gated | .0315 (21/1/16 / 19/3/16) | 1.000 / .819 | 8.73; 20/20 / 0.22; 1/20 |
| ORT Turbo q4 (CPU = DML) | masked / gated | .0505 (19/39/3 / 18/40/3) | 1.000 / .828 | 4.48; 20/20 / 0.22; 1/20 |
| Moonshine CPU | masked / gated | .0654 (39/19/21) | .966 / .741 | 0; 0/20 |
| ORT Small.en fp16 (CPU = DML) | masked / gated | .1209 (34/105/7 / 33/106/7) | .980 / .836 | 4.48; 20/20 / 0.22; 1/20 |

- Masking alone does not stop Whisper-family hallucination: digital silence still produces text (ORT Turbo q4 emits "you" on silence; whisper.cpp Turbo and ORT Small.en produce output on 20/20). The gate only works as a skip decision made before ASR. With the skip, hallucination falls to the single clip the gate passed (the pink-noise 30 s clip).
- The gate's one miss on real speech (`timing_noise_pink_-5_01`) turns into deletions: gated numbers pay about 3 extra deletions in the totals above.
- Whisper.cpp Turbo masked/gated insertions (16 vs 9 unmasked) are higher than unmasked, so masking is not free on this runner; the cause was not investigated.

### 5.3 Corpus v3 (380 clips, lexical stress set; central rescore, review 4)

WER is over the 340 speech clips (2,807 reference words). Target P/R covers banana/cobalt/harbor with distractors (66 target occurrences, so a handful of words moves the figures). "Raw" = unmasked input. "Halluc." = words/min over the 40 non-speech clips (raw view unless noted).

| Runner | Config | Raw WER (S/D/I) | Masked/gated WER | Target P/R (raw) | Halluc. raw; clips with output | Masked-all decode |
|---|---|---:|---:|---|---:|---|
| Parakeet int8 | CPU | .0616 (130/34/9) | .0631 | .903 / .848 | 0; 0/40 | 0; 0/40 |
| whisper.cpp Turbo | Vulkan | .0638 (132/41/6) | .0663 | .913 / .955 | 4.77; 18/40 | 10.3; 40/40 |
| whisper.cpp Turbo | CPU | .0638 (135/38/6) | .0666 | .913 / .955 | 4.65; 18/40 | 10.3; 40/40 |
| ORT Turbo q4 | CPU = DML | .0631 (136/27/14) | .0634 | .914 / .970 | 2.97; 19/40 | 5.16; 40/40 |
| faster-whisper Small.en | beam5, VAD off | .0730 (165/25/15) | .0759 | .900 / .955 | 5.16; 33/40 | 5.16; 40/40 |
| faster-whisper Small.en | beam5, built-in VAD | .0730 (165/25/15) | n/a | .900 / .955 | 0; 0/40 | n/a |
| ORT Small.en fp16 | CPU = DML | .0777 (171/31/16) | .0787 | .914 / .970 | 4.26; 33/40 | 5.16; 40/40 |
| whisper.cpp Small.en | CPU | .0887 (173/62/14) | .0891 | .914 / .803 | 3.61; 13/40 | 0; 0/40 |
| whisper.cpp Small.en | Vulkan | .0908 (176/64/15) | .0901 | .915 / .818 | 3.74; 13/40 | 0; 0/40 |
| Moonshine base int8 | CPU | .1240 (239/78/31) | .1343 | .877 / .864 | 0; 0/40 | 0; 0/40 |

Gated-skip (flagged clips skipped, which here was exactly the 40 non-speech clips) reduced hallucination to 0 words and 0/40 clips for every runner, with no speech clip skipped; its WER equals the masked WER. faster-whisper's built-in VAD gave the same WER as no VAD (7.30%), no empty outputs on the 340 speech clips, and 0/40 non-speech output.

- GPU vs CPU: ORT Turbo q4 CPU and DML text agreed on 380/380 clips raw and masked; ORT Small.en 380/380 raw and 379/380 masked (one reverb clip, a "brake"/"break" difference). whisper.cpp Vulkan and CPU transcripts differed on 7-17 clips depending on model and view (per WP8, not independently recounted); WER differed by at most 0.2 points.
- Condition difficulty: 3-5 clips per noisy condition, so per-condition rates are anecdotal, not rankings. Raw input, babble 0 dB (4 clips): whisper.cpp Small.en 61.8% WER, Parakeet 50%, whisper.cpp Turbo 17.6%. Raw white noise 0 dB (3 clips): whisper.cpp Small.en 23.8%, whisper.cpp Turbo 9.5%, Parakeet 4.8%. Clean (300 clips): Parakeet 5.4%, whisper.cpp Turbo 6.2%, whisper.cpp Small.en 8.0%; ORT Turbo q4 masked 5.6% clean, 41% babble 0 dB, 19% white 0 dB. The full per-condition tables are in `reviewer4/scores.json` and the WP8-WP13 v3 sections.
- Masking cost without any clip flagged: Parakeet +4 errors (+0.14 pp; 5 clips worse, 3 better), Moonshine +29 (+1.03 pp; one repeated-output music clip contributes 14), ORT Small.en CPU +3 (+0.11 pp; 2 worse, none better), whisper.cpp Turbo about +0.25-0.3 pp. The cause was not isolated (the largest changes are in noisy/reverb clips where masking removes low-level audio). These are small paired differences on a fixed finite set and say nothing about statistical significance.
- The target-word precision/recall values above come from per-clip `score.target_metrics` summed over clips. Several delegates had first aggregated target tokens across clips (WP10, WP11) or aligned tokens across clip boundaries for WER (WP13, an 8-substitution difference); all were corrected to the central rescore (review 4, `reviewer4/rescore.py`).

## 6. Explicit-device and fallback behavior (D48/D49)

| Runtime | Behavior with a bad or unavailable GPU request |
|---|---|
| whisper.cpp `-dev 1`, `-dev 7`, nonexistent `GGML_VK_VISIBLE_DEVICES` | **exit 0, transcribes on CPU**, log only says `no GPU found`. Application must enforce no silent fallback |
| ORT DirectML, invalid `device_id` | DML-only provider list: raises. With `CPUExecutionProvider` also listed (the usual config): logs an error and returns a CPU session. Application must pick the provider list deliberately and verify actual placement |
| ORT `session.disable_cpu_ep_fallback=1` | fails whenever any node is CPU-assigned (all tested Whisper/Moonshine ONNX graphs have some), so strict mode is unusable as-is for these exports |
| sherpa-onnx | non-CPU provider request warns and runs on CPU; transcript still succeeds |
| faster-whisper | `device='cuda'` raises at construction; `device='auto'` resolves to CPU |

**Device guard prototype** (`spike/asr50/device_guard/`, 13 tests pass on both `onnxruntime-directml` 1.24.4 and `onnxruntime-windowsml` 1.30.1.202610302006): stable device keys from PCI vendor/device ids + name (via `ort.get_ep_devices()` metadata and `ggml-diag list`), ORT session factory with cpu/auto/explicit-gpu modes that disables ORT's retry and verifies DML profile events (raising typed errors on fallback), a whisper.cpp wrapper that validates the device before the run and parses logs after it (log parsing is the fragile signal; production should require a structured "actual device" API). Real-model guard test on the Whisper Small.en encoder (float32 input `(1,80,3000)`) succeeded on both wheels. The Windows ML wheel's import warning "Init provider bridge failed" did not block enumeration or guarded DML execution.

### 6.1 DirectML process-model stability (WP19, onnxruntime-directml 1.24.4, Whisper Small.en fp16, RX 7900 XT)

Each experiment ran in a child process with a hard timeout; the System event log showed no display-driver reset around these tests (a negative result, not proof of none).

| Experiment | Outcome |
|---|---|
| 200 sequential encoder runs, one session | completed; output identical to the first run; working set steady at about 212 MB (no growth during the loop); per-process GPU memory was not obtainable |
| Two sessions, one process, alternating sequential calls | completed; encoder outputs bit-identical |
| Two sessions, one process, two threads concurrently | **crashed: exit code 0xC0000005 (access violation)**, no output, not a timeout |
| 2, 3 and 4 separate processes, each its own session, concurrent | all completed; transcripts matched the CPU transcript |
| whisper.cpp Vulkan process concurrent with a DirectML process | both completed (short co-run only) |
| 20 encoder create/destroy cycles | completed |
| Full Whisper create/destroy loop | timed out at 300 s (not diagnosed) |
| Providers list vs `add_provider_for_devices` | not tested: the API is not exposed in ORT 1.24.4's Python wheel, so the older project's "4.5x slower" claim stays untested |
| Low-GPU-memory behavior | not run: free-VRAM telemetry was not reliable enough to target a safe level |
| Windows ML wheel concurrency | one inference only |

This supports the older project's one-session-per-process design for parallel GPU work (L5 evidence on this machine only). It does not show that threaded use is safe, how much VRAM each process holds, or what happens near GPU memory exhaustion.

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

### 7.1 Boundary-convention sensitivity (WP20)

The 1e-4 trim edges include low-energy tails. Against 94 constructed words, boundaries re-derived where the smoothed envelope exceeds -20/-30/-40 dB re peak move inward by a mean 42-73 ms at starts and 56-112 ms at ends (David's offsets are larger than Zira's). WP20 reproduced the aligner oracle (WP14) and Parakeet (WP9) trim-edge numbers exactly before re-scoring.

Mean absolute error in ms, trim-edge convention (as in the table above) versus -20 dB re peak:

| Method | Start MAE: trim -> -20 dB | End MAE: trim -> -20 dB | Matched words at -20 dB |
|---|---|---|---:|
| wav2vec2 aligner on true transcript | 82 -> 30.7 (within 100 ms: 95.7%) | 147 -> 47.9 (end bias -147 -> -35 ms) | 94 |
| Parakeet, next-word end rule | 62 -> 64.9 | 138 -> 221.6 (bias +216 ms) | 75 |
| Parakeet, duration end rule | 62 -> 64.9 | 133 -> 216.3 (bias +211 ms) | 75 |
| faster-whisper DTW, beam5 | 74.5 -> 103.9 | 169 -> 97.2 | 71 |
| whisper.cpp Small.en DTW / `-ml 1`, CPU and Vulkan | not tabulated here (see WP8) -> 52-57 | -> 74-83 | 72-74 |
| whisper.cpp Turbo DTW / `-ml 1`, CPU and Vulkan | not tabulated here (see WP8) -> 67-87 | -> 167-183 | 73-76 |

Conclusions that survive both conventions: the aligner on the true transcript has the lowest start and end error of every method; Whisper Turbo word ends stay about 167-183 ms off; Parakeet word ends come out late by about 210-220 ms at -20 dB. Conclusions that depend on the convention: whether ends are worse than starts (true for the aligner against trim edges, false against -20 dB, where its ends are only 17 ms worse), faster-whisper's start and end ranking (its start error grows and its end error shrinks), and all absolute millisecond figures, which are relative to a boundary definition and not a human label. Held-out calibration: a fixed offset fitted on one voice often does not help the other (Zira-fitted start correction raised David's start MAE 51.5 -> 79.1 ms); category-fitted offsets help in some directions only. No fixed calibration is recommended, and none was applied to any results file.

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
- Untested: Windows ML catalog AMD provider, HIP/ROCm, NVIDIA and Intel hardware, iGPU, real game audio, whisper.cpp's own VAD (no VAD model approved), speed, low-VRAM behavior, per-process VRAM.
- The older Hushpatch project's DirectML two-session crash claim was reproduced (6.1); its MIGraphX segfault and `add_provider_for_devices` 4.5x slowdown were not tested.
- Not independently recomputed by any review: WP14's aggregate aligner numbers (WP20 reproduced its oracle trim-edge figures) and WP15's header-vs-PCM determinism explanation (regen_a/regen_b match).
- Process note: three delegates (WP10, WP11, WP13) initially computed target or WER aggregates across clip boundaries; review 4 caught this and the figures in this report are the per-clip central values. Delegates repeatedly stopped before finishing queued work and needed follow-ups.
- Hallucination on non-speech depends on masking: masking leaves digital silence, which still makes ORT Turbo q4 emit "you" (40/40 clips) and whisper.cpp Turbo emit text (40/40); only skipping ASR for gate-flagged clips removed it.

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

1. Done in this report with the faster-whisper-bundled Silero model (5.1-5.3). Open: whisper.cpp's own VAD path (needs a model download approval), and testing the gate on real game audio, quiet or distant speech, and speech-like decoys (TV, crowd), where it can miss speech or pass noise (one of each on v2).
2. Natural-speech timing ground truth (human-annotated or a licensed aligned corpus) to complement the isolated-word timing set; the convention sensitivity in 7.1 shows absolute timing numbers cannot be settled without it.
3. Production-shaped wrapper experiments: device guard against real whisper.cpp and ORT use in a worker process; a one-session-per-process worker pool on DirectML (6.1 shows it works for 2-4 processes in a short test) with per-process VRAM, low-VRAM and long-run behavior.
4. Real-ish dialogue and more voices/accents/longer clips: corpus v3 is synthetic SAPI speech with only 3-5 clips per acoustic condition, so condition rankings are anecdotal.
5. If Moonshine stays a candidate: operator-level isolation of the cached-decoder NaN on DirectML.
6. Optional, needs approval: Windows ML catalog AMD provider; HIP SDK for whisper.cpp HIP / CT2 ROCm; NVIDIA and Intel runs on those machines; speed benchmarks on a quiet machine.

## 13. Decisions requiring maintainer approval

1. Whether to continue spending budget, and which of the next experiments.
2. Approval for system-level or new-download steps, if wanted: a VAD model for whisper.cpp's own VAD path (the gate used here is the model bundled in the faster-whisper wheel), HIP SDK, Windows ML catalog acquisition.
   - Related design point: if a speech gate is adopted, the pipeline must skip ASR for non-speech (masking is not enough), and decide how to handle the gate's misses on noisy speech.
3. Whether to keep the temporary workflows on PR #56 (the maintainer chose "keep until selection").
4. Whether separate aligner-based word timing (wav2vec2 CTC, as the older project did) is acceptable under the SpeechAnalysisResult contract (D31/D66-D71), versus native ASR timestamps; the evidence above shows the aligner more accurate than every native timestamp method on isolated words under both boundary conventions tested (7.1), with per-word scores usable as a quality signal (D67-style); it was not tested on natural speech, and a fixed calibration did not generalize.
5. Per-hardware model strategy (CPU, NVIDIA, AMD, Intel): this report supplies evidence only. On this AMD machine the working GPU routes are whisper.cpp Vulkan and ONNX Runtime DirectML with Whisper; Parakeet and faster-whisper are CPU-only here.
6. Runtime/model selection (D47) remains with the maintainer.
