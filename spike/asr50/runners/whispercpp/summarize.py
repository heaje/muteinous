"""Score results.jsonl using the canonical benchmark scorer."""
import importlib.util
import json
from collections import defaultdict
from pathlib import Path

root = Path(r"C:\scratch\asr50\results\whispercpp")
spec = importlib.util.spec_from_file_location(
    "score", r"C:\code\muteinous-spike50\spike\asr50\benchmark\score.py")
score = importlib.util.module_from_spec(spec)
spec.loader.exec_module(score)
rows = [json.loads(x) for x in (root / "results.jsonl").read_text(encoding="utf-8").splitlines()]
groups = defaultdict(list)
for row in rows:
    groups[(row["candidate"], row["device"]["requested"])].append(row)
summary = {}
for (candidate, device), records in groups.items():
    sub = sum(x["metrics"]["substitutions"] for x in records)
    dele = sum(x["metrics"]["deletions"] for x in records)
    ins = sum(x["metrics"]["insertions"] for x in records)
    refs = {x["clip_id"]: x for x in records}
    selected = [x for x in records if x["run"]["kind"] == "functional"]
    if not selected:
        selected = [x for x in records if x["run"]["kind"] == "cold"]
    hyp = [x["hypothesis"]["text"] for x in selected]
    ref_words = []
    for x in selected:
        gt = json.loads((Path(r"C:\scratch\asr50\WP6\audio16k") / "ground_truth.json").read_text(encoding="utf-8"))
        ref_words += [w["text"] for c in gt["clips"] if c["clip_id"] == x["clip_id"] for w in c["words"]]
    target_totals = [x["metrics"]["targets"] for x in selected]
    tp = sum(x["true_positives"] for x in target_totals)
    fp = sum(x["false_positives"] for x in target_totals)
    fn = sum(x["false_negatives"] for x in target_totals)
    target_precision = tp / (tp + fp) if tp + fp else (1.0 if not fn else 0.0)
    target_recall = tp / (tp + fn) if tp + fn else (1.0 if not fp else 0.0)
    time_rows = [x["metrics"]["timing"] for x in selected]
    audio_seconds = sum(x["measurements"]["audio_duration_s"] for x in selected)
    timed = [x for x in selected if x["measurements"]["runtime_s"] is not None]
    inference_seconds = sum(x["measurements"]["runtime_s"] for x in timed)
    silence = [x for x in selected if x["category"] in {"silence", "non_speech"}]
    sil_metrics = score.hallucination_metrics([
        {"duration_s": x["measurements"]["audio_duration_s"], "hypothesis": x["hypothesis"]["text"]}
        for x in silence])
    summary[f"{candidate}/{device}"] = {
        "clips": len(selected), "aggregate_wer": (sub + dele + ins) / len(ref_words) if ref_words else None,
        "s": sub, "d": dele, "i": ins,
        "target_precision": target_precision, "target_recall": target_recall,
        "timing": time_rows,
        "missing_alignment_words": sum(x["missing_alignment_words"] for x in time_rows),
        "silence_non_speech": sil_metrics,
        "rtf": inference_seconds / audio_seconds if audio_seconds and len(timed) == len(selected) else None,
        "ram_peak_bytes": max((x["measurements"]["peak_ram_bytes"] for x in records
                               if x["measurements"]["peak_ram_bytes"] is not None), default=None),
        "vram_peak_bytes": max((x["measurements"]["peak_vram_bytes"] for x in records
                                if x["measurements"]["peak_vram_bytes"] is not None), default=None),
    }
(root / "score-summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
print(json.dumps(summary, indent=2))
