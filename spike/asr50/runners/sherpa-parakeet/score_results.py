"""Score normalized candidate JSON using the repository's unmodified scorer."""
import argparse
import importlib.util
import json
import math
import pathlib
import sys

root = pathlib.Path(r"C:\code\muteinous-spike50\spike\asr50\benchmark")
spec = importlib.util.spec_from_file_location("score", root / "score.py")
score = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = score
spec.loader.exec_module(score)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--raw", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    raw_dir = pathlib.Path(args.raw)
    output = pathlib.Path(args.out)
    truth = json.loads(pathlib.Path(
        r"C:\scratch\asr50\WP6\audio16k\ground_truth.json").read_text(encoding="utf-8"))
    refs = {c["clip_id"]: c for c in truth["clips"]}
    rows = []
    for clip_id, reference in refs.items():
        pred = json.loads((raw_dir / f"{clip_id}.json").read_text(encoding="utf-8"))
        rows.append((clip_id, reference, pred))
    ref_words = [w for _, r, _ in rows for w in score.tokenize(r["transcript"])]
    hyp_words = [w for _, _, p in rows for w in score.tokenize(p["text"])]
    edits = [score.edit_counts(score.tokenize(r["transcript"]),
                               score.tokenize(p["text"]))
             for _, r, p in rows]
    substitutions = sum(e["substitutions"] for e in edits)
    deletions = sum(e["deletions"] for e in edits)
    insertions = sum(e["insertions"] for e in edits)
    word_count = len(ref_words)
    wer = (substitutions + deletions + insertions) / word_count if word_count else 0.0
    targets = {"true_positives": 0, "false_positives": 0, "false_negatives": 0}
    for _, reference, prediction in rows:
        m = score.target_metrics(reference["transcript"], prediction["text"])
        for key in targets:
            targets[key] += m[key]
    tp, fp, fn = (targets["true_positives"], targets["false_positives"],
                  targets["false_negatives"])
    targets.update(precision=tp / (tp + fp) if tp + fp else (1.0 if not fn else 0.0),
                   recall=tp / (tp + fn) if tp + fn else (1.0 if not fp else 0.0))
    targets["f1"] = (2 * targets["precision"] * targets["recall"] /
                     (targets["precision"] + targets["recall"])
                     if targets["precision"] + targets["recall"] else 0.0)
    timing = {
        "clips": {
            cid: score.timing_metrics(r["words"], [
                {"text": w["word"], "start_s": w["start"], "end_s": w["end"]}
                for w in p["words"]])
            for cid, r, p in rows
        }
    }
    start_errors, end_errors = [], []
    for _, reference, prediction in rows:
        hyp = [{"text": w["word"], "start_s": w["start"], "end_s": w["end"]}
               for w in prediction["words"]]
        matched = score.edit_counts(
            [score.tokenize(w["text"])[0] for w in reference["words"]],
            [score.tokenize(w["text"])[0] for w in hyp])["matches"]
        for ri, hi in matched:
            r, h = reference["words"][ri], hyp[hi]
            vals = (r.get("start_s"), r.get("end_s"), h.get("start_s"), h.get("end_s"))
            if all(isinstance(v, (int, float)) and math.isfinite(v) for v in vals):
                start_errors.append(abs(vals[0] - vals[2]) * 1000)
                end_errors.append(abs(vals[1] - vals[3]) * 1000)
    def timing_summary(values):
        return {
            "mean_ms": sum(values) / len(values) if values else None,
            "median_ms": score.median(values) if values else None,
            "p95_ms": score.percentile_nearest_rank(values, .95),
            "within_ms": {str(t): sum(v <= t for v in values) / len(values)
                          if values else None for t in (50, 100, 200)},
        }
    timing["all_matched_words"] = {
        "matched_words": len(start_errors),
        "hypothesized_words": sum(len(p["words"]) for _, _, p in rows),
        "missing_alignment_words": sum(
            1 for _, _, p in rows for w in p["words"]
            if not all(isinstance(w.get(k), (int, float)) and math.isfinite(w[k])
                       for k in ("start", "end"))),
        "start_error": timing_summary(start_errors),
        "end_error": timing_summary(end_errors),
    }
    silence = score.hallucination_metrics([
        {"duration_s": r["duration_s"], "hypothesis": p["text"]}
        for _, r, p in rows if r["category"] in ("silence", "non_speech")
    ])
    output.mkdir(parents=True, exist_ok=True)
    summary = {
        "candidate": "sherpa-parakeet", "wer": wer,
        "substitutions": substitutions, "deletions": deletions,
        "insertions": insertions, "reference_words": word_count,
        "target_words": targets, "timing_by_clip": timing,
        "silence_non_speech_hallucinations": silence,
        "clip_results": {
            cid: {"reference": r["transcript"], "hypothesis": p["text"],
                  "category": r["category"]}
            for cid, r, p in rows
        },
    }
    (output / "score-summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: summary[k] for k in (
        "wer", "substitutions", "deletions", "insertions", "target_words",
        "silence_non_speech_hallucinations")}, indent=2))


if __name__ == "__main__":
    main()
