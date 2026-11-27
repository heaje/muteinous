# M2.0 (#50) AMD hardware ASR investigation report

Temporary investigation record. Not an architecture decision, runtime/model selection, or production dependency change. D47 selection remains open. Two delegate-reviewer passes (same model, read-only) were completed; their corrections are incorporated. Date: 2026-11-26.

Evidence levels: **L1** documented support, **L2** successful build/install, **L3** device enumeration, **L4** actual computation on the device, **L5** actual ASR inference. "GPU ran it" (L4/L5) is not "GPU result is correct": see Moonshine on DirectML.

Scope limits that apply to everything below: 14 synthetic clips (35 s, SAPI voice, English), 58 reference words, one machine (Ryzen 9 9900X + RX 7900 XT). It is not game dialogue and not NVIDIA or Intel evidence. Timing/speed was deprioritized by the maintainer and the incidental timings were taken under concurrent load, so none are reported as findings.

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
| Not installed | HIP SDK/ROCm, CMake, MSVC, Ninja, Vulkan SDK (none installed locally) |
| Python / uv | CPython 3.14.10 via uv 0.13.9 (whisper.cpp driver script used system Python 3.12; the runtime under test is unaffected) |

## 2. Engineering time

Supervisor wall-clock 15:33 to about 17:15 MT. Delegate effort is self-reported or estimated and ran in parallel: phase 1 (WP1-6 + review) about 2 h; phase 2 (WP8-14 + review 2) about 4.5 h. Approximate total 6.5 h of delegate effort plus about 1.7 h supervisor wall-clock, **likely at or past the eight-hour cap** counting everything, and hours spent on #50 before this task were not provided. No further experiments should start without maintainer direction.

## 3. Evidence and commands (reproducible)

- CI run [45908168976](https://github.com/heaje/muteinous/actions/runs/45908168976) builds whisper.cpp at the pin (CPU all-variants, Vulkan); workflow `.github/workflows/asr-whisper-backend-probe.yml`; diagnostic `spike/asr50/ggml-diag/devices.cpp`.
- Models: 31 files, 3,106,591,908 bytes, downloaded from pinned revisions into staging, size and SHA-256 verified before use (`reports/WP7-download-results.json`); the 7 reused Hushpatch files were hash-verified against pinned values (`reports/WP13-hushpatch-model-copy.json`).
- Corpus: `spike/asr50/benchmark/` (generator, scorer, tests); shared 16 kHz mono float32 inputs resampled once (`scipy.signal.resample_poly`).
- Runners: `spike/asr50/runners/{whispercpp,sherpa-parakeet,faster-whisper,moonshine-onnx,ort-whisper-turbo,ort-whisper-small-en,wav2vec2-aligner}`. Delegate reports WP1-WP14 and both reviews: `spike/asr50/reports/`.
- Disposable envs: `uv venv --python 3.14.10`, `--only-binary :all:`, `HF_HUB_OFFLINE=1`.
- GPU proof method: ORT profiling JSON / verbose logs for node placement, and Windows `GPU Engine(*)` and `GPU Process Memory(*)` counters filtered to the process ID, with a CPU control.

## 4. Runtime compatibility matrix (this machine)

| Runtime / artifact | CPU | AMD GPU path | Word timing |
|---|---|---|---|
| whisper.cpp, Turbo q5_0 and Small.en q5_1 | L5, WER .190-.241 | **Vulkan: L5, proven by process GPU counters (31-56% engine, 1.04 GiB)** | `-ml 1`/DTW ran (DTW needs flash attention off); accuracy unvalidated |
| ONNX Runtime + DirectML, Whisper Small.en fp16 (Hushpatch recipe) | L5, WER .190 | **DirectML: L5, WER .172, mixed DML/CPU placement, counters verified** | none (text only) |
| ONNX Runtime + DirectML, Whisper Large-v3 Turbo q4 | L5, WER .155 | **DirectML: L5, identical output to CPU, MatMulNBits on DML, ~2.77 GiB** | none |
| sherpa-onnx 2.0.3 + Parakeet TDT 0.6B v2 int8 | L5, **WER .121** | none: `directml`/`cuda`/`dml` all fall back to CPU with a warning; wheel lacks DirectML | token times grouped to words (see 7) |
| faster-whisper 1.2.1 / CT2 4.9.1, Small.en | L5, WER .138 with bundled Silero VAD (.224 without) | none: `cuda` raises a driver error, `auto` -> CPU, ROCm/HIP not accepted | native DTW |
| Moonshine base int8 (HF ONNX) | L5, WER .224 | DirectML executes but output is corrupt (WER 2.14, target 0/0); cause unproven | none |
| ORT Windows ML catalog providers | not tested (needs network + Windows App SDK; docs list CPython 3.10-3.13) | not tested | n/a |
| HIP/ROCm (whisper.cpp, CT2) | not tested (needs system HIP SDK; not approved) | L1 only; CT2's Windows ROCm guide is a source-build recipe validated on RX 7900 XTX / Python 3.11 | n/a |

## 5. Central rescore (one scorer, raw per-clip outputs; reviewer 2)

| Runner | Config / device | WER (S/D/I) | Target precision / recall | Silence + non-speech words/min |
|---|---|---:|---|---:|
| sherpa-parakeet | CPU | .1207 (6/1/0) | .967 / .829 | 0 |
| faster-whisper | beam5 + VAD | .1379 (6/0/2) | .968 / .857 | 0 |
| faster-whisper | beam5, no VAD | .2241 (6/0/7) | .968 / .857 | 75 |
| faster-whisper | beam1, no VAD | .2241 (7/0/6) | 1.000 / .829 | 60 |
| moonshine-onnx | CPU | .2241 (8/1/4) | .966 / .800 | 0 |
| moonshine-onnx | **DirectML** | **2.1379** (57/0/67) | 0 / 0 | 0 |
| ort-whisper-turbo (q4) | CPU | .1552 (7/0/2) | .938 / .857 | 30 |
| ort-whisper-turbo (q4) | DirectML | .1552 (7/0/2) | .938 / .857 | 30 |
| ort-whisper-small-en (fp16) | CPU | .1897 (7/0/4) | 1.000 / .829 | 30 |
| ort-whisper-small-en (fp16) | DirectML | .1724 (6/0/4) | .968 / .857 | 30 |
| whisper.cpp turbo | Vulkan GPU | .2069 (8/1/3) | .966 / .800 | 45 |
| whisper.cpp turbo | CPU | .2414 (8/1/5) | .966 / .800 | 45 |
| whisper.cpp small.en | Vulkan GPU / CPU | .1897 (7/0/4) | .967 / .829 | 30 |

Corrections applied after review: WP13's faster-whisper comparison figure of .2759 matches no configuration and is withdrawn (use the configuration-specific figures above). The 14-clip, 58-word set means a single word changes WER by 1.7 points; do not rank candidates on differences smaller than a few words.

Silence/non-speech output: faster-whisper without VAD and the Whisper ONNX models emit text ("you", "Thank you", "Bang", "gun shots"); whisper.cpp small.en emitted `[BLANK_AUDIO]` on the silent clip (a control marker, normalized to empty). VAD (faster-whisper's bundled Silero) removed all of it; no VAD was available for whisper.cpp (not approved). The real pipeline needs silence gating.

## 6. Explicit-device and fallback behavior (D48/D49)

| Runtime | Behavior with a bad or unavailable GPU request |
|---|---|
| whisper.cpp `-dev 1`, `-dev 7`, nonexistent `GGML_VK_VISIBLE_DEVICES` | **exit 0, transcribes on CPU**, log only says `no GPU found`. `-ng` is an explicit logged CPU choice. Application must enforce no silent fallback |
| ORT DirectML, invalid `device_id` | with DML as the only provider: session creation raises (`887A0002`). With `CPUExecutionProvider` also listed (the usual config): logs an error and returns a CPU session. **Application must pick the provider list deliberately and verify actual providers** |
| ORT `session.disable_cpu_ep_fallback=1` | session creation fails when any node is CPU-assigned (all three Whisper/Moonshine ONNX graphs have CPU-assigned nodes), so strict mode is not usable as-is for these exports |
| sherpa-onnx | non-CPU provider request -> warns and runs on CPU; transcript still succeeds |
| faster-whisper | `device='cuda'` raises at construction (no silent fallback); `device='auto'` resolves to CPU |
| ggml-diag (spike tool) | refuses nonexistent device index (exit 2) |

## 7. Word timing

- Native: faster-whisper DTW (per word), whisper.cpp DTW/`-ml 1` token times, Parakeet token times grouped into words. Whisper ONNX and Moonshine ONNX exports give none.
- Separate aligner (from the older Hushpatch project's design): wav2vec2-base-960h ONNX CTC forced alignment on CPU against known text, with a mean-log-probability per-word score (fits D67). Implemented independently in `runners/wav2vec2-aligner`; aligns all 14 oracle clips with no missing words; true words scored about -0.1 versus about -14 for appended hallucinated words on one clean clip (uncalibrated).
- **Timing accuracy is not established.** The SAPI SpeakProgress start times in `ground_truth.json` are not defensible as independent acoustic boundaries: on `clean_001` the audio's silent gaps (about 0.90 s and 1.04 s) conflict with SAPI's 0.854/1.377 s starts, and aligner-minus-SAPI differences grow with word position (aligner comparison only; reviewer 2 supports the concern but did not re-verify the aggregate numbers). Therefore the reported timing errors (Parakeet about 273 ms start, aligner 256/482 ms, native DTW) are disagreement with approximate SAPI annotations, not validated boundary accuracy, and no timing ranking is claimed. WER, target recall/precision and hallucination figures use transcripts only and are unaffected.

## 8. Footprint

| Item | Bytes |
|---|---|
| whisper.cpp CPU all-variants build (exe+dll) | 11,703,296 |
| whisper.cpp Vulkan + CPU build | 54,137,344 (incl. 316,416 B build-only shader generator; `ggml-vulkan.dll` 42,117,632) |
| whisper.cpp runtime deps | MSVC runtime, OpenMP `vcomp140.dll`, driver `vulkan-1.dll`; no vendor SDK |
| ORT env sizes (post-install, incl. venv) | DirectML 170,074,007; Windows ML 142,340,453; CPU 121,507,852 |
| faster-whisper env | 267,087,721 (+ 486,098,798 model) |
| Earlier CI-measured installs | faster-whisper 262.85 MB, WinML 113.33 MB, Moonshine 82.71 MB, sherpa-onnx 52.94 MB |

## 9. Errors, warnings, unresolved blockers

- `onnxruntime-windowsml` prints "Init provider bridge failed" on import (the older project silenced it with a stderr redirect during import); DirectML still executes inside that wheel. The historical override remains a dependency-consistency failure (`uv pip check`); faster-whisper pulls `onnxruntime`, which conflicts on module name with the Windows ML wheel.
- whisper.cpp DTW requires flash attention off (`-nfa`), else it warns and returns no word times.
- Moonshine DirectML corruption: observed; cause unproven (quantized `DynamicQuantizeLinear`/`MatMulIntegerToFloat` nodes ran on DML; no operator isolation done).
- WP13's first report claimed a valid DirectML session failed; the later correction says the failure was the invalid-device retry path and a valid `device_id=0` session works (ORT 1.24.4, 1.30.1 and 1.32.0 all create sessions). Treat the first report as superseded.
- Untested: Windows ML catalog AMD provider, HIP/ROCm, NVIDIA and Intel hardware, iGPU, real game audio, long clips, whisper.cpp VAD.
- The older project reported DirectML crashing when two sessions share a process, MIGraphX segfaulting on the second inference, and `add_provider_for_devices` running 4.5x slower; these were not independently tested here.

## 10. Model-artifact manifest (downloaded and verified; nothing further requested)

All verified against pinned revision metadata (LFS SHA-256 where available; small-file hashes observed on download are trust-on-first-use).

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

## 11. Benchmark status

Defined in `spike/asr50/benchmark/README.md`; scorer includes a matched-word-pair helper for timing. Lexical metrics (WER, target recall/precision, silence hallucination) are valid for this synthetic set. Timing metrics need a better ground truth: reviewer 2 proposes synthesizing each word separately, keeping each WAV's exact sample count, concatenating with explicit silence gaps, and verifying boundaries acoustically. Not done.

## 12. Recommended next experiments

1. Build the constructed-boundary corpus v2 and re-score native DTW (faster-whisper, whisper.cpp), Parakeet token times and the wav2vec2 aligner on it.
2. Extend the corpus (more clips, a second voice, longer clips, real-ish dialogue without game assets) before using differences of a few words to choose.
3. Whisper-based GPU candidates to carry forward for AMD evidence: whisper.cpp Vulkan and ORT DirectML (fp16 Small.en proven; q4 Turbo proven). Parakeet and faster-whisper are CPU-only on this hardware.
4. Test explicit-device enforcement in a thin wrapper (verify actual provider/backend, refuse silent fallback) for both whisper.cpp and ORT.
5. Isolate the Moonshine DirectML corruption (operator-level tensor comparison) only if Moonshine stays a candidate.
6. Optional with approval: Windows ML catalog AMD provider; HIP SDK for whisper.cpp HIP / CT2 ROCm; NVIDIA and Intel runs on those machines.

## 13. Decisions requiring maintainer approval

1. Whether to spend more budget at all (the eight-hour cap appears reached) and, if so, on which of the next experiments.
2. Approval for system-level steps, if wanted: HIP SDK install; Windows ML catalog acquisition.
3. Whether to keep the temporary workflows on PR #56 (the maintainer chose "keep until selection").
4. Direction for any future per-hardware model strategy (CPU, NVIDIA, AMD, Intel); this report supplies evidence only. Whether separate aligner-based word timing is acceptable under the SpeechAnalysisResult contract is an architecture question for the maintainer.
5. Runtime/model selection (D47) remains with the maintainer.
