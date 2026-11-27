# Proposed decision-log amendments for issue #50 (DRAFT, not approved)

Status: **proposal for maintainer review.** Nothing here is a decision. The decision log (`docs/architecture/decisions.md`) is unchanged; if approved, these would be recorded there through a reviewed PR, with the decision-coverage tracker updated. Evidence references are to [REPORT.md](REPORT.md) on branch `spike/issue-50-asr-dependency-probe`. Wording follows the "Approved M2 planning decisions" format.

## Proposed amendment A: Speech-recognition engine selection

**Status: Proposed.** Refines D47, D48, D50, D51; D46 and D144/D145 rules unchanged. The D47 open item stays open until the maintainer approves.

- **Selection (proposed):**
  - Device resolved to a suitable GPU (D48): whisper.cpp with Whisper Large-v3 Turbo q5_0 on Vulkan (multilingual model; evidence: REPORT 5.3, 5.5, 9.1).
  - Device resolved to CPU: Parakeet TDT 0.6B v2 int8 through sherpa-onnx (English only; REPORT 5.3, 5.5, 9.1).
  - The application resolves the engine from the resolved device (D48) and effective language (D51). Users still do not select models (D47); explicit CPU or GPU selection remains a hardware choice.
- **Cache validity (refines D46, D50):** the analysis signature records the engine, model and revision, and precision. D50's reuse across CPU and GPU applies when the same engine and model run on both. Where the resolved device changes the engine, the signature differs and cached analysis for the new engine is needed. Whisper.cpp's own Vulkan and CPU transcripts differed on 3-10% of clips, which D50 already allows (no bit-for-bit requirement).
- **Output limits (required):** the recognition stage bounds runaway or repeated output (token cap proportional to clip length, stop on a repeated short pattern, no carry-over between clips, as Hushpatch does). Whisper-family engines produce text on silence and vocal efforts, but on a real-audio sample a word-list word appeared in at most 1 of 60 vocal-effort clips per engine. Equivalent limits must be shown for the chosen whisper.cpp engine (not tested here).
- **Speech-presence gate (optional, swappable stage; default undecided):** a separate stage with a speech detector and a no-op implementation behind one interface; one skip-or-process decision per clip, no audio cutting. Controlled by an advanced user setting; the gate and its settings, including "none", are part of the cache signature (D46). On real audio the tested detector skipped 3 of 300 speech lines (each with a word-list word) and passed about half of the vocal-effort clips, so it is not shown necessary for listed-word recall; it may save scan time (not measured). A detector model needs its own pinned entry and download approval (D144/D145) only if the gate is enabled.
- **Device placement:** every runtime needs a guard that proves actual placement and raises a typed error for an explicit-GPU request that cannot be honored (D49). No tested runtime refuses by default (REPORT 6).
- **DirectML:** if DirectML is ever used, one session per process (REPORT 6.1).
- **Not established:** non-English accuracy of any model; behavior on other games, ambient or processed audio; a multilingual CPU-only engine.
- **Open question for the maintainer:** a CPU-only user who needs a language Parakeet v2 does not support has no fast option (Turbo on CPU is about 6x real time on long audio at 12 threads, 0.5-1.1x on short utterances). Options: accept slower scans, add a multilingual CPU engine later (a multilingual Parakeet release was not tested), or require a GPU for non-English.

## Proposed amendment B: Supporting models and replaceability

**Status: Proposed.** Refines D03, D46, D47, D67, D144, D145; reaffirms D03's rule that abstractions need a real consumer and justified variation.

- **Scope:** extend D47/D144/D145 from the speech-recognition model to the supporting models the application chooses and manages: the word-alignment model (wav2vec2-base-960h is English-only; REPORT 7), the speech-presence gate model, and the context judge (Phi-4-mini-instruct int4, MIT). No user model selection and no model-management UI.
- **Replaceability requirement (maintainer, 2026-11-27):** a model, runtime, or stage implementation must be replaceable without changes outside its own seam.
- **Seams:** four narrow internal interfaces, one per stage (recognize speech, align words, gate speech, judge ambiguous words), with built-in registration only (D03). Add a capability flag only where engines demonstrably differ: native word times or none, maximum clip length, supported devices; a stage that may be off (the gate) gets a no-op implementation.
- **Manifest as data (refines D144):** each supported model's pinned revision, SHA-256 per file, license, and per-model settings (chunk limit; for the context judge, prompt template, answer rule and decision threshold; device builds) live beside it. Prompt and threshold are tied to the model, so replacing the judge replaces them.
- **Cache signatures:** the aligner's identity and version enter the speech-analysis signature, because it determines word timings (D46). The context judge's model and prompt version belong to the effective-edit-outcome fingerprint (D19, D44), not the speech-analysis signature, since decisions are recomputed without repeating ASR (D45).
- **Admission procedure:** a replacement model is admitted only after the repository's qualification suite: the synthetic corpora and central per-clip scorer, listed-word recall on real audio (kept local, not committed), silence and vocal-effort hallucination, device-placement verification and CPU/GPU agreement, memory, and speed.
- **Context judge on CPU by default:** run it on the CPU build everywhere unless a measured need says otherwise (REPORT 5.4: not faster on GPU, about 3.4 GB GPU memory versus 4.5 GB RAM), which also gives the same decisions on every machine (application path identical on 165 of 165 cases).
- **Not established:** a multilingual aligner or context judge (a text-only 60-sentence check scored 90%, unverified labels); the judge's labelled accuracy on real lines.

## Consequences if both are approved

- Scans record engine, model, aligner and (for decisions) judge and prompt versions; changing any invalidates only what depends on it.
- A new model means a new manifest entry and, if its runtime is new, a new adapter and device guard, then the qualification suite.
- Model updates keep D145's explicit approval for download and activation.
