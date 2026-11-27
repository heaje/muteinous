# ASR runtimes: silent CPU fallback, DirectML concurrency and non-speech hallucination
Status: active
Last verified: 2026-11-27
Related: [Issue #50](https://github.com/heaje/muteinous/issues/50), draft PR #56, [investigation report](../../spike/asr50/REPORT.md) (on `spike/issue-50-asr-dependency-probe`, not `main`), D47-D49, D31, D66-D71
Retire/promote when: runtime/model selection (D47) is decided and the device guard, speech gate and worker design are implemented or rejected.

## Finding and limitations

Measured on one machine (Ryzen 9 9900X, Radeon RX 7900 XT, Windows 11), English synthetic speech only; not representative of real game audio, NVIDIA, Intel or HIP/ROCm.

- **No tested runtime refuses a bad explicit GPU request by default.** whisper.cpp with a bad `-dev` or `GGML_VK_VISIBLE_DEVICES` exits 0 and transcribes on CPU. ONNX Runtime DirectML with `CPUExecutionProvider` also in the provider list retries on CPU after a bad `device_id`. sherpa-onnx warns and runs on CPU. D48/D49 ("no silent CPU fallback for an explicit GPU request") therefore require the application to verify actual placement itself. ORT `disable_cpu_ep_fallback` fails on every tested Whisper/Moonshine graph, so it is unusable as a strict mode.
- **DirectML: one session per process.** Two sessions run concurrently from two threads in one process crashed with access violation `0xC0000005`. Two to four separate processes worked and matched the CPU transcript. Not tested: low VRAM, per-process VRAM, long runs.
- **Whisper-family models hallucinate on non-speech** ("you", "thank you"). Replacing non-speech with digital silence does not stop it; skipping ASR for clips a speech gate flags does. A Silero VAD gate (threshold 0.5, 100 ms pad, 200 ms min silence) skipped all 40 synthetic non-speech clips and no speech in the v3 corpus, but missed real speech at -5 dB SNR in pink noise and passed a 30 s pink-noise clip in the v2 corpus. Parakeet and Moonshine did not hallucinate on silence.
- **Moonshine base int8 on DirectML produces corrupt text** (first NaN logits at the second, cached decoder step); cause unproven.
- **Speed (quiet machine):** large Whisper on CPU is slow on short utterances (0.5x-1.1x real time with whisper.cpp Turbo); on Vulkan it is about 4x faster than 12 CPU threads. Parakeet int8 on 4 CPU threads handles a 20 s clip in about 0.4 s.
- **Word timing depends on the boundary definition.** The wav2vec2 CTC aligner beat every native timestamp method under both conventions tested, but only on isolated words; fixed calibration offsets did not generalize across voices.
- **ASR models do not make censor/keep decisions.** A separate language model (Hushpatch uses Phi-4-mini int4) must judge ambiguous words; on synthetic ASR output Hushpatch's rules plus that model decided about 89% correctly, and words the ASR misses (5-6%) are never judged. The model needs about 4.5 GB RAM on CPU (0.2 s per decision) or about 3.4 GB GPU memory (no faster here). Its GPU build needs the Windows ML runtime (`onnxruntime-windowsml`) in the environment, otherwise creation fails with "Specified provider is not supported". It ran alongside ASR in separate processes and, once, in one process with DirectML Whisper without crashing.
- **Test-data trap:** libsndfile writes a wall-clock timestamp in the WAV PEAK chunk, making whole-file hashes differ for identical PCM. Windows SAPI SpeakProgress word times lag the audio and are invalid as ground truth.

## Reproduction / evidence

Commands, scripts, per-clip central rescoring (`spike/asr50/analysis/`), per-runner reports (`spike/asr50/reports/WP*.md`, `REVIEW4.md`) and the speed protocol (`WP22.md`) are on the spike branch. Delegate-reported aggregates were wrong in three places before central rescoring; use the central numbers in `REPORT.md`.

## Recommendation

Do not treat these numbers as a model or runtime choice. When implementing GPU ASR: verify placement after session creation (typed error, not log text where avoidable), run each DirectML session in its own process, put a speech gate in front of any Whisper-family model and skip ASR on non-speech, and re-test on real game audio and with a game running before relying on speed figures.
