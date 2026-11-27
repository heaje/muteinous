"""Score Parakeet results on the frozen corpus-v2 files."""
import importlib.util
import json
import math
import pathlib
import statistics
import sys

BENCH = pathlib.Path(r"C:\code\muteinous-spike50\spike\asr50\benchmark")
CORPUS = pathlib.Path(r"C:\scratch\asr50\corpus_v2_frozen")
RAW = pathlib.Path(r"C:\scratch\asr50\results_v2\sherpa-parakeet\cpu")
OUTPUT = RAW.parent

spec = importlib.util.spec_from_file_location("score", BENCH / "score.py")
score = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = score
spec.loader.exec_module(score)


def summarize(values):
    return {
        "mean_ms": statistics.mean(values) if values else None,
        "median_ms": statistics.median(values) if values else None,
        "p95_ms": score.percentile_nearest_rank(values, 0.95),
        "within_ms": {
            str(limit): (sum(v <= limit for v in values) / len(values) if values else None)
            for limit in (50, 100, 200)
        },
    }


def main():
    truth = json.loads((CORPUS / "ground_truth_v2.json").read_text(encoding="utf-8"))
    records = []
    by_id = {}
    for clip in truth["clips"]:
        raw = json.loads((RAW / f"{clip['clip_id']}.json").read_text(encoding="utf-8"))
        if raw["clip_set"] != clip["set"]:
            raise ValueError(f"clip_set mismatch for {clip['clip_id']}")
        by_id[clip["clip_id"]] = (clip, raw)
        records.append((clip, raw))

    # Lexical WER over transcript-bearing speech clips only.
    speech = [(c, r) for c, r in records if c["category"] not in ("silence", "non_speech")]
    edits = [score.edit_counts(score.tokenize(c["transcript"]),
                               score.tokenize(r["text"])) for c, r in speech]
    substitutions = sum(e["substitutions"] for e in edits)
    deletions = sum(e["deletions"] for e in edits)
    insertions = sum(e["insertions"] for e in edits)
    reference_words = sum(len(score.tokenize(c["transcript"])) for c, _ in speech)
    lexical_wer = ((substitutions + deletions + insertions) / reference_words
                   if reference_words else None)

    # Exact target occurrence counts across all 60 clips, including negative clips.
    target_counts = {"true_positives": 0, "false_positives": 0, "false_negatives": 0}
    for clip, raw in records:
        metric = score.target_metrics(clip["transcript"], raw["text"])
        for key in target_counts:
            target_counts[key] += metric[key]
    tp, fp, fn = (target_counts["true_positives"], target_counts["false_positives"],
                  target_counts["false_negatives"])
    precision = tp / (tp + fp) if tp + fp else (1.0 if not fn else 0.0)
    recall = tp / (tp + fn) if tp + fn else (1.0 if not fp else 0.0)
    target_counts.update(precision=precision, recall=recall,
                         f1=2 * precision * recall / (precision + recall)
                         if precision + recall else 0.0)

    negatives = [
        {"duration_s": c["duration_s"], "hypothesis": r["text"]}
        for c, r in records if c["category"] in ("silence", "non_speech")
    ]
    hallucinations = score.hallucination_metrics(negatives)

    timing_by_clip = {}
    start_errors = []
    primary_end_errors = []
    duration_end_errors = []
    missing_words = total_hyp_words = matched_words = 0
    for clip, raw in records:
        if clip["set"] != "timing":
            continue
        ref_words = [
            {"text": w["text"],
             "start_s": w["start_sample"] / truth["sample_rate_hz"],
             "end_s": w["end_sample"] / truth["sample_rate_hz"]}
            for w in clip["words"]
        ]
        hyp_primary = [
            {"text": w["word"], "start_s": w["start"], "end_s": w["end"]}
            for w in raw["words"]
        ]
        hyp_duration = [
            {"text": w["word"], "start_s": w["start"], "end_s": w["end"]}
            for w in raw["words_duration_end"]
        ]
        pairs = score.matched_word_pairs(ref_words, hyp_primary)
        primary = score.timing_metrics(ref_words, hyp_primary, matches=pairs)
        alternative = score.timing_metrics(ref_words, hyp_duration, matches=pairs)
        timing_by_clip[clip["clip_id"]] = {
            "primary_next_word_start": primary,
            "alternative_last_token_start_plus_duration": alternative,
            "matched_word_pairs": len(pairs),
        }
        total_hyp_words += len(hyp_primary)
        missing_words += primary["missing_alignment_words"]
        for ri, hi in pairs:
            r, h1, h2 = ref_words[ri], hyp_primary[hi], hyp_duration[hi]
            vals = (r.get("start_s"), r.get("end_s"), h1.get("start_s"),
                    h1.get("end_s"), h2.get("end_s"))
            if all(isinstance(x, (int, float)) and math.isfinite(x) for x in vals):
                matched_words += 1
                start_errors.append(abs(vals[0] - vals[2]) * 1000)
                primary_end_errors.append(abs(vals[1] - vals[3]) * 1000)
                duration_end_errors.append(abs(vals[1] - vals[4]) * 1000)

    timing = {
        "timing_clip_count": len(timing_by_clip),
        "boundary_source": "constructed exact start_sample/end_sample",
        "matched_word_pairs": matched_words,
        "hypothesized_words": total_hyp_words,
        "missing_alignment_words": missing_words,
        "missing_alignment_rate": missing_words / total_hyp_words if total_hyp_words else 0.0,
        "start_error": summarize(start_errors),
        "end_error_next_word_start": summarize(primary_end_errors),
        "end_error_last_token_start_plus_duration": summarize(duration_end_errors),
        "per_clip": timing_by_clip,
    }
    summary = {
        "candidate": "sherpa-parakeet",
        "corpus": "corpus_v2_frozen",
        "clip_count": len(records),
        "clip_sets": {"timing": sum(c["set"] == "timing" for c, _ in records),
                      "natural": sum(c["set"] == "natural" for c, _ in records)},
        "lexical_speech_clip_count": len(speech),
        "speech_reference_words": reference_words,
        "wer": lexical_wer,
        "substitutions": substitutions, "deletions": deletions, "insertions": insertions,
        "target_words_all_clips": target_counts,
        "silence_non_speech_hallucinations": hallucinations,
        "timing": timing,
        "clip_results": {
            c["clip_id"]: {"clip_set": c["set"], "category": c["category"],
                           "reference": c["transcript"], "hypothesis": r["text"]}
            for c, r in records
        },
    }
    (OUTPUT / "score-summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "wer": lexical_wer, "substitutions": substitutions,
        "deletions": deletions, "insertions": insertions,
        "target_words_all_clips": target_counts,
        "silence_non_speech_hallucinations": hallucinations,
        "timing": {k: v for k, v in timing.items() if k != "per_clip"},
    }, indent=2))


if __name__ == "__main__":
    main()
