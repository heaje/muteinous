# Issue #50 — independent read-only review #2

Scope: reviewed WP8–WP14, scorer contract and raw per-clip JSON. No repository, result, or delegate-report files were changed. The rescore implementation is `reviewer2/rescore.py`; it imports repository `score.py` and aggregates canonical runner outputs for all 14 clips (58 reference words), excluding WP14-derived copies and duplicate warm runs. Values use S/D/I, target precision/recall, silence/non-speech words per minute, and fraction of the two silence/non-speech clips emitting words.

## Central rescore

| Runner | Config/device | WER (S/D/I) | Target P/R | silence+non-speech wpm | clips output |
|---|---|---:|---:|---:|---:|
| sherpa-parakeet | cpu | .1207 (6/1/0) | .9667/.8286 | 0 | 0/2 |
| faster-whisper | cpu (default) | .1379 (6/0/2) | .9677/.8571 | 0 | 0/2 |
| faster-whisper | int8_float32 beam1 no VAD | .2241 (7/0/6) | 1.0000/.8286 | 60 | 2/2 |
| faster-whisper | int8_float32 beam5 no VAD | .2241 (6/0/7) | .9677/.8571 | 75 | 2/2 |
| faster-whisper | int8_float32 beam5 VAD | .1379 (6/0/2) | .9677/.8571 | 0 | 0/2 |
| moonshine-onnx | CPU t4/t12/t24/warm1-3 (same transcript) | .2241 (8/1/4) | .9655/.8000 | 0 | 0/2 |
| moonshine-onnx | DML | 2.1379 (57/0/67) | 0/0 | 0 | 0/2 |
| ort-whisper-turbo | CPU | .1552 (7/0/2) | .9375/.8571 | 30 | 2/2 |
| ort-whisper-turbo | DML | .1552 (7/0/2) | .9375/.8571 | 30 | 2/2 |
| ort-whisper-small-en | CPU | .1897 (7/0/4) | 1.0000/.8286 | 30 | 2/2 |
| ort-whisper-small-en | DML | .1724 (6/0/4) | .9677/.8571 | 30 | 2/2 |

| whisper.cpp model | build/device | WER (S/D/I) | Target P/R | silence+non-speech wpm | clips output |
|---|---|---:|---:|---:|---:|
| turbo | Vulkan GPU | .2069 (8/1/3) | .9655/.8000 | 45 | 2/2 |
| turbo | Vulkan CPU | .2414 (8/1/5) | .9655/.8000 | 45 | 2/2 |
| turbo | CPU-DL | .2414 (8/1/5) | .9655/.8000 | 45 | 2/2 |
| small.en | Vulkan GPU | .1897 (7/0/4) | .9667/.8286 | 30 | 1/2 |
| small.en | Vulkan CPU | .1897 (7/0/4) | .9667/.8286 | 30 | 1/2 |
| small.en | CPU-DL | .1897 (7/0/4) | .9667/.8286 | 30 | 1/2 |

These are central rescoring values from functional full-mode JSON. WP8's one-decimal-percent claims match. Silence text: turbo “Thank you” / “Bang”; small.en `[BLANK_AUDIO]` / “gun shots”. `[BLANK_AUDIO]` is a Whisper control marker, not lexical words; it is represented as no transcript in the normalized JSON, so no special-case exclusion changes the raw rescore. `-ml 1` and DTW are distinct modes; do not mix with full-mode accuracy.

**Discrepancy:** WP13’s faster-whisper “existing CPU baseline” .2759 matches none of the current WP10 raw configurations. Raw rescore: .2241 beam5/no-VAD; .1379 beam5/VAD and the separate `cpu` directory. Remove .2759 or label it as a distinct historical configuration with its source. WP12 .1552 both devices is correct; WP11 .2241 CPU / 2.1379 DML is correct; WP9 .1207 is correct. WP8 rounded accuracy matches subject to normalization.

All scored canonical directories have JSON for each of the expected 14 IDs; GT declares 14 clips, 12 speech-bearing and 2 silence/non-speech. Reported model paths tie to approved `C:\scratch\asr50\models` artifacts / WP7 verification; no report evidence of unapproved weights, though this was not an exhaustive filesystem hash audit. WP8 used system Python 3.12 for its driver; disclose as a reproducibility deviation, not evidence the runtime changed.

## Timing ground truth

The challenge to SAPI timestamps is credible and supported independently of forced alignment by the described speech-only waveform RMS gaps near 0.90/1.04 s versus SAPI’s 0.854/1.377 s boundaries for clean_001. The corpus generator itself labels its RMS check “coarse envelope sanity check, not an alignment oracle.” The progressively growing reported lag is inconsistent with a mere fixed offset. However, the stated 98%/58 and word-position lag numbers are aligner comparisons, not independent validation; I did not run fresh SAPI or RMS segmentation over all speech WAVs, so those aggregate numbers remain unverified here.

Conclusion: ground_truth.json SAPI times are not defensible as independently established acoustic word boundaries. Retain transcripts as lexical ground truth; relabel timing as approximate SpeakProgress annotations. A stronger future oracle is separately synthesizing each word, retaining each WAV’s exact sample count, then concatenating with explicit silence gaps and verifying boundaries acoustically. Do not regenerate this corpus now.

Parakeet 273 ms start error, WP14 256/482 ms, faster-whisper DTW, and whisper.cpp DTW are errors *against SAPI annotations*, not validated timing accuracy. Withdraw timing-accuracy/ranking claims or label as annotation disagreement with uncertainty; do not call WP14’s reference an “oracle.” End errors are especially weak because SAPI ends are approximate/inferred.

## Claim spot-checks

- **WP13 correction:** its narrative says an earlier invalid-device fallback/optimizer error, later valid device_id=0 success. Clarify the first issue was invalid device 999, explicit CPU retry and optimizer error—not failure of valid 0. The .2759 comparator remains unsupported.
- **WP8 fallback:** report gives exit-0 CPU allocation/“no GPU found” for `-dev 1`, `-dev 7`, and visibility index 5; index 1 is CPU. Supported by reported logs; exit status/transcription do not establish GPU computation.
- **WP11 DML garbage:** plausible quantized-kernel/provider interaction, but unproven. Logs establish DML work on DynamicQuantizeLinear/MatMulIntegerToFloat and mixed CPU assignment; no tensor comparison/operator isolation establishes causality. Describe corruption as observed and cause as unknown.
- **WP9 fallback:** explicit warnings for directml/cuda/dml and CPU fallback support the report; no GPU inference claim follows.
- **WP8 Python 3.12:** disclose driver environment deviation.

## Severity-ranked actionable errors

1. **Critical — timing accuracy overstated:** recast all absolute timing errors as disagreement with approximate SAPI annotations; no validated boundary ranking.
2. **High — WP13 wrong faster-whisper comparator:** replace .2759 with current configuration-specific .2241 no-VAD/.1379 VAD or identify historical source.
3. **Moderate — normalization ambiguity:** consistently strip non-lexical whisper.cpp control tokens before lexical scoring and document per-run silence outputs.
4. **Moderate — unsupported WP11 causal diagnosis:** do not attribute DML corruption to quantized ops without causal evidence.
5. **Low — reproducibility:** mention WP8 driver Python 3.12.

## Verified OK

- 14 clips and 58 reference words; expected clip IDs present in canonical runner output sets.
- Central scorer reproduces WP9, WP10 config-specific, WP11, WP12 and WP13 raw scores above; WP12 CPU/DML agree.
- WP9/WP11 provider-fallback warnings are explicit; WP8 invalid device selections do not prove GPU.
- No report evidence of unapproved model paths; reported artifacts refer to approved local paths/manifest records.
- Lexical findings remain useful for this synthetic set, not spontaneous game dialogue.

**Final report caveats:** timing is not ground-truth validated; .2759 baseline is unsupported/currently mismatched; name exact faster-whisper configurations; normalize controls consistently; mixed-provider execution is not all-GPU; WP11 DML corruption cause is unknown; synthetic 14-clip results do not establish real game-audio performance.

### Summary (<350 words)

Central rescore confirms WP9 .1207; WP10 .2241 no-VAD and .1379 VAD; WP11 .2241 CPU / 2.1379 DML; WP12 .1552 both devices; WP13 .1897 CPU / .1724 DML. WP13’s .2759 faster-whisper comparison does not match current WP10 raw configurations. WP8 full-mode rounded claims match; whisper.cpp silence/non-speech output includes “Thank you”/“Bang” (turbo) and `[BLANK_AUDIO]`/“gun shots” (small.en), requiring consistent control-token treatment. SAPI SpeakProgress timing is approximate, not validated acoustic ground truth; Parakeet, WP14, faster-whisper DTW and whisper.cpp DTW numbers should be described only as disagreement with SAPI labels. The described silence-gap evidence supports the concern, but I did not independently re-run SAPI/RMS analysis over all speech WAVs; the supervisor’s aggregate lag figures remain unverified in this review. DML corruption cause is unknown. The scorer implementation and TSV are under `C:\scratch\asr50\reviewer2\`; no repo/results/delegate reports were modified.
