"""Score normalized ORT runner result records with the project benchmark scorer."""
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
truth = {c["clip_id"]: c for c in json.loads(
    pathlib.Path(r"C:\scratch\asr50\WP6\audio16k\ground_truth.json").read_text(encoding="utf-8"))["clips"]}
records = [json.loads(s) for s in pathlib.Path(
    r"C:\scratch\asr50\results\ort-whisper-turbo\results.jsonl").read_text(encoding="utf-8").splitlines() if s]
# Select one deterministic, complete 14-clip pass per device for headline scoring.
records = [r for r in records if
           (r["device"]["requested"] == "cpu" and r["settings"]["threads"] == 12
            and r["run"]["kind"] == "cold" and r["run"]["index"] == 0)
           or (r["device"]["requested"] == "dml" and r["run"]["kind"] == "functional"
               and r["run"]["index"] == 0)]
groups = collections.defaultdict(list)
for r in records:
    key = (r["device"]["requested"], r["settings"]["threads"], r["run"]["kind"], r["run"]["index"])
    groups[key].append(r)
summary = {}
for key, rows in sorted(groups.items()):
    ws, rs, hs, silence = [], [], [], []
    for r in rows:
        ref = truth[r["clip_id"]]
        h = r["hypothesis"]["text"]
        counts = score.edit_counts(score.tokenize(ref["transcript"]), score.tokenize(h))
        ws.append(counts)
        rs.extend(ref["words"])
        hs.extend({"text": x, "start_s": None, "end_s": None} for x in score.tokenize(h))
        if ref["category"] in ("silence", "non_speech"):
            silence.append({"duration_s": r["measurements"]["audio_duration_s"], "hypothesis": h})
    ref_n = sum(len(score.tokenize(truth[r["clip_id"]]["transcript"])) for r in rows)
    edits = sum(x["substitutions"] + x["deletions"] + x["insertions"] for x in ws)
    target = score.target_metrics(
        [x for r in rows for x in score.tokenize(truth[r["clip_id"]]["transcript"])],
        [x for r in rows for x in score.tokenize(r["hypothesis"]["text"])])
    summary["/".join(map(str, key))] = {
        "clips": len(rows), "wer": edits / ref_n if ref_n else None, "edit_count": edits,
        "reference_words": ref_n, "target_words": target,
        "timing": score.timing_metrics(rs, hs),
        "silence_non_speech": score.hallucination_metrics(silence),
        "audio_seconds": sum(r["measurements"]["audio_duration_s"] for r in rows),
        "inference_seconds": sum(r["measurements"]["runtime_s"] for r in rows),
        "rtf": (sum(r["measurements"]["runtime_s"] for r in rows) /
                sum(r["measurements"]["audio_duration_s"] for r in rows)) if rows else None,
    }
out = pathlib.Path(r"C:\scratch\asr50\results\ort-whisper-turbo\score-summary.json")
out.write_text(json.dumps(summary, indent=2), encoding="utf-8")
print(out)
print(json.dumps(summary, indent=2))
