"""Render the aggregate-only WP24 report from local scratch summaries."""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(r"C:\scratch\asr50\WP24")
REPORT = Path(r"C:\scratch\asr50\reports\WP24.md")
ENGINE_ORDER = [
    "Parakeet TDT int8 CPU",
    "whisper.cpp Turbo q5_0 Vulkan",
    "whisper.cpp Small.en q5_1 Vulkan",
    "ORT Whisper Small.en fp16 DML-request",
    "faster-whisper Small.en int8 CPU",
    "ORT Whisper Turbo q4 DML-request",
]


def pct(value):
    return "—" if value is None else f"{value * 100:.2f}%"


def number(value):
    return "—" if value is None else f"{value:,.0f}"


def main():
    analysis = json.loads((ROOT / "analysis_summary.json").read_text(encoding="utf-8"))
    context = json.loads((ROOT / "context_summary.json").read_text(encoding="utf-8"))
    samples = json.loads((ROOT / "sample_manifest.json").read_text(encoding="utf-8"))["sampled"]
    vad = json.loads((ROOT / "vadmasked" / "manifest.json").read_text(encoding="utf-8"))["clips"]
    gate = {x["input"]: x for x in vad}
    speech = [x for x in samples if x["sample_kind"] == "speech"]
    vocal = [x for x in samples if x["sample_kind"] != "speech"]
    source_formats = {
        "48 kHz PCM16, mono": 15728,
        "48 kHz PCM16, stereo": 31,
        "48 kHz PCM16, 4-channel": 25,
        "48 kHz PCM16, 6-channel": 36,
    }
    by_line_gate = defaultdict(lambda: [0, 0])
    for row in speech:
        entry = by_line_gate[row["line_type"]]
        entry[0] += 1
        entry[1] += int(bool(gate[row["clip_id"] + ".wav"]["gate_no_speech"]))
    by_vocal_gate = defaultdict(lambda: [0, 0])
    for row in vocal:
        entry = by_vocal_gate[row["vocalization_type"]]
        entry[0] += 1
        entry[1] += int(not bool(gate[row["clip_id"] + ".wav"]["gate_no_speech"]))

    lines = [
        "# WP24 — Real FF7R voice-audio test",
        "",
        "**Status:** complete; local-only sample. No game audio, subtitle lines, or transcript text is included in this report.",
        "",
        "## Summary (<300 words)",
        "",
        "A deterministic, stratified sample of 300 subtitle-mapped English voice clips and 60 uncaptioned vocalization candidates was evaluated. Direct FF7R adapter mapping linked 963 of 15,820 extracted WAVs to a subtitle. All six requested model configurations completed 360 clips each; the mapped-speech subtitle WER ranged from 8.78% to 11.82%, while exact Hushpatch ASR text was unavailable for the mapped lines because its transcript cache covers unsubtitled lines. A six-engine per-clip medoid consensus differed from the subtitle on 60/300 clips with at least 4/6 configurations matching the medoid; this is a mismatch signal, not a verified transcript. Target-word recall against listed subtitle occurrences ranged from 91.46% to 95.43%. The Silero gate missed 3/300 speech clips and passed 31/60 vocalization candidates. Vulkan inference was verified by the `Vulkan0` log and PID-filtered GPU counters for both whisper.cpp models. ORT DirectML was requested and produced outputs, but WP24 PID-filtered counters did not match its process, so GPU execution is not claimed. No human transcription or timing truth was available; Hushpatch source and frozen data remained unchanged.",
        "",
        "## Scope, privacy, and setup",
        "",
        "- Source: the already-extracted Hushpatch FF7R voice tree only; the game installation was not accessed. Hushpatch code was imported read-only where needed.",
        "- Audio/text-derived files, raw transcripts, alignments, model outputs, clip list, logs, and analyses are confined to `C:\\scratch\\asr50\\WP24\\`. Only runner code is under `spike/asr50/real_audio/`.",
        "- No system installs, model downloads, commits, or Hushpatch/frozen-corpus modifications. `HF_HUB_OFFLINE=1`, `TRANSFORMERS_OFFLINE=1`, and `HF_HUB_DISABLE_TELEMETRY=1` were set for inference.",
        "- ASR was strictly serialized: one ASR process at a time. No speed benchmark was run. Existing disposable environments/artifacts were reused.",
        "- whisper.cpp has a 180 s per-clip hard timeout and writes per-clip checkpoints. Long library runner invocations were bounded by 2 h process timeouts; aligner/context passes were likewise bounded.",
        "- Runtime/model settings: Parakeet TDT 0.6B int8 / sherpa-onnx 2.0.3, CPU greedy; whisper.cpp Large-v3 Turbo q5_0 and Small.en q5_1 / CLI 1.9.6-dev, Vulkan0 and CPU controls, English, DTW timestamps; ORT Whisper Small.en fp16 and Turbo q4 / ONNX Runtime DirectML 1.24.4 requested, greedy; faster-whisper Small.en int8 / faster-whisper 1.2.1 + CTranslate2 4.9.1, beam 5, built-in VAD off, CPU.",
        "",
        "Mapping follows Hushpatch `UnrealTxtRes.lines()` / `_read_unsubtitled()`: a subtitle key directly maps to a voice asset stem only when the asset has one track. Multi-track banks are expanded as `asset#NNN` unsubtitled lines, not assigned the bank's single subtitle. See `C:\\code\\hushpatch\\src\\muteinous\\engines\\unreal\\txtres.py` lines 250–263 and 283–296.",
        "",
        "## Source inventory and sample",
        "",
        f"- WAV files: **15,820**. Header scan found {sum(source_formats.values()):,} PCM16 files, all 48 kHz: "
        + ", ".join(f"{k.split(', ')[1]} {v:,}" for k, v in source_formats.items()) + ".",
        f"- Direct subtitle mapping: **963 / 15,820 (6.09%)**. Hushpatch `transcripts.json` contains non-empty ASR strings for **14,857** unsubtitled lines; the 300 sampled mapped clips had **0** cached Hushpatch transcripts, so Hushpatch-vs-subtitle WER is unavailable (not 100% or zero).",
        "- Resampling: `soundfile` float32 decode, channel mean to mono, then `scipy.signal.resample_poly` to 16 kHz; output is mono IEEE float32 WAV. The fixed seed is **24027**. The reusable clip list is `WP24\\clip-list.csv`; `sample_manifest.json` retains the source/text only inside WP24.",
        "- Mapped source inventory by line-id prefix: talk 466, event 227, battle 102, PV 164, other 4. Mapped duration inventory: <2 s 276, 2–6 s 606, 6–15 s 81, >15 s 0.",
        "",
        "| Speech sample stratum | Clips |",
        "|---|---:|",
    ]
    for key, value in sorted(analysis["sample"]["line_types"].items()):
        lines.append(f"| line type `{key}` | {value} |")
    for key, value in sorted(analysis["sample"]["length_buckets"].items()):
        lines.append(f"| length `{key}` | {value} |")
    lines += [
        f"| speaker-code strata represented | {len(analysis['sample']['characters'])} |",
        "| **Mapped speech sample** | **300** |",
        "",
        "Speaker strata in the sample are the final speaker-code field in extracted line IDs (not canonical localized character names). Subtitle actor metadata was present on 228 clips: 35 matched a main-cast marker, 193 had other actor tags, and 72 had no actor tag; 74 distinct non-empty tags were represented. These private tags establish coverage across main and minor/other roles; no names are reproduced here. Code-level counts and WER are below. Duration strata include 31 clips from 6–15 s; no mapped clip exceeded 15 s.",
        "",
        "The 60 negative/control clips were selected from uncaptioned voice tracks whose local Hushpatch ASR output was an exact short vocalization/interjection or laugh label, then sampled across 60 distinct assets with a fixed seed: 58 effort/interjection candidates and 2 laugh candidates. These are **ASR-selected candidates, not audio-human-verified non-speech**. The extracted source is voice-only; it contains no ambient/music/SFX controls. Folder/line-ID tag screening flagged no heavy radio/intercom/distortion clips; absence of a tag is not acoustic verification, so the effect-heavy subgroup is unavailable.",
        "",
        "## Speech accuracy",
        "",
        "Scoring uses the unchanged `benchmark/score.py` NFKC/casefold tokenization, and sums S/D/I per clip rather than flattening across clips. Subtitle text is a useful reference but not ground truth.",
        "",
        "| Engine | Clips | Ref words | S | D | I | WER vs subtitle | WER vs consensus |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for engine in ENGINE_ORDER:
        s = analysis["subtitle_wer"][engine]
        c = analysis["consensus_wer"][engine]
        lines.append(
            f"| {engine} | {s['clips_scored']} | {s['reference_words']} | "
            f"{s['substitutions']} | {s['deletions']} | {s['insertions']} | "
            f"{pct(s['wer'])} | {pct(c['wer'])} |"
        )
    lines += [
        "",
        f"Hushpatch's own cached ASR text was present on **{analysis['hushpatch_asr_coverage']['with_transcript']}/{analysis['hushpatch_asr_coverage']['sampled_mapped_clips']}** sampled mapped lines. The source design caches ASR for unsubtitled lines; it does not provide a Hushpatch transcript baseline for these subtitle-bearing clips.",
        "",
        "### Subtitle-mismatch signal",
        "",
        f"The engine-consensus reference is the per-clip **medoid transcript** among the six requested model configurations: the candidate with minimum summed pairwise Levenshtein distance to the other five. **{analysis['subtitle_mismatch']['high_consensus_clips']}/300** mapped clips had a medoid different from the subtitle while at least 4/6 configurations exactly matched that medoid. This is a likely subtitle mismatch signal only—no human verified transcript is claimed. It may also reflect common-mode engine errors, line edits, or alignment differences.",
        "",
        "| Engine | High-consensus mismatch clips where output equals medoid |",
        "|---|---:|",
    ]
    for engine in ENGINE_ORDER:
        lines.append(f"| {engine} | {analysis['subtitle_mismatch']['engine_at_consensus_in_high_consensus_clips'].get(engine, 0)} |")

    def subgroup_table(dimension: str, heading: str):
        lines.extend(["", f"### WER by {heading}", "",
                      "| Group | n | " + " | ".join(ENGINE_ORDER) + " |",
                      "|---|---:|" + "|".join(["---:"] * len(ENGINE_ORDER)) + "|"])
        groups = sorted(analysis["subgroup_subtitle_wer"][ENGINE_ORDER[0]][dimension])
        for group in groups:
            metrics = [
                analysis["subgroup_subtitle_wer"][engine][dimension][group]
                for engine in ENGINE_ORDER
            ]
            n = metrics[0]["clips_scored"]
            lines.append(f"| {group} | {n} | " + " | ".join(pct(x["wer"]) for x in metrics) + " |")

    subgroup_table("line_type", "line type")
    subgroup_table("length_bucket", "length bucket")
    subgroup_table("effect_heavy", "effect tag")
    subgroup_table("character", "speaker-code character")

    lines += [
        "",
        "The effect-tag table contains only the `clean` row (n=300): no clip was flagged from folder/line-ID metadata. No effect-heavy WER can be inferred from it.",
        "",
        "## Listed-word coverage",
        "",
        f"Hushpatch `WordList.all_words()` contains {analysis['target_word_count']['all_wordlist_entries']} entries ({analysis['target_word_count']['ambiguous_entries']} ambiguous); the strict preset contained {analysis['target_word_count']['strict_preset_entries']} entries. `WordList.find()` matched {analysis['target_word_count']['subtitle_occurrences']} subtitle occurrences in {analysis['target_word_count']['clips_with_target']}/300 clips. Exact/recognized counts use canonical listed-word matches; insertions are ASR-listed occurrences absent from the subtitle. Mangled/variant and euphemism/bleep categories are heuristic.",
        "",
        "| Engine | Listed subtitle occurrences | Recognized | Recall | ASR-added listed occurrences | Miss: mangled/variant | Miss: missing | Miss: euphemized/bleeped/asterisk |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for engine in ENGINE_ORDER:
        x = analysis["targets"][engine]
        misses = x["miss_categories"]
        lines.append(
            f"| {engine} | {x['reference_occurrences']} | {x['recognized_occurrences']} | "
            f"{pct(x['recall'])} | {x['added_occurrences']} | "
            f"{misses.get('mangled/variant', 0)} | {misses.get('missing', 0)} | "
            f"{misses.get('euphemized/bleeped/asterisk', 0)} |"
        )
    lines += [
        "",
        "### Listed-word type breakdown",
        "",
        "| Engine | Word type | Subtitle occurrences | Recognized | Miss: variant | Miss: absent | Miss: bleep/euphemism |",
        "|---|---|---:|---:|---:|---:|---:|",
    ]
    categories = ["ambiguous", "non-ambiguous", "profanity", "deity", "crude", "slur"]
    for engine in ENGINE_ORDER:
        for category in categories:
            x = analysis["targets"][engine]["by_type"].get(category)
            if not x or not x.get("reference"):
                continue
            lines.append(
                f"| {engine} | {category} | {x.get('reference', 0)} | {x.get('recognized', 0)} | "
                f"{x.get('mangled/variant', 0)} | {x.get('missing', 0)} | "
                f"{x.get('euphemized/bleeped/asterisk', 0)} |"
            )

    lines += [
        "",
        "## Silero gate and vocalization candidates",
        "",
        "WP18 `apply_gate.py`, Silero VAD v6, CPU; threshold 0.5, 100 ms speech pad, 200 ms min-silence. The gate processed all 360 sampled clips.",
        "",
        "| Clip type | n | Gate no-speech (speech misses) | Passed to ASR (negative-set false pass) |",
        "|---|---:|---:|---:|",
    ]
    for group, (n, misses) in sorted(by_line_gate.items()):
        lines.append(f"| speech / {group} | {n} | {misses} ({pct(misses/n)}) | — |")
    for group, (n, passed) in sorted(by_vocal_gate.items()):
        lines.append(f"| vocalization candidate / {group} | {n} | — | {passed} ({pct(passed/n)}) |")
    total_speech_miss = sum(v[1] for v in by_line_gate.values())
    total_vocal_pass = sum(v[1] for v in by_vocal_gate.values())
    lines += [
        f"| **Total** | **360** | **{total_speech_miss}/300 ({pct(total_speech_miss/300)})** | **{total_vocal_pass}/60 ({pct(total_vocal_pass/60)})** |",
        "",
        "### Hallucinated output on the 60 vocalization candidates",
        "",
        "| Engine | Words/min | Clips with text | Empty | Spurious lexical | Repeated-token output | Bracketed nonverbal marker |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for engine in ENGINE_ORDER:
        x = analysis["non_speech"][engine]
        cats = x["output_categories"]
        lines.append(
            f"| {engine} | {x['words_per_minute']:.2f} | {x['clips_with_output']}/60 | "
            f"{cats.get('empty', 0)} | {cats.get('spurious_lexical_words', 0)} | "
            f"{cats.get('repeated_tokens', 0)} | {cats.get('bracketed_nonverbal_marker', 0)} |"
        )
    lines += [
        "",
        "Outputs on this set are classified from transcript form, not audio review; lexical output may be speech or hallucination. Vocalization-labelled cases are not a human ground truth set.",
        "",
        "## Native word-time / forced-alignment agreement",
        "",
        "wav2vec2-base-960h was forced to the subtitle text on the 300 mapped speech clips only. Exact lexical matches between each engine's native word list and the aligner output were compared; values below are median / nearest-rank p95 absolute boundary differences. **This is timestamp agreement, not timing accuracy**: subtitles can differ from speech, and neither source is timing truth.",
        "",
        "| Engine | Matched words | Native words missing start/end | Start median / p95 ms | End median / p95 ms |",
        "|---|---:|---:|---:|---:|",
    ]
    for engine in ENGINE_ORDER:
        x = analysis["timing_agreement"][engine]
        s, e = x["start_abs_ms"], x["end_abs_ms"]
        if not x["matched_words_with_both_boundaries"]:
            start_text = end_text = "unavailable"
        else:
            start_text = f"{s['median']:.1f} / {s['p95']:.1f}"
            end_text = f"{e['median']:.1f} / {e['p95']:.1f}"
        missing = (f"{x['missing_native_timing_words']}/{x['hypothesis_words']}"
                   if x["hypothesis_words"] else "not provided")
        lines.append(
            f"| {engine} | {x['matched_words_with_both_boundaries']} | {missing} | "
            f"{start_text} | {end_text} |"
        )
    lines += [
        "",
        "ORT Whisper's text-only greedy exports did not return word boundaries; no times were fabricated. The aligner produced usable subtitle word boundaries for all 300 clips; the alignment outputs and word text remain only in WP24.",
        "",
        "## GPU / CPU evidence and agreement",
        "",
        "| Configuration | Evidence from WP24 | Conclusion |",
        "|---|---|---|",
        "| whisper.cpp Turbo q5_0 Vulkan | 360/360 outputs contain the `using Vulkan0 backend` log line. A separate four-clip telemetry pass had PID-matched GPU-engine max 47.42% and dedicated-memory max 1,312,940,032 B. | Actual Vulkan inference verified (process-filtered counters + backend log). |",
        "| whisper.cpp Small.en q5_1 Vulkan | 360/360 outputs contain the `using Vulkan0 backend` log line. A separate repeated four-clip telemetry pass had PID-matched GPU-engine max 56.18% and dedicated-memory max 933,871,616 B. | Actual Vulkan inference verified (process-filtered counters + backend log). |",
        "| ORT Whisper Small.en fp16, DML requested | 40-clip short pass succeeded; counter rows existed, but none matched the candidate PID for GPU Engine or Dedicated Usage. | DML execution **not verified** in WP24. Provider list/request is insufficient. |",
        "| ORT Whisper Turbo q4, DML requested | 8-clip short pass succeeded; no candidate-PID matches in GPU Engine or Dedicated Usage counters. | DML execution **not verified** in WP24. Provider list/request is insufficient. |",
        "| Parakeet / faster-whisper | Explicit CPU paths. | CPU only. |",
        "",
        "The DML runners list DML plus CPU providers; this does not identify actual node placement. Their output scores are reported as model-run results with DML requested, not as verified GPU scores. No exact ORT CPU counterpart was run in WP24.",
        "",
        "| whisper.cpp model | GPU/CPU clips | Exact transcript agreement | Token-exact agreement | Speech exact agreement |",
        "|---|---:|---:|---:|---:|",
    ]
    for model, x in analysis["gpu_cpu_agreement"].items():
        lines.append(
            f"| {model} | {x['clips']} | {x['exact_transcript_agreement']}/{x['clips']} | "
            f"{x['token_exact_agreement']}/{x['clips']} | "
            f"{x['speech_exact_transcript_agreement']}/300 |"
        )

    lines += [
        "",
        "## Context decision proxy",
        "",
        "The CPU context process imported Hushpatch `application.context.model_loader(None)`, `inference.context.decide`, `WordList.load('strict')`, FF7R `keep_names`, idioms, and innocent phrases at runtime. Ambiguous listed words use the context classifier; non-ambiguous listed words follow the production direct-censor path, with names taking precedence. Agreement is conditional on the same listed-word occurrence being present in both subtitle and ASR; absent occurrences are counted separately. This is not human truth.",
        "",
        "| Engine | Matched word decisions | Agreement | Censor on subtitle, not ASR | Censor on ASR, not subtitle |",
        "|---|---:|---:|---:|---:|",
    ]
    for engine in ENGINE_ORDER:
        x = context["engines"][engine]
        lines.append(
            f"| {engine} | {x['matched_decisions']} | {pct(x['agreement'])} | "
            f"{x.get('censor_on_subtitle_not_asr', 0)} | "
            f"{x.get('censor_on_asr_not_subtitle', 0)} |"
        )
    lines += [
        f"",
        f"The context run made {context['model_calls']} unique model calls, reused {context['cache_hits']} cached decisions, and recorded {sum(context['decision_errors'].values())} decision errors.",
        "",
        "## Failures, limits, and reproducibility",
        "",
        "- All six requested model configurations have 360/360 final outputs; all per-clip inference errors are zero. Per-clip checkpoints and runner logs are retained in WP24.",
        "- A first whisper.cpp full pass had a harness PID-recording bug after successful inference; 360 failed-attempt records were preserved, then the runner was corrected and all 360 were rerun successfully. Initial DTW argument and telemetry-wrapper errors were also corrected; failed logs remain under WP24.",
        "- Initial ORT probe attempts had environment/input-manifest setup errors; corrected probes completed, but still produced no PID-matched DML counters. The Turbo runner emitted a non-fatal Transformers warning about PyTorch being absent; all 360 outputs/JSONL rows were written.",
        "- Single English game; subtitles are not verbatim truth (abbreviations, omissions, edits, speaker tags, line splits). ASR consensus is not a human transcript. Vocalization candidates were selected via existing ASR text and are not human-verified.",
        "- No ambient/music/SFX files were present in the extracted voice tree. Heavy effects were not acoustically screened; only folder/line-ID tags were used, so effect-heavy WER is unavailable.",
        "- Only this machine, its existing drivers/runtimes, and these approved artifacts were tested. ORT DML GPU placement remains unverified here. Word-time values are agreement statistics, never accuracy claims.",
        "- Copyrighted game audio/text and derived data remain local under WP24. The report contains aggregate numbers only; no dialogue fragments are quoted.",
        "",
        f"**Initial wall-time estimate:** 6–10 hours. **Observed wall time:** approximately 2 h 12 min from the first WP24 artifact (11:46 local) to report generation (13:58 local); earlier planning time is not included.",
        "",
        "### Final summary (<300 words)",
        "",
        "The direct FF7R voice-asset mapping linked 963/15,820 WAVs to subtitles. A seeded sample covered 300 mapped speech clips and 60 uncaptioned vocalization candidates. Six requested configurations completed all 360 clips with no final per-clip errors. Subtitle WER was 8.78–11.82%; the six-engine medoid differed from subtitles on 60/300 clips with ≥4/6 exact agreement, a mismatch signal rather than verified truth. Listed-word recall was 91.46–95.43%; Silero missed 3/300 speech clips and passed 31/60 vocalization candidates. Context-path agreement on matched listed-word decisions was 99.03–100%, with subtitle-censor/ASR-slip counts of 14–24 by engine. Native word times were available for Parakeet, faster-whisper, and whisper.cpp; ORT exports had none. Aligner/native differences are timing agreement only. Both whisper.cpp Vulkan paths were verified with `Vulkan0` logs and process-filtered counters. ORT DML execution remained unverified because its candidate PID did not appear in counters. Hushpatch's cached ASR transcripts were absent for the mapped subtitle lines. No game data left WP24, Hushpatch remained unchanged, and no speed benchmark or human verification was performed.",
        "",
    ]
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps({"report": str(REPORT), "characters": len("".join(lines)),
                      "speaker_code_rows": len(analysis["sample"]["characters"]),
                      "speech": len(speech), "vocalization_candidates": len(vocal)}))


if __name__ == "__main__":
    main()
