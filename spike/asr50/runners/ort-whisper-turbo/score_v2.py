"""Score corpus v2 device outputs and compare the prototype silence gate."""
import collections
import importlib.util
import json
import pathlib
import sys

root = pathlib.Path(r"C:\code\muteinous-spike50\spike\asr50")
spec = importlib.util.spec_from_file_location("asr_score", root / "benchmark" / "score.py")
score = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = score
spec.loader.exec_module(score)
truth_data = json.loads(pathlib.Path(
    r"C:\scratch\asr50\corpus_v2_frozen\ground_truth_v2.json").read_text(encoding="utf-8"))
truth = {c["clip_id"]: c for c in truth_data["clips"]}
path = pathlib.Path(r"C:\scratch\asr50\results_v2\ort-whisper-turbo\results.jsonl")
records = [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x]
by_device = collections.defaultdict(dict)
for r in records:
    by_device[r["device"]["requested"]][r["clip_id"]] = r
speech_ids = [c["clip_id"] for c in truth_data["clips"]
              if c["category"] not in ("silence", "non_speech")]
hall_ids = [c["clip_id"] for c in truth_data["clips"]
            if c["category"] in ("silence", "non_speech")]
hall_by_category = {
    category: [c["clip_id"] for c in truth_data["clips"] if c["category"] == category]
    for category in ("silence", "non_speech")
}


def lexical(device, ids, text_key="hypothesis"):
    refs, hyps = [], []
    edits = 0
    for clip_id in ids:
        r = by_device[device][clip_id]
        ref = score.tokenize(truth[clip_id]["transcript"])
        hypothesis = (r["hypothesis"]["text"] if text_key == "hypothesis" or r["guard"] is None
                     else r["guard_text"])
        hyp = score.tokenize(hypothesis or "")
        refs.extend(ref)
        hyps.extend(hyp)
        counts = score.edit_counts(ref, hyp)
        edits += counts["substitutions"] + counts["deletions"] + counts["insertions"]
    return {"clips": len(ids), "edits": edits, "reference_words": len(refs),
            "wer": edits / len(refs) if refs else None,
            "targets": score.target_metrics(refs, hyps)}


def hall(device, ids, gated=False):
    items = []
    for clip_id in ids:
        r = by_device[device][clip_id]
        hyp = (r["guard_text"] or "") if gated else r["hypothesis"]["text"]
        items.append({"duration_s": r["measurements"]["audio_duration_s"], "hypothesis": hyp})
    return score.hallucination_metrics(items)


summary = {"corpus": str(pathlib.Path(r"C:\scratch\asr50\corpus_v2_frozen")),
           "clip_count": len(truth), "set_counts": dict(collections.Counter(
               c["set"] for c in truth_data["clips"])),
           "speech_clip_count": len(speech_ids), "silence_non_speech_count": len(hall_ids),
           "per_device": {}, "agreement": {}, "gate": {}}
for device in ("cpu", "dml"):
    summary["per_device"][device] = {
        "wer_speech_only": lexical(device, speech_ids),
        "wer_speech_by_set": {
            corpus_set: lexical(device, [c["clip_id"] for c in truth_data["clips"]
                                        if c["set"] == corpus_set
                                        and c["category"] not in ("silence", "non_speech")])
            for corpus_set in ("timing", "natural")
        },
        "targets_all_60": lexical(device, list(truth)),
        "silence_non_speech_default": hall(device, hall_ids),
        "hallucinations_by_category": {
            category: hall(device, ids) for category, ids in hall_by_category.items()
        },
        "chunked_clip_count": sum(by_device[device][c]["chunk_count"] > 1 for c in truth),
        "total_window_count": sum(by_device[device][c]["chunk_count"] for c in truth),
    }
    gate_eligible = [c for c in hall_ids if by_device[device][c]["guard"] is not None]
    summary["gate"][device] = {
        "eligible_clips": len(gate_eligible),
        "rms_skipped_clip_ids": [c for c in gate_eligible
                                 if by_device[device][c]["guard"]["skipped"]],
        "default": hall(device, gate_eligible),
        "gated": hall(device, gate_eligible, gated=True),
        "default_by_category": {
            category: hall(device, [c for c in ids if c in gate_eligible])
            for category, ids in hall_by_category.items()
        },
        "gated_by_category": {
            category: hall(device, [c for c in ids if c in gate_eligible], gated=True)
            for category, ids in hall_by_category.items()
        },
        "gated_target_metrics_all_60": lexical(device, list(truth), text_key="guard_text"),
    }
cpu, dml = by_device["cpu"], by_device["dml"]
diffs = [{"clip_id": clip_id, "cpu": cpu[clip_id]["hypothesis"]["text"],
          "dml": dml[clip_id]["hypothesis"]["text"]}
         for clip_id in truth if cpu[clip_id]["hypothesis"]["text"] != dml[clip_id]["hypothesis"]["text"]]
summary["agreement"] = {"identical_clip_count": len(truth) - len(diffs),
                        "total_clips": len(truth), "different_clip_count": len(diffs),
                        "different_clips": diffs}
out = path.parent / "score-summary.json"
out.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
print(out)
print(json.dumps(summary, indent=2, ensure_ascii=False))
