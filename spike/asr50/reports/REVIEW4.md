# Independent central rescore — VAD-masked v2 and corpus v3

Recomputed directly from each per-clip `text` JSON and frozen ground-truth transcript using the unmodified `spike/asr50/benchmark/score.py` (`tokenize`, `edit_counts`, `target_metrics`). No delegate aggregate score files were used to calculate these results. Driver and full-precision results are in [`reviewer4/rescore.py`](../reviewer4/rescore.py) and [`reviewer4/scores.json`](../reviewer4/scores.json).

## Method and coverage

WER counts are summed per transcript-bearing clip; v2 has 40 speech clips / 1,208 reference tokens and 20 negative clips, v3 has 340 speech clips / 2,807 tokens and 40 negative clips. Target metrics call `score.target_metrics` per clip, then sum TP/FP/FN; hallucination WPM uses the total negative-clip duration and normalized tokens. Gated-skip replaces text with empty text on manifest-flagged clips. The v2 manifest keys by `clip_id`; v3 keys by input WAV basename. A gate flag is not inferred from output JSON.

Included all 11 complete v2 masked-run configurations. V3 includes all complete CPU/raw/masked, CPU/DML raw/masked, and Whisper.cpp configs with 380 clips. Whisper.cpp `turbo-vulkan-full` is complete; `turbo-cpu-full` had 174/380 clips when rescored and is incomplete. No other Whisper.cpp v3 config has a full 380-clip set. The scorer driver does not wait for these runs. V3 per-condition scores for every complete configuration are in `scores.json`.

## VAD-masked v2: centralized scores

`P/R` is target precision/recall. `WPM/output` is hallucinated words/minute and negative clips with nonempty normalized text.

| Runner / config | View | WER (S/D/I) | P / R | WPM / output |
|---|---|---:|---:|---:|
| whisper.cpp small.en CPU | masked / gated | 1.90% (15/6/2) | 97.98 / 83.62% | 0.22 / 1 of 20 |
| whisper.cpp small.en Vulkan | masked / gated | 2.24% (19/6/2) | 97.96 / 82.76% | 0.22 / 1 |
| whisper.cpp turbo CPU | masked | 3.15% (21/1/16) | 100 / 81.90% | 8.73 / 20 |
| whisper.cpp turbo CPU | gated | 3.15% (19/3/16) | 100 / 81.90% | 0.22 / 1 |
| whisper.cpp turbo Vulkan | masked | 3.06% (20/1/16) | 100 / 82.76% | 8.73 / 20 |
| whisper.cpp turbo Vulkan | gated | 3.06% (18/3/16) | 100 / 82.76% | 0.22 / 1 |
| Parakeet CPU | masked / gated | 1.82% (15/7/0) | 97.96 / 82.76% | 0 / 0 |
| faster-whisper beam5 VAD-off | masked | 2.24% (17/5/5) | 97.00 / 83.62% | 4.25 / 19 |
| faster-whisper beam5 VAD-off | gated | 2.24% (16/6/5) | 97.00 / 83.62% | 0 / 0 |
| Moonshine CPU | masked / gated | 6.54% (39/19/21) | 96.63 / 74.14% | 0 / 0 |
| Turbo ONNX CPU or DML | masked | 5.05% (19/39/3) | 100 / 82.76% | 4.48 / 20 |
| Turbo ONNX CPU or DML | gated | 5.05% (18/40/3) | 100 / 82.76% | 0.22 / 1 |
| Small.en ONNX CPU or DML | masked | 12.09% (34/105/7) | 97.98 / 83.62% | 4.48 / 20 |
| Small.en ONNX CPU or DML | gated | 12.09% (33/106/7) | 97.98 / 83.62% | 0.22 / 1 |

There is an intentional difference between masked-run and gated view on the single VAD-passed non-speech clip: only the v2 false negative `timing_noise_pink_-5_01` is speech-flagged; the non-speech false negative `nonspeech_pink_noise_30s` remains decoded and hallucinates for some runners. Gating also changes the S/D/I alignment on the one speech false positive without changing total edit distance.

## Corpus v3 overall

| Runner/configuration | View | WER (S/D/I) | P / R | Hallucination WPM; output clips |
|---|---|---:|---:|---:|
| faster-whisper beam5 VAD-off | raw | 7.30% (165/25/15) | 90.00 / 95.45% | 5.16; 33/40 |
| faster-whisper beam5 VAD-off | masked / gated | 7.59% (171/27/15) | 90.00 / 95.45% | 5.16 / 40; gated 0 / 0 |
| faster-whisper beam5 VAD-on | raw | 7.30% (165/25/15) | 90.00 / 95.45% | 0 / 0 |
| Parakeet CPU | raw | 6.16% (130/34/9) | 90.32 / 84.85% | 0 / 0 |
| Parakeet CPU | masked / gated | 6.31% (131/37/9) | 90.32 / 84.85% | 0 / 0 |
| Moonshine CPU | raw | 12.40% (239/78/31) | 87.69 / 86.36% | 0 / 0 |
| Moonshine CPU | masked / gated | 13.43% (245/86/46) | 87.88 / 87.88% | 0 / 0 |
| Turbo ONNX CPU/DML | raw | 6.31% (136/27/14) | 91.43 / 96.97% | 2.97; 19/40 |
| Turbo ONNX CPU/DML | masked / gated | 6.34% (138/27/13) | 91.43 / 96.97% | 5.16 / 40; gated 0 / 0 |
| Small.en ONNX CPU/DML | raw | 7.77% (171/31/16) | 91.43 / 96.97% | 4.26; 33/40 |
| Small.en ONNX CPU/DML | masked / gated | 7.87% (174/32/15) | 91.43 / 96.97% | 5.16 / 40; gated 0 / 0 |
| whisper.cpp turbo Vulkan full | raw | 6.38% (132/41/6) | 91.30 / 95.45% | 4.77; 18/40 |

CPU/DML text matches: Turbo ONNX 380/380 on raw and masked; small.en ONNX 380/380 raw, 379/380 masked (the changed speech text is `v3_condition_034`, a brake/break spelling difference). The same masked file appears twice in small.en's output tree (ordinary and gated-skip); comparisons should use the ordinary CPU/DML pair, not count duplicate paths as independent clips.

## Condition-level changes and paired clip analysis

Only these three CPU model pairs show the noted slight aggregate WER increases under masked input with no speech clip flagged. Aggregate change is modest, but each paired comparison reveals more clips got worse than improved. This is a fixed test set comparison, not repeated sampling; “chance” is not established by aggregate WER alone.

| Model | Raw -> masked error counts | Changed-error clips (worse / better / net) | Changed transcript clips | Condition contributions (raw -> masked WER) |
|---|---:|---:|---:|---|
| Parakeet | 173 -> 177 (+4; +0.143 pp) | 5 / 3 / +2 | 11 | clean 5.40 -> 5.40%; pink 15 dB 0 -> 4.00%; pink 0 dB 15.38 -> 19.23%; reverb 20 -> 28%; white 0 dB 4.76 -> 14.29%; radio 12.20 -> 9.76%; white 5 dB 13.04 -> 8.70%; babble/music/effects/pink 5 dB unchanged |
| Moonshine | 348 -> 377 (+29; +1.033 pp) | 10 / 3 / +7 | 19 | clean 10.07 -> 10.19%; music loop 0 -> 68.18% (+15 errors, one clip repetition); pink 0 dB 30.77 -> 61.54%; reverb 40 -> 44%; game effects 54.55 -> 54.55%; remaining condition values in JSON |
| Small.en ONNX CPU | 218 -> 221 (+3; +0.107 pp) | 2 / 0 / +2 | 8 | clean 6.53 -> 6.53%; pink 0 dB 15.38 -> 19.23%; reverb 20 -> 28%; other condition rates mostly unchanged |

The biggest degradation clips were Parakeet `v3_condition_007` (white noise 0 dB, 0 to 2 errors), `v3_condition_033` (reverb, 3 to 5), and `v3_clean_017_1` (0 to 1); Moonshine `v3_condition_027` (music-loop repeated output, 0 to 14), `v3_condition_018` (pink 0 dB, 0 to 8 after empty masked transcript), and `v3_clean_033_0` (0 to 3); Small.en `v3_condition_033` (reverb, 4 to 6) and `v3_condition_017` (pink 0 dB, 4 to 5). Paired errors went down on 3 Parakeet clips and 3 Moonshine clips; no Small.en clip improved. All paired details are reproducible from the stored per-clip score breakdowns.

## Delegate-report audit

Scoring cross-check against the requested WP8–WP13 sections:

* **Confirmed:** WP8's masked v2 S/D/I, WER and hallucination rates, including turbo-vulkan and Small.en-vulkan; WP9's masked v2 WER/edits and zero negative output; WP10's masked v2 WER/edits and hallucinations; WP11's masked v2 WER/edits/target P-R; WP12's masked v2 speech and hallucination metrics; WP13's masked v2 WER/edits and hallucination metrics. Small variation in prose rounding is below 0.1 pp.
* **V2 target-metric discrepancies:** WP8 reports turbo Vulkan masked P/R 100/82.8%, while centralized is 100/82.76% (rounding); its small.en Vulkan masked P/R 98.0/82.8%, centralized is 97.96/82.76% (rounding). WP9 masked v2 97.96/82.76% confirms. WP10 masked v2 reports recall/precision 82.8/96.0%, whereas central scorer is recall/precision 83.62/97.00%; this is material and likely comes from a different target occurrence aggregation or source output set. WP13 masked small.en ONNX P/R is 0.8362/0.9798, confirmed to displayed precision. WP11 matches 0.741/0.966 after ordinary rounding.
* **V3 discrepancies:** WP8–WP13 prose values are largely supported for the runners where their per-clip results exist, but one material issue surfaced: WP10 v3 reports target P/R 98.5/92.9%; central `score.target_metrics` per clip gives 90.00/95.45% (63 TP, 7 FP, 3 FN) for faster-whisper. WP11 target values differ slightly: reported 90.32/84.85%, while central masked gives 87.88/87.88% (58/8/8), raw 87.69/86.36% (57/8/9). The specific cause is likely delegate target aggregation or a different target matching convention; audit per-clip underlying text before treating those precision/recall figures as equivalent. WP13's small.en v3 headline reports 0.0805 raw / 0.0816 masked (179/31/16, 182/32/15); central rescoring of files on disk gives 0.0777 / 0.0787 (171/31/16, 174/32/15), exactly eight fewer substitutions in both views. The same eight-token offset suggests a different scored clip/transcript set or a prior version of outputs; it is not a rounding difference. Its per-condition table also has values differing from this file-level rescore, so inspect which file snapshot produced its summary.
* WP13's **0.2759** baseline is a distinct earlier 14-clip corpus/configuration (faster-whisper CPU Small.en), not a competing v3 score; it is not comparable to v3's 7.77% from ONNX small.en or 7.30% faster-whisper beam5. No central-rescore mismatch should be inferred across those different systems/datasets.
* “Any count mismatch” applies to the disagreements above: target TP/FP/FN are explicitly enumerated in `scores.json`. The known reports that use ordered target alignment differ from simple independent occurrence counts in some duplicated-target cases. No delegate v3 output set has been overwritten.

### Turbo ONNX: digital silence and masked hallucination

From the actual q4 Turbo per-clip JSON, masked inference emitted a normalized token on all 40 negative clips (40 words total; five 1.0-second clips plus other durations yield 5.16 WPM). The eight `v3_nonspeech_silence_dither_*` files all say **“you”** on masked silence/dither; raw text was punctuation-only `.` on six, **“you”** on the 10-second clip, and **“Thank you.”** on the 30-second clip. Thus raw has two token-bearing silence/dither outputs in that subset, while masking changes all eight to a hallucinated “you”. This is consistent with the aggregate non-speech increase from 19/40 raw (23 words) to 40/40 masked (40 words), not a claim that every raw file is empty.

## Summary (<250 words)

Independent scoring confirms the major masked-v2 speech WER/edit and negative hallucination results in WP8–WP13. Material exceptions: WP10 masked-v2 target P/R and WP10/WP11 v3 target values do not match canonical per-clip `target_metrics`; WP13's v3 small.en headline is eight substitutions higher in each view than scoring the files now present. WP13's .2759 figure is a separate 14-clip faster-whisper baseline, not v3.

All three queried v3 mask regressions are measurable despite the manifest correctly flagging no speech: Parakeet +4 errors (+0.14 pp; 5 clips worse/3 better), Moonshine +29 (+1.03 pp; 10 worse/3 better, driven heavily by one 14-error repeated music-loop output), and Small.en ONNX CPU +3 (+0.11 pp; 2 worse/0 better). These paired finite-corpus changes do not establish statistical chance or generalization. The Turbo q4 masked output says “you” on all eight silence/dither samples; raw yielded “you” on one and “Thank you” on one, with punctuation-only text on the other six.

One incomplete Whisper.cpp v3 config was observed: turbo CPU full 174/380 (count can continue changing while the experiment runs). Included turbo Vulkan full at 380/380. All condition scores and clip-level deltas are in the rerunnable JSON output; inputs and delegate reports were read-only.
