"""Score raw, masked-run, and masked gated-skip predictions for corpus v3."""
import importlib.util
import json
import pathlib
import sys

BENCH = pathlib.Path(r"C:\code\muteinous-spike50\spike\asr50\benchmark")
GT = pathlib.Path(r"C:\scratch\asr50\corpus_v3_frozen\ground_truth_v3.json")
ROOT = pathlib.Path(r"C:\scratch\asr50\results_v3\sherpa-parakeet")
spec = importlib.util.spec_from_file_location("score", BENCH / "score.py")
score = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = score
spec.loader.exec_module(score)


def lexical_summary(pairs):
    edits = [score.edit_counts(score.tokenize(c["transcript"]),
                               score.tokenize(o["text"])) for c, o in pairs]
    subs = sum(e["substitutions"] for e in edits)
    dels = sum(e["deletions"] for e in edits)
    ins = sum(e["insertions"] for e in edits)
    refs = sum(len(score.tokenize(c["transcript"])) for c, _ in pairs)
    return {
        "clips": len(pairs), "reference_words": refs,
        "substitutions": subs, "deletions": dels, "insertions": ins,
        "wer": (subs + dels + ins) / refs if refs else None,
    }


def grouped_wer(pairs, key):
    groups = {}
    for clip, output in pairs:
        group = key(clip)
        if group is None:
            continue
        groups.setdefault(group, []).append((clip, output))
    return {str(group): lexical_summary(items) for group, items in sorted(groups.items())}


def evaluate(view, pairs):
    speech = [(c, o) for c, o in pairs if not c["category"].startswith("non_speech_")]
    targets = {"true_positives": 0, "false_positives": 0, "false_negatives": 0}
    for clip, output in pairs:
        m = score.target_metrics(clip["transcript"], output["text"])
        for k in targets:
            targets[k] += m[k]
    tp, fp, fn = (targets["true_positives"], targets["false_positives"],
                  targets["false_negatives"])
    precision = tp / (tp + fp) if tp + fp else (1.0 if not fn else 0.0)
    recall = tp / (tp + fn) if tp + fn else (1.0 if not fp else 0.0)
    targets.update(precision=precision, recall=recall,
                   f1=2 * precision * recall / (precision + recall)
                   if precision + recall else 0.0)
    negative = [
        {"duration_s": c["duration_s"], "hypothesis": o["text"]}
        for c, o in pairs if c["category"].startswith("non_speech_")
    ]
    per_negative = {}
    for category in sorted({c["category"] for c, _ in pairs
                            if c["category"].startswith("non_speech_")}):
        items = [(c, o) for c, o in pairs if c["category"] == category]
        per_negative[category] = score.hallucination_metrics([
            {"duration_s": c["duration_s"], "hypothesis": o["text"]}
            for c, o in items
        ])
    return {
        "view": view,
        "overall_speech": lexical_summary(speech),
        "wer_by_condition": grouped_wer(speech, lambda c: c["condition"]),
        "wer_by_voice": grouped_wer(speech, lambda c: c.get("voice")),
        "wer_by_rate": grouped_wer(speech, lambda c: c.get("rate")),
        "target_words_all_380_clips": targets,
        "non_speech_hallucinations": score.hallucination_metrics(negative),
        "non_speech_by_category": per_negative,
    }


def main():
    truth = json.loads(GT.read_text(encoding="utf-8"))
    if len(truth["clips"]) != 380:
        raise ValueError("Expected 380 ground-truth records")
    manifest = json.loads(
        pathlib.Path(r"C:\scratch\asr50\WP18\corpus_v3_vadmasked\manifest.json")
        .read_text(encoding="utf-8"))
    gate = {pathlib.Path(x["input"]).stem: bool(x["gate_no_speech"])
            for x in manifest["clips"]}
    raw_pairs, masked_pairs, gated_pairs = [], [], []
    transcript_summary = {}
    for clip in truth["clips"]:
        cid = clip["clip_id"]
        raw = json.loads((ROOT / "raw" / "cpu" / f"{cid}.json").read_text(encoding="utf-8"))
        masked = json.loads((ROOT / "masked" / "cpu" / f"{cid}.json").read_text(encoding="utf-8"))
        is_gated = gate[cid]
        if raw["gate_no_speech"] != is_gated or masked["gate_no_speech"] != is_gated:
            raise ValueError(f"VAD flag mismatch for {cid}")
        raw_output = {"text": raw["text"]}
        masked_output = {"text": masked["text"]}
        gated_output = {"text": ""} if is_gated else masked_output
        raw_pairs.append((clip, raw_output))
        masked_pairs.append((clip, masked_output))
        gated_pairs.append((clip, gated_output))
        transcript_summary[cid] = {
            "condition": clip["condition"], "category": clip["category"],
            "gate_no_speech": is_gated, "reference": clip["transcript"],
            "raw": raw["text"], "masked": masked["text"],
            "masked_gated_skip": gated_output["text"],
        }
    views = [
        evaluate("A-raw", raw_pairs),
        evaluate("B-masked-run", masked_pairs),
        evaluate("B-gated-skip", gated_pairs),
    ]
    output = {
        "corpus": "corpus_v3_frozen",
        "clip_count": len(truth["clips"]),
        "speech_clip_count": sum(not c["category"].startswith("non_speech_")
                                 for c in truth["clips"]),
        "non_speech_clip_count": sum(c["category"].startswith("non_speech_")
                                     for c in truth["clips"]),
        "gate_no_speech_count": sum(gate.values()),
        "gate_flagged_speech": sum(
            gate[c["clip_id"]] and not c["category"].startswith("non_speech_")
            for c in truth["clips"]),
        "gate_passed_non_speech": sum(
            not gate[c["clip_id"]] and c["category"].startswith("non_speech_")
            for c in truth["clips"]),
        "views": views,
        "clip_results": transcript_summary,
    }
    (ROOT / "score-comparison.json").write_text(
        json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    compact = {}
    for v in views:
        compact[v["view"]] = {
            "overall_speech": v["overall_speech"],
            "target_words_all_380_clips": v["target_words_all_380_clips"],
            "non_speech_hallucinations": v["non_speech_hallucinations"],
            "wer_by_condition": v["wer_by_condition"],
            "wer_by_voice": v["wer_by_voice"],
            "wer_by_rate": v["wer_by_rate"],
        }
    print(json.dumps({
        "gate_no_speech": output["gate_no_speech_count"],
        "gate_flagged_speech": output["gate_flagged_speech"],
        "gate_passed_non_speech": output["gate_passed_non_speech"],
        "views": compact,
    }, indent=2))


if __name__ == "__main__":
    main()
