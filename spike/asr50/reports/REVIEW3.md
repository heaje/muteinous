# Independent read-only review #3 — issue #50 corpus v2

Reviewed 2026-11-26. Scope: frozen v2 corpus, raw per-clip result trees, WP8–WP15 corpus-v2 sections, repository `score.py`/README, and WP11 operator diagnostic. Rescore code/output are in `C:\scratch\asr50\reviewer3\rescore.py` and `computed.txt`. No corpus, result, delegated report, or repository files were changed; no downloads or installs.

## Central lexical rescore

Imported repository scorer functions (`tokenize`, `edit_counts`, `target_metrics`) and aggregated all expected 60 clip JSONs per configuration. WER is on 40 transcript-bearing clips (1,208 words); target P/R on all clips; hallucinations on all 20 silence/non-speech clips. P/R are shown P/R.

| Runner | Config/device | WER S/D/I | Target P/R | hallucinated words/min | clips output |
|---|---|---:|---:|---:|---:|
| whisper.cpp | turbo Vulkan | .02235 (18/0/9) | 1.0000/.8534 | 6.269 | 16/20 |
| whisper.cpp | turbo CPU | .02483 (21/0/9) | 1.0000/.8276 | 5.821 | 16/20 |
| whisper.cpp | small.en Vulkan | .02070 (16/6/3) | .9798/.8362 | 16.567 | 10/20 |
| whisper.cpp | small.en CPU | .02235 (17/5/5) | .9796/.8276 | 37.612 | 10/20 |
| Parakeet | CPU | .01573 (16/3/0) | .9802/.8534 | 0 | 0/20 |
| faster-whisper | beam1 no VAD | .03063 (26/1/10) | .9691/.8103 | 6.045 | 13/20 |
| faster-whisper | beam5 no VAD | .02566 (23/0/8) | .9697/.8276 | 7.612 | 16/20 |
| faster-whisper | beam5 VAD | .02070 (19/4/2) | .9697/.8276 | .672 | 1/20 |
| Moonshine | CPU | .07202 (41/16/30) | .9667/.7500 | .224 | 1/20 |
| ORT Whisper turbo | CPU / DML | .04801 (19/37/2) each | 1/.8448 each | 3.134 each | 13/20 each |
| ORT Whisper small.en | CPU / DML | .12334 (36/102/11) each | .9800/.8448 each | 6.716 each | 20/20 each |

**Claims checked:** WP9 1.57% and 99/2/17 targets match. WP12 .0480 and exact CPU/DML transcript equality 60/60 match. WP13 .1233 and precisely one differing clip match. WP11 CPU .0720 and timing-set DML 3.628 versus CPU .543 match its described set-specific scoring (DML only ran timing clips). WP8’s .0207–.0248 range and hallucination figures match. WP10’s beam5 2.57%→1.90%, and 16/20→1/20, match; however its report target P/R for beam5 configurations (96.0%/81.9%) do **not** reproduce: centralized all-60 scoring is 96.97%/82.76%. WP10 beam1 report P/R (99%/82.8%) likewise differs from 96.91%/81.03%. Check or correct these target figures. WP8 table P/R is rounded coarsely; central rescore shows small differences (notably small.en CPU recall 82.76%, not 82.9%).

Normalization uses NFKC/casefold/alphanumeric-token matching with punctuation dropped and numerals left literal; constructed “banana cobalt harbor” case/punctuation variants score identically. Whisper control strings need explicit treatment: tokenizer regards `[BLANK_AUDIO]` as lexical `blank audio` and `[MUSIC]` as `music`; do not count these as ordinary recognized speech if raw transcript fields include them. No v2 silence record found with those tags in inspected full-mode outputs, but the v1 WP8 example explicitly did. All whitespace-separated isolated-word sequences in timing clips are scored as words; these are deliberately unnatural speech, not natural sentence performance. Numeric formatting is not converted (digit vs number words remain different).

## Independent timing rescore / matcher review

I matched normalized word tokens with a separate standard Levenshtein alignment (same deterministic diagonal/delete/insert tie order) and compared results to `matched_word_pairs`. Pair counts and metrics reproduced WP8, WP9, and WP10 tables to rounding. Key checks: Parakeet next-word end, 75 pairs: start mean/median/p95 61.9/48.5/160.0 ms, end 137.8/137.0/298.2; duration end 132.6/136.2/281.2 ms. Faster-whisper beam5 start 74.5/23.8/280.8 and end 168.7/170.2/319.2 ms on 71 matched words; WP10 values reproduce. Whisper.cpp all eight DTW/-ml1 configs also reproduce WP8’s shown figures. Missing timestamps: 0 in each listed output set.

WP14 oracle and ASR-vs-native aggregates were not recomputed here: those require its derived aligner pipeline tree and a substantially larger paired-observation join. Its figures are therefore not independently verified in this review. The source helper is appropriate for these one-token word records: NFKC/casefold punctuation normalization and exact-word Levenshtein matching preserve repeated occurrences. Its tie-break is deterministic but ambiguous in repeated-token insertion/deletion ties; document this where such a tie can alter which repeated occurrence is timed. `timing_metrics()` without explicit matches only casefolds raw strings (no punctuation/NFKC normalization); callers should continue passing `matched_word_pairs` results, as reports state.

Ground-truth construction boundaries are sample indices and robust as *construction boundaries*, not phonetic word onsets/offsets: isolated SAPI word clips are amplitude-trimmed at 1e-4 then concatenated with exact digital-zero gaps. Thus a stable acoustic trim/phonetic offset is expected, especially at tails; ASR/CTC frame boundaries need not equal trim edges. The scorer treats exact edges as truth, so timing errors measure agreement with this reproducible convention, not human-annotated phonetic boundaries. I did not perform subjective acoustic listening; no acoustic spot-check claim is made.

## Other audit checks

- **WP11 diagnostic:** `operator-diagnostic.json` supports the narrow observation: first greedy divergence is step index 1 (second decoder invocation), DML step has 14 NaN logits, CPU has none. First-step top-1 agrees even with own encoder output; second-step comparison with the same next token and separate provider caches also agrees top-1. It localizes the observed divergence but does not establish which operator, cache tensor, provider kernel, or precision behavior caused it. WP11’s caveat is appropriately cautious.
- **WP15 determinism:** report records exact 60/60 PCM equality and whole-WAV inequality attributable to PEAK timestamp metadata. I inspected the report evidence, not old headers/PCM independently; stated comparison is plausible but not independently verified here.
- **Model provenance:** sampled metadata identifies the named approved artifacts; no evidence in examined raw output points to an alternate model path. This is not a complete filesystem audit of weights.
- **v1 untouched:** all files under `C:\scratch\asr50\results\` had timestamps from 16:26:31 through 17:05:46 on Nov 26, before the reported ~17:15 phase start. Timestamp evidence supports no v1 writes during this phase (not cryptographic proof).

## Severity-ranked actionable findings

1. **Medium — WP10 target metrics mismatch.** Central all-clip rescore differs from reported target P/R for all three configs; resolve target scope or fix report values.
2. **Medium — lexical normalization/control tokens.** State consistently that Whisper control tags are excluded from lexical hypotheses; tokenizer otherwise counts their content as words. Keep numerals literal and disclose that constructed isolated-word clips are not natural speech.
3. **Low — timing interpretation.** Exact constructed edges are reproducible sample boundaries, but not human phonetic boundaries; fixed trim/aligner conventions and isolated-word prosody limit claims. WP14 aggregate figures remain unverified here.
4. **Low — repeated-word ties.** Matcher uses deterministic edit-path tie resolution; report ambiguity only matters for repeated tokens with tied edits, not the reproduced corpus totals.

## Verified OK

Central lexical values substantiate the main WP8–WP13 headline WER and hallucination claims except WP10 target P/R. Timing recomputation confirms WP8/9/10 reported timing statistics. WP11 diagnostic supports second-invocation divergence and NaNs without proving cause. Raw v1 timestamps precede phase start. No evidence of model substitution or modifications to the frozen corpus was found.

### Summary (<350 words)

Central `score.py` rescore across 60 clips per configuration confirms the main WER and hallucination claims: Parakeet .01573; faster-whisper .02070–.03063; whisper.cpp .02070–.02483; Moonshine CPU .07202; ORT turbo .04801 on both devices; ORT small.en .12334 on both. WP12 text equality 60/60 and WP13 one differing clip reproduce. WP10 target precision/recall claims do not: beam5 no-VAD/VAD central P/R is 96.97%/82.76%, versus reported 96.0%/81.9%; beam1 is 96.91%/81.03%, versus 99%/82.8%. WP8 small.en CPU recall also rounds differently (82.76%, not 82.9%). Timing was independently recomputed with a separate Levenshtein matcher; Parakeet, faster-whisper and all whisper.cpp DTW/-ml1 results reproduce to rounding. WP14 aggregate timing was not independently recomputed. Matcher normalization is sound for one-token words; repeated-word edit ties are deterministic but can be ambiguous, and direct `timing_metrics` default matching lacks full normalization. WP11 diagnostic supports first divergence at decoder invocation two with 14 DML NaNs but not a causal operator diagnosis. WP15 PEAK/PCM evidence and model-path audit were reviewed, not independently reproduced. v1 file timestamps (16:26–17:05) precede ~17:15 phase start. No acoustic listening was done; construction edges are exact trimmed-sample edges, not validated phonetic labels. No corpus/results/reports/repo changes, downloads, or installs.
