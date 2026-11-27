"""Compare raw v2, energy-gate, masked v2, and manifest-gated skip hypotheses."""
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
gt = json.loads(pathlib.Path(
    r"C:\scratch\asr50\corpus_v2_frozen\ground_truth_v2.json").read_text(encoding="utf-8"))["clips"]
truth = {x["clip_id"]: x for x in gt}
masked_data = json.loads(pathlib.Path(
    r"C:\scratch\asr50\WP18\corpus_v2_vadmasked\manifest.json").read_text(encoding="utf-8"))["clips"]
flags = {x["clip_id"]: bool(x["gate_no_speech"]) for x in masked_data}
speech = [c["clip_id"] for c in gt if c["category"] not in ("silence", "non_speech")]
non_speech = [c["clip_id"] for c in gt if c["category"] == "non_speech"]
silence = [c["clip_id"] for c in gt if c["category"] == "silence"]
hall_ids = silence + non_speech


def load(path):
    return [json.loads(line) for line in pathlib.Path(path).read_text(encoding="utf-8").splitlines() if line]


raw_rows = load(r"C:\scratch\asr50\results_v2\ort-whisper-turbo\results.jsonl")
masked_rows = load(r"C:\scratch\asr50\results_v2_vadmasked\ort-whisper-turbo\results.jsonl")
raw = {d: {r["clip_id"]: r for r in raw_rows if r["device"]["requested"] == d}
       for d in ("cpu", "dml")}
masked = {d: {r["clip_id"]: r for r in masked_rows if r["device"]["requested"] == d}
          for d in ("cpu", "dml")}


def get_hyp(device, clip_id, mode):
    if mode == "unmasked_default":
        return raw[device][clip_id]["hypothesis"]["text"]
    if mode == "energy_gate":
        r = raw[device][clip_id]
        return r["guard_text"] if r["guard"] is not None else r["hypothesis"]["text"]
    r = masked[device][clip_id]
    if mode == "masked_vad_skip" and flags[clip_id]:
        return ""
    return r["hypothesis"]["text"]


def lexical(device, ids, mode):
    refs = hyps = edits = substitutions = deletions = insertions = 0
    ref_tokens, hyp_tokens = [], []
    for clip_id in ids:
        reference = score.tokenize(truth[clip_id]["transcript"])
        hypothesis = score.tokenize(get_hyp(device, clip_id, mode))
        c = score.edit_counts(reference, hypothesis)
        edits += c["substitutions"] + c["deletions"] + c["insertions"]
        substitutions += c["substitutions"]
        deletions += c["deletions"]
        insertions += c["insertions"]
        refs += len(reference)
        ref_tokens.extend(reference)
        hyp_tokens.extend(hypothesis)
    targets = score.target_metrics(ref_tokens, hyp_tokens)
    return {"clips": len(ids), "reference_words": refs, "substitutions": substitutions,
            "deletions": deletions, "insertions": insertions, "edit_count": edits,
            "wer": edits / refs if refs else None, "targets": targets}


def hallucinations(device, ids, mode):
    clips = [{"duration_s": truth[c]["duration_s"], "hypothesis": get_hyp(device, c, mode)}
             for c in ids]
    return score.hallucination_metrics(clips)


modes = ("unmasked_default", "energy_gate", "masked_all", "masked_vad_skip")
summary = {"clip_count": len(truth), "gate_flagged": sum(flags.values()),
           "flagged_speech": [c for c in speech if flags[c]], "per_device": {}, "agreement": {}}
for device in ("cpu", "dml"):
    summary["per_device"][device] = {}
    for mode in modes:
        summary["per_device"][device][mode] = {
            "speech_wer": lexical(device, speech, mode),
            "targets_all_60": lexical(device, list(truth), mode)["targets"],
            "silence": hallucinations(device, silence, mode),
            "non_speech": hallucinations(device, non_speech, mode),
            "silence_non_speech_combined": hallucinations(device, hall_ids, mode),
        }
    clip_id = "timing_noise_pink_-5_01"
    summary["per_device"][device]["flagged_real_speech_clip"] = {
        "clip_id": clip_id, "reference": truth[clip_id]["transcript"],
        "masked_default": get_hyp(device, clip_id, "masked_all"),
        "gated_skip": get_hyp(device, clip_id, "masked_vad_skip"),
        "skip_edit_counts": score.edit_counts(score.tokenize(truth[clip_id]["transcript"]), []),
    }
diffs = [{"clip_id": c, "cpu": get_hyp("cpu", c, "masked_all"),
          "dml": get_hyp("dml", c, "masked_all")}
         for c in truth if get_hyp("cpu", c, "masked_all") != get_hyp("dml", c, "masked_all")]
summary["agreement"] = {"identical": len(truth) - len(diffs), "total": len(truth),
                        "different": len(diffs), "different_clips": diffs}
out = pathlib.Path(r"C:\scratch\asr50\results_v2_vadmasked\ort-whisper-turbo\score-summary.json")
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
print(out)
print(json.dumps(summary, indent=2, ensure_ascii=False))
