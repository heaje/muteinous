"""Central-normalization scores for raw and VAD-masked v3 Whisper outputs."""
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

gt_path = pathlib.Path(r"C:\scratch\asr50\corpus_v3_frozen\ground_truth_v3.json")
truth_rows = json.loads(gt_path.read_text(encoding="utf-8"))["clips"]
truth = {c["clip_id"]: c for c in truth_rows}
manifest = json.loads(pathlib.Path(
    r"C:\scratch\asr50\WP18\corpus_v3_vadmasked\manifest.json"
).read_text(encoding="utf-8"))["clips"]
flags = {pathlib.Path(c["input"]).stem: bool(c["gate_no_speech"]) for c in manifest}
speech_ids = [c["clip_id"] for c in truth_rows if not c["category"].startswith("non_speech_")]
non_speech_ids = [c["clip_id"] for c in truth_rows if c["category"].startswith("non_speech_")]
assert len(truth_rows) == 380 and len(speech_ids) == 340 and len(non_speech_ids) == 40

base = pathlib.Path(r"C:\scratch\asr50\results_v3\ort-whisper-turbo")
rows = {}
for corpus in ("raw", "masked"):
    rows[corpus] = {}
    for device in ("cpu", "dml"):
        rows[corpus][device] = {
            c["clip_id"]: json.loads((base / corpus / device / f"{c['clip_id']}.json")
                                     .read_text(encoding="utf-8"))
            for c in truth_rows
        }


def hypothesis(corpus, device, clip_id, gated=False):
    if gated and flags[clip_id]:
        return ""
    return rows[corpus][device][clip_id]["text"]


def lexical(corpus, device, ids, gated=False):
    substitutions = deletions = insertions = references = 0
    ref_all, hyp_all = [], []
    for clip_id in ids:
        ref = score.tokenize(truth[clip_id]["transcript"])
        hyp = score.tokenize(hypothesis(corpus, device, clip_id, gated))
        result = score.edit_counts(ref, hyp)
        substitutions += result["substitutions"]
        deletions += result["deletions"]
        insertions += result["insertions"]
        references += len(ref)
        ref_all.extend(ref)
        hyp_all.extend(hyp)
    return {
        "clips": len(ids), "reference_words": references,
        "substitutions": substitutions, "deletions": deletions, "insertions": insertions,
        "edit_count": substitutions + deletions + insertions,
        "wer": (substitutions + deletions + insertions) / references if references else None,
        "targets": score.target_metrics(ref_all, hyp_all),
    }


def hallucinations(corpus, device, gated=False):
    items = [{"duration_s": truth[c]["duration_s"],
              "hypothesis": hypothesis(corpus, device, c, gated)}
             for c in non_speech_ids]
    result = score.hallucination_metrics(items)
    result["clips_with_output"] = round(result.pop("clips_with_output_fraction") * len(items))
    result["clips_total"] = len(items)
    return result


def agreement(corpus, gated=False):
    differing = []
    for clip_id in truth:
        cpu = hypothesis(corpus, "cpu", clip_id, gated)
        dml = hypothesis(corpus, "dml", clip_id, gated)
        if cpu != dml:
            differing.append({"clip_id": clip_id, "cpu": cpu, "dml": dml})
    return {"identical_clips": len(truth) - len(differing), "total_clips": len(truth),
            "differing_clips": len(differing), "first_differences": differing[:10]}


summary = {
    "corpus": "corpus_v3_frozen",
    "clip_count": len(truth), "speech_clip_count": len(speech_ids),
    "non_speech_clip_count": len(non_speech_ids), "gate_flagged_count": sum(flags.values()),
    "gate_flagged_speech": [c for c in speech_ids if flags[c]],
    "normalization": {
        "tokenizer": "spike/asr50/benchmark/score.py tokenize (NFKC, casefold, Unicode word tokens)",
        "wer": "score.py deterministic Levenshtein edit counts; speech clips only",
        "targets": "score.py target_metrics for banana/cobalt/harbor; all 380 clips",
        "hallucinations": "score.py hallucination_metrics over 40 non-speech clips",
    },
    "condition_counts": dict(collections.Counter(c["condition"] for c in truth_rows)),
    "per_corpus_device": {},
    "agreement": {},
}
for corpus in ("raw", "masked"):
    summary["per_corpus_device"][corpus] = {}
    for device in ("cpu", "dml"):
        by_condition = {}
        conditions = sorted({c["condition"] for c in truth_rows})
        for condition in conditions:
            ids = [c["clip_id"] for c in truth_rows
                   if c["condition"] == condition and not c["category"].startswith("non_speech_")]
            by_condition[condition] = lexical(corpus, device, ids)
        by_voice = {}
        for voice in sorted({c["voice"] for c in truth_rows}, key=lambda v: str(v)):
            ids = [c["clip_id"] for c in truth_rows
                   if c["voice"] == voice and not c["category"].startswith("non_speech_")]
            if len(ids) >= 3:
                by_voice[str(voice)] = lexical(corpus, device, ids)
        by_rate = {}
        for rate in sorted({c["rate"] for c in truth_rows}, key=lambda v: str(v)):
            ids = [c["clip_id"] for c in truth_rows
                   if c["rate"] == rate and not c["category"].startswith("non_speech_")]
            if len(ids) >= 3:
                by_rate[str(rate)] = lexical(corpus, device, ids)
        summary["per_corpus_device"][corpus][device] = {
            "default": {
                "speech_wer": lexical(corpus, device, speech_ids),
                "speech_wer_by_condition": by_condition,
                "speech_wer_by_voice": by_voice,
                "speech_wer_by_rate": by_rate,
                "target_metrics_all_clips": lexical(corpus, device, list(truth))["targets"],
                "target_metrics_speech_only": lexical(corpus, device, speech_ids)["targets"],
                "non_speech_hallucinations": hallucinations(corpus, device),
            }
        }
        if corpus == "masked":
            summary["per_corpus_device"][corpus][device]["gated_skip"] = {
                "speech_wer": lexical(corpus, device, speech_ids, gated=True),
                "target_metrics_all_clips": lexical(corpus, device, list(truth), gated=True)["targets"],
                "target_metrics_speech_only": lexical(corpus, device, speech_ids, gated=True)["targets"],
                "non_speech_hallucinations": hallucinations(corpus, device, gated=True),
            }
    summary["agreement"][corpus] = agreement(corpus)
summary["agreement"]["masked_gated_skip"] = agreement("masked", gated=True)
out = base / "score-summary.json"
out.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
print(out)
print(json.dumps(summary, indent=2, ensure_ascii=False))
