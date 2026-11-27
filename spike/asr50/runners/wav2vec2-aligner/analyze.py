import json
from collections import defaultdict
from pathlib import Path
import statistics
import sys

ROOT = Path(r"C:\scratch\asr50\results\wav2vec2-aligner")
sys.path.insert(0, r"C:\code\muteinous-spike50\spike\asr50\benchmark")
from score import matched_word_pairs, timing_metrics
oracle = json.loads((ROOT / "cpu" / "oracle.json").read_text(encoding="utf-8"))
pipeline = json.loads((ROOT / "cpu" / "pipeline.json").read_text(encoding="utf-8"))
for row in oracle:
    row["aligner_timing_metrics"] = timing_metrics(
        row["reference_words"], row["words"],
        matched_word_pairs(row["reference_words"], row["words"]))


def group_metrics(rows, key, metric_field):
    buckets = defaultdict(list)
    for row in rows:
        metrics = row.get(metric_field)
        if not metrics:
            continue
        buckets[key(row)].append(metrics)
    result = {}
    for group, vals in sorted(buckets.items()):
        starts = [v["start_error"]["mean_ms"] for v in vals if v["start_error"]["mean_ms"] is not None]
        ends = [v["end_error"]["mean_ms"] for v in vals if v["end_error"]["mean_ms"] is not None]
        result[group] = {
            "clip_observations": len(vals),
            "start_mean_ms_macro": statistics.mean(starts) if starts else None,
            "end_mean_ms_macro": statistics.mean(ends) if ends else None,
            "start_within_100ms_macro": statistics.mean(
                [v["start_error"]["within_ms"]["100"] for v in vals
                 if v["start_error"]["within_ms"]["100"] is not None]) if starts else None,
            "missing_words": sum(v["missing_alignment_words"] for v in vals),
        }
    return result


counts = defaultdict(int)
for r in pipeline:
    counts[f"{r['runner']}/{r['config']}"] += 1
behavior = json.loads((ROOT / "behavior.json").read_text(encoding="utf-8"))
hall = behavior["clean_001:The banana rests beside cobalt near the harbor and hallucination"]["words"]
true_scores = [w["alignment_score"] for w in hall[:8]]
hall_scores = [w["alignment_score"] for w in hall[8:]]
silence_score = behavior["silence_001:banana"]["words"][0]["alignment_score"]
result = {
    "oracle_by_category": group_metrics(oracle, lambda r: r["category"], "aligner_timing_metrics"),
    "pipeline_by_category": group_metrics(pipeline, lambda r: r["category"], "aligner_timing_metrics"),
    "pipeline_by_runner_config": {
        "observations": dict(sorted(counts.items())),
        "aligner_start_mean_ms_macro": statistics.mean(
            [r["aligner_timing_metrics"]["start_error"]["mean_ms"] for r in pipeline
             if r["aligner_timing_metrics"]["start_error"]["mean_ms"] is not None]),
        "native_start_mean_ms_macro": statistics.mean(
            [r["native_timing_metrics"]["start_error"]["mean_ms"] for r in pipeline
             if r["native_timing_metrics"] and r["native_timing_metrics"]["start_error"]["mean_ms"] is not None]),
    },
    "same_native_timestamp_observations": {
        "count": sum(r["native_timing_metrics"] is not None for r in pipeline),
        "aligner_start_mean_ms_macro": statistics.mean(
            [r["aligner_timing_metrics"]["start_error"]["mean_ms"] for r in pipeline
             if r["native_timing_metrics"] is not None
             and r["aligner_timing_metrics"]["start_error"]["mean_ms"] is not None]),
        "native_start_mean_ms_macro": statistics.mean(
            [r["native_timing_metrics"]["start_error"]["mean_ms"] for r in pipeline
             if r["native_timing_metrics"] is not None
             and r["native_timing_metrics"]["start_error"]["mean_ms"] is not None]),
        "aligner_end_mean_ms_macro": statistics.mean(
            [r["aligner_timing_metrics"]["end_error"]["mean_ms"] for r in pipeline
             if r["native_timing_metrics"] is not None
             and r["aligner_timing_metrics"]["end_error"]["mean_ms"] is not None]),
        "native_end_mean_ms_macro": statistics.mean(
            [r["native_timing_metrics"]["end_error"]["mean_ms"] for r in pipeline
             if r["native_timing_metrics"] is not None
             and r["native_timing_metrics"]["end_error"]["mean_ms"] is not None]),
    },
    "hallucination_score_probe": {
        "true_words": len(true_scores), "true_mean_logp": statistics.mean(true_scores),
        "hallucinated_words": len(hall_scores), "hallucinated_mean_logp": statistics.mean(hall_scores),
        "true_minus_hallucinated_logp": statistics.mean(true_scores) - statistics.mean(hall_scores),
        "silence_forced_banana_logp": silence_score,
        "interpretation": "Less-negative per-word mean CTC emission log-probability supported true transcript words better in this probe; uncalibrated and not a universal threshold."
    }
}
(ROOT / "analysis.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
