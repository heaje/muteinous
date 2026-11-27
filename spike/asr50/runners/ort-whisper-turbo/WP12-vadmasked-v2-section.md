## VAD-masked v2

WP18's frozen masked copy (60 clips) was SHA-256 checked against its manifest; source `ground_truth_v2.json` and original `results_v2` outputs were preserved. CPU and DirectML each decoded all 60 masked clips with the same 30-second fixed-window policy. CPU and DML text matched on **60/60**. Output is in `C:\scratch\asr50\results_v2_vadmasked\ort-whisper-turbo\<device>\<clip>.json`, with `gate_no_speech`; `results.jsonl` has 120 observations and `score-summary.json` compares these to the preserved unmasked results and the earlier RMS-gate output.

### Speech lexical results (40 speech clips; 1,208 reference words)

| Input / output policy | WER S/D/I | Target precision | Target recall |
|---|---:|---:|---:|
| Unmasked v2 default | 58/1,208 = 0.0480 (19/37/2) | 1.000 | 0.8448 |
| Unmasked v2 RMS prototype | 58/1,208 = 0.0480 (19/37/2) | 1.000 | 0.8448 |
| VAD-masked, ASR on all | 61/1,208 = 0.0505 (19/39/3) | 1.000 | 0.8276 |
| VAD-masked, skip flagged clips | 61/1,208 = 0.0505 (18/40/3) | 1.000 | 0.8276 |

Target counts: unmasked 98 TP / 0 FP / 18 FN; masked A and B 96 / 0 / 20. Gate manifest flags 20 clips: 19 non-speech/silence and one real-speech false positive, `timing_noise_pink_-5_01`. On that clip the masked default says “you”; B skips it, yielding 3 deletions (WER 1.0 for its reference “banana cobalt harbor”). Its default output was already wrong, so aggregate B WER stays equal to A; the edit mix changes.

### Silence/non-speech hallucinations

| Run | Silence WPM / output clips | Non-speech WPM / output clips | Combined WPM / output clips |
|---|---:|---:|---:|
| Unmasked default | 4.48 / 5 of 5 | 2.69 / 8 of 15 | 3.13 / 13 of 20 |
| Unmasked RMS prototype | 0 / 0 of 5 | 2.69 / 8 of 15 | 2.01 / 8 of 20 |
| VAD-masked A, decode all | 4.48 / 5 of 5 | 4.48 / 15 of 15 | 4.48 / 20 of 20 |
| VAD-masked B, skip flagged | 0 / 0 of 5 | 0.30 / 1 of 15 | 0.22 / 1 of 20 |

Digital silence did **not** prevent Whisper hallucinations: all five pure-silence clips still produced text (“you”), and every non-speech clip emitted text after masking; the VAD-pass `nonspeech_pink_noise_30s` remained audible and produced “BOOM”. Skipping the 20 flagged clips reduces hallucinations to the one non-speech VAD-pass clip, matching the RMS prototype's overall result. CPU and DML metrics are identical.

### Summary (<250 words)

Masked-v2 inference completed on CPU and DirectML for all 60 clips; provider outputs agree exactly. Whisper still emits text on digital silence: all five pure-silence clips say “you”. All 15 non-speech clips also produce text in the masked run; the VAD-pass 30-second pink-noise clip produces “BOOM”. Masked speech WER is 5.05%, target precision/recall 100%/82.76%, versus unmasked 4.80% and 100%/84.48%.

Manifest-driven skip improves combined silence/non-speech output from 20/20 clips (4.48 words/min) to 1/20 (0.22 words/min), matching the prior energy-gate prototype overall. However, it falsely skips real speech in `timing_noise_pink_-5_01`; B yields three deletions for “banana cobalt harbor”. That clip was already misrecognized as “you” in masked A, so total WER happens to remain unchanged. This is a concrete coverage cost, not evidence the gate is safe. No speed or timing measurement was performed.
