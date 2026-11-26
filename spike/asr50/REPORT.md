# M2.0 (#50) AMD hardware ASR investigation report

Temporary investigation record. Not an architecture decision, runtime/model selection, or production dependency change. D47 selection remains open. Independent review: delegate reviewer (same model) completed; corrections incorporated below. Date: 2026-11-26.

Evidence levels used throughout: **L1** documented support, **L2** successful build/install, **L3** device enumeration, **L4** actual computation on the device, **L5** actual ASR inference (not performed; no model weights downloaded).

## 1. Repository and hardware state

| Item | Value |
|---|---|
| `main` | `a76f82d03fb021d096607d189c01498e66f433cf` (verified via `git ls-remote`) |
| Spike branch / PR | `spike/issue-50-asr-dependency-probe`, draft PR #56, head at report time = this commit's parent chain from `824671a` |
| whisper.cpp pin | `ggml-org/whisper.cpp@96ec4d9823e9d0211944172da35f9f29134af990` (1.9.6-dev; same as release v1.9.6 top commit) |
| CPU | AMD Ryzen 9 9900X, Zen 5, 12 cores / 24 threads; AVX2, FMA, AVX-512 (F/BW/CD/DQ/IFMA/VBMI/VBMI2/VNNI/VPOPCNTDQ/BITALG); BF16 flag not reported |
| GPU | AMD Radeon RX 7900 XT, **discrete**, Navi 31 / RDNA3 / gfx1100, PCI 1002:744C; 20,420 MB dedicated + 16,201 MB shared (dxdiag); driver 32.0.32029.2010 (Adrenalin 26.20.29.02) |
| iGPU | Ryzen 9 9900X has an RDNA2 iGPU on paper; **not enumerated** by Windows/dxdiag/Vulkan on this machine (BIOS state not established) |
| RAM / OS | 31.6 GiB; Windows 11 Pro build 26300 |
| APIs | D3D12 FL 12_2; Vulkan 1.4.359 (AMD proprietary 26.11.2), cooperative_matrix, fp16/int8, int dot; DirectML.dll present |
| Not installed | HIP SDK/ROCm, CMake, MSVC, Ninja, Vulkan SDK (none installed by this work) |
| Python / uv | CPython 3.14.10 via uv 0.13.9 (system `python` is a Store alias) |

## 2. Engineering time

My wall-clock: 15:33 to about 16:20 MT (~45 min). Delegate effort is self-reported and ran in parallel: WP1 ~9, WP2 ~15, WP3 ~35 (initial + follow-up), WP4 ~20, WP5 ~15, WP6 ~12 min, reviewer unreported (~15 est). Approximate total ≈ 2 h 15 min of this investigation's effort. Hours previously spent on #50 before this task were not provided, so remaining budget against the 8 h cap cannot be computed here.

## 3. Evidence and commands (reproducible)

- CI: run [45908168976](https://github.com/heaje/muteinous/actions/runs/45908168976) (commit `824671a`) builds whisper.cpp at the pin: `cpu-dl` and `vulkan-dl`; earlier run 45902940651 for the dependency probes.
- Local runs used the CI artifacts: `ggml-diag.exe list`, `ggml-diag.exe matmul <idx> <n> <iters>` (source: `spike/asr50/ggml-diag/devices.cpp`), PowerShell `Get-Counter '\GPU Engine(*)\Utilization Percentage'` filtered to the process ID.
- DirectML/ORT: scripts and logs from WP3 (`probe.py`, `sustain.py`, `fallback_probe.py`, `windowsml_fp16.py`) in disposable `uv venv --python 3.14.10` environments with `--only-binary :all:`.
- Benchmark: `spike/asr50/benchmark/` (`README.md`, `generate_corpus.py`, `score.py`, tests: 5 passed). Corpus (14 clips, 35.18 s, 22.05 kHz mono) generated outside git; all 14 ground-truth SHA-256 values recomputed and matched; regeneration was bit-identical.
- Delegate reports (WP1–WP6, REVIEW, WP5 manifest) are copied under `spike/asr50/reports/`.

## 4. Runtime compatibility matrix (this machine: Ryzen 9 9900X + RX 7900 XT, Windows 11)

| Runtime | CPU | AMD GPU path | Evidence on this machine |
|---|---|---|---|
| whisper.cpp (ggml) | CPU all-variants: L2 build, L4 CPU matmul (variant `cascadelake` chosen on Zen 5) | **Vulkan: L4** (below). HIP: L1 only (HIP SDK lists RX 7900 XT; not installed; Windows HIP via ggml CMake needs validation, source has a `hipcc` workaround) | no ASR (L5 not run) |
| ONNX Runtime + DirectML (standalone `onnxruntime-directml` 1.24.4, CPython 3.14) | L2 | **DirectML: L4** (below) | no ASR |
| ONNX Runtime + Windows ML wheel (`onnxruntime-windowsml` 1.30.1) | L2 | wheel's bundled DML: L4; catalog EPs (AMDGPU/MIGraphX/Vitis): **not tested** (needs network/system changes; docs list Python 3.10-3.13 only) | warns "Init provider bridge failed" on import |
| faster-whisper 1.2.1 / CTranslate2 4.9.1 | L1 metadata: cp314 win_amd64 wheel exists; CPU int8/float32 | L1: Windows ROCm build guide maps RX 7900 XT to gfx1100, but it is a **source build** with AMD ROCm SDK wheels, validated on RX 7900 XTX / Python 3.11 / ROCm 7.2.0; no prebuilt CT2 ROCm wheel evidence | not installed or run locally; CI probe (L2) passed on a generic runner |
| sherpa-onnx 2.0.3 + Parakeet TDT 0.6B v2 | L1: cp314 win_amd64 wheel; int8 export exists; CI probe L2 | unverified; DirectML availability in the published wheel not established | Parakeet gives token timings; word times need aggregation |
| Moonshine (`moonshine-voice` 0.1.6) | L1/L2: generic py3 Windows wheel, no cp314 classifier; CI probe L2 | none found | word timestamps documented |

## 5. Verified AMD GPU computation (L4)

All synthetic, no model weights.

- **ggml Vulkan (whisper.cpp backend):** `Vulkan0` = RX 7900 XT (AMD proprietary driver, KHR_coopmat, fp16 true, warp 64). 2048x2048 f32 matmul: max relative error vs double-precision reference 2.2e-6 (n=4096: 4.4e-6), 0.61 ms warm vs 42 ms on the CPU device in the same binary. Sustained 4096 run: process-filtered GPU **compute** engine ~84% in 6 of 7 one-second samples. Reported TFLOPS exceed fp32 peak, so ggml is probably using fp16 matrix cores with fp32 accumulation; do not read it as an fp32 benchmark.
- **ORT DirectML:** fp32/fp16 MatMul chains and Conv matched CPU exactly; profile JSON `args.provider == DmlExecutionProvider`; verbose logs "All nodes placed on [DmlExecutionProvider]". Sustained 22 s run: 3D engine mean/peak 52.7/52.9% (fp16) and 64.4/65.4% (fp32) on the RX 7900 XT LUID; CPU controls showed no GPU engine instance for the PID. Counter samples were several seconds apart (not 1 Hz).
- **Explicit-GPU and fallback behavior:** DirectML invalid `device_id` fails loudly (`887A0002`). A CPU-only op (string `Identity`) silently runs on CPU by default; `session.disable_cpu_ep_fallback=1` makes session creation fail. ggml-diag refuses a nonexistent device index (exit 2). **whisper-cli explicit-GPU failure behavior is untested (needs a model); the application will need its own strict-GPU enforcement for D48.**

## 6. CPU compatibility

CI probes: faster-whisper, sherpa-onnx, Moonshine, WinML standard and whisper.cpp CPU build passed install/import/build (L2) on Windows Server 2025 / CPython 3.14.10 (4 vCPU runner). Locally verified CPU computation (L4-equivalent, CPU device): ORT CPU, ggml CPU. No CPU ASR (L5).

## 7. Footprint

| Item | Bytes |
|---|---|
| whisper.cpp CPU all-variants build (exe+dll) | 11,703,296 |
| whisper.cpp Vulkan + CPU all-variants build | 54,137,344 (includes 316,416 B `vulkan-shaders-gen.exe`, build-only; `ggml-vulkan.dll` alone is 42,117,632) |
| Runtime dependencies | MSVC runtime (`msvcp140`, `vcruntime140`, `vcruntime140_1`), OpenMP `vcomp140.dll`; `vulkan-1.dll` from the GPU driver; no vendor SDK |
| ORT DirectML env (post-install, includes venv scaffolding) | 170,074,007 |
| ORT Windows ML wheel env | 142,340,453 |
| ORT CPU env | 121,507,852 |
| CI-measured dependency installs (earlier run) | faster-whisper 262.85 MB, WinML standard 113.33 MB, Moonshine 82.71 MB, sherpa-onnx 52.94 MB |

Model sizes are in section 9. Footprints for real packaged distributions are unmeasured.

## 8. Errors, warnings, unresolved blockers

- Historical WinML override fails `uv pip check`; standard `onnxruntime-windowsml` passes `uv pip check` but logs `Init provider bridge failed` on import (same warning seen in the override). DML still executes through that wheel (L4).
- Windows ML catalog acquisition (dynamic AMD EP) untested: needs network + Windows App SDK runtime, a system change; docs list CPython 3.10-3.13 only. Its applicability to RX 7900 XT is documented only at provider level ("supported AMD GPUs"), not exact-card.
- HIP/ROCm paths untested: require the system-wide HIP SDK (not authorized). whisper.cpp pinned CMake notes CMake on Windows lacks HIP language support, with a `hipcc` workaround; not categorical impossibility.
- CI hosted runners enumerate CPU only (AMD EPYC); GPU evidence comes only from local runs.
- No iGPU enumerated, so integrated-GPU behavior is untestable here. NVIDIA and Intel paths are untested on this hardware.
- Word timing quality is unproven for every candidate (whisper.cpp `-ml 1`/DTW experimental; Parakeet token-to-word aggregation; Moonshine attention asset).
- SAPI ground-truth word ends are approximate (next word event / utterance end).

## 9. Proposed model-artifact manifest (approval request; nothing downloaded)

Full per-file revisions, filenames, sizes and SHA-256 (LFS `oid`) are in `reports/WP5-manifest.json`; eight entries were spot-checked against live HuggingFace metadata by the reviewer. Non-LFS small files have no SHA-256 and are marked UNVERIFIED until a small-file fetch is approved. Preferred set for comparison (runtime / artifact / revision / bytes / license):

| # | Combo | Repo @ revision | Download bytes | License |
|---|---|---|---:|---|
| 1 | Whisper Large-v3 Turbo q5_0 / whisper.cpp (Vulkan/CPU) | `ggerganov/whisper.cpp@5359861c739e955e79d9a303bcbc70fb988958b1`, `ggml-large-v3-turbo-q5_0.bin` | 574,041,195 | MIT |
| 2 | Whisper Small.en q5_1 / whisper.cpp | same repo/revision, `ggml-small.en-q5_1.bin` | 190,098,681 | MIT |
| 3 | Parakeet TDT 0.6B v2 int8 / sherpa-onnx | `csukuangfj/sherpa-onnx-nemo-parakeet-tdt-0.6b-v2-int8@84b478d541cdbf0c296a7ab5f1e20a6f8f998114` (encoder, decoder, joiner, tokens) | 661,288,526 | CC-BY-4.0 (attribution required) |
| 4 | Moonshine base int8 / ONNX Runtime | `onnx-community/moonshine-base-ONNX@b1e9b6aae3c3c7298f10c3798393fdf38e8fbbad` | 105,876,417 | MIT |
| **Core total** | | | **1,531,304,819 (1.43 GiB)** | |
| Opt. A | Whisper Small.en CT2 / faster-whisper (CPU) | `Systran/faster-whisper-small.en@d1d751a5f8271d482d14ca55d9e2deeebbae577f` | 486,098,798 | MIT |
| Opt. B | Whisper Large-v3 Turbo q4 ONNX / ORT DirectML | `onnx-community/whisper-large-v3-turbo@360ebcde2559d60bb474678be3c1de9ef347d01a` | 1,089,188,291 | not stated in HF metadata (UNVERIFIED) |

Notes: Moonshine's official runtime (`moonshine-voice`) fetches `.ort` components from `https://download.moonshine.ai/model/...` (dated directory such as `medium-streaming-en/quantized_26_08_21`), with no fixed commit or published per-file SHA-256, so D144 provenance would need a Muteinous-owned pinned manifest; the HF ONNX route in row 4 is pinnable. `alignment_heads` is not a separate artifact in these repos. Expected installed size is assumed equal to download size (excludes caches). Issue #50: do not mirror models in GitHub Releases. Each combo downloads only one variant; the full catalog (13.65 GB) is not a request.

## 10. Benchmark plan

Defined in `spike/asr50/benchmark/README.md`: recall/precision/F1 on target words, FP/FN, WER (explicit normalization), word start/end error (mean/median/p95; 50/100/200 ms), missing alignments, silence hallucinations, RTF, cold vs warm in fresh processes, peak RAM/VRAM, footprint; JSONL result schema; equivalent inputs (16 kHz mono float32, same clips and thread counts). Corpus categories: clean, noisy (10/0/-5 dB), music/effects, quiet (-30/-40 dBFS), silence, non-speech, rapid, repeated targets, similar-sounding, boundary words. The current corpus is small (14 clips, 35 s) and synthetic SAPI speech; scale and diversity (second SAPI voice, more targets) should grow before any model choice.

## 11. Recommended next experiments

1. After approval: download the core set (1.43 GiB) plus the small unverified files, verify hashes, and run the equivalent-input benchmark on CPU and on the RX 7900 XT (whisper.cpp Vulkan; ORT DirectML for Opt. B).
2. Test whisper.cpp explicit device behavior (`-dev`, `-ng`, `GGML_VK_VISIBLE_DEVICES`) and word-timing modes (`-ml 1`, DTW) with a model.
3. Parakeet token-to-word aggregation prototype and sherpa-onnx provider check (DirectML availability).
4. Optional, needs approval: HIP SDK install for whisper.cpp HIP and CTranslate2 ROCm source build; Windows ML catalog test for the AMD GPU EP.
5. NVIDIA and Intel coverage on those machines (whisper.cpp CUDA/Vulkan, SYCL/OpenVINO; ORT DirectML on Intel).
6. Grow the corpus and add a native Linux/macOS CPU check if those platforms stay in scope.

## 12. Decisions requiring maintainer approval

1. Approve (or amend) the model downloads in section 9, including fetching the small unverified config/tokenizer files to compute SHA-256.
2. Approve installing the AMD HIP SDK on this machine (system-wide), or decline HIP/ROCm testing.
3. Approve Windows ML catalog acquisition testing (network + shared package install), or decline.
4. Decide whether to keep the temporary workflows on PR #56 or remove them after this phase; PR #56 stays draft and unmerged.
5. Confirm remaining time budget and whether to continue past the point where selection stays with the maintainer (D47).
6. Per-hardware model strategy (different models for CPU, NVIDIA, AMD, Intel) is a future architectural decision; this report only supplies evidence.
