"""Compare unmasked, VAD-masked ASR, and VAD-gated skip over corpus v2."""
import importlib.util
import json
import math
import pathlib
import statistics
import sys

BENCH = pathlib.Path(r"C:\code\muteinous-spike50\spike\asr50\benchmark")
GT_PATH = pathlib.Path(r"C:\scratch\asr50\corpus_v2_frozen\ground_truth_v2.json")
MANIFEST_PATH = pathlib.Path(r"C:\scratch\asr50\WP18\corpus_v2_vadmasked\manifest.json")
BASE = pathlib.Path(r"C:\scratch\asr50\results_v2\sherpa-parakeet\cpu")
MASKED = pathlib.Path(r"C:\scratch\asr50\results_v2_vadmasked\sherpa-parakeet\cpu")
OUTPUT = MASKED.parent

spec = importlib.util.spec_from_file_location("score", BENCH / "score.py")
score = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = score
spec.loader.exec_module(score)


def summarise(values):
    return {
        "mean_ms": statistics.mean(values) if values else None,
        "median_ms": statistics.median(values) if values else None,
        "p95_ms": score.percentile_nearest_rank(values, .95),
        "within_ms": {
            str(t): sum(v <= t for v in values) / len(values) if values else None
            for t in (50, 100, 200)
        },
    }


def metrics(view_name, items):
    # items: (clip metadata, output dict, gate flag)
    speech = [(c, o) for c, o, _ in items
              if c["category"] not in ("silence", "non_speech")]
    edit = [score.edit_counts(score.tokenize(c["transcript"]),
                              score.tokenize(o["text"])) for c, o in speech]
    subs = sum(e["substitutions"] for e in edit)
    dels = sum(e["deletions"] for e in edit)
    ins = sum(e["insertions"] for e in edit)
    refs = sum(len(score.tokenize(c["transcript"])) for c, _ in speech)
    wer = (subs + dels + ins) / refs if refs else None

    target = {"true_positives": 0, "false_positives": 0, "false_negatives": 0}
    for clip, output, _ in items:
        m = score.target_metrics(clip["transcript"], output["text"])
        for k in target:
            target[k] += m[k]
    tp, fp, fn = target["true_positives"], target["false_positives"], target["false_negatives"]
    precision = tp / (tp + fp) if tp + fp else (1.0 if not fn else 0.0)
    recall = tp / (tp + fn) if tp + fn else (1.0 if not fp else 0.0)
    target.update(precision=precision, recall=recall,
                  f1=2 * precision * recall / (precision + recall)
                  if precision + recall else 0.0)
    negative = [
        {"duration_s": c["duration_s"], "hypothesis": o["text"]}
        for c, o, _ in items if c["category"] in ("silence", "non_speech")
    ]
    hallucination = score.hallucination_metrics(negative)

    timing_clip_results = {}
    starts, ends_next, ends_duration = [], [], []
    matched = hyp_count = missing = 0
    for clip, output, _ in items:
        if clip["set"] != "timing":
            continue
        reference = [
            {"text": w["text"],
             "start_s": w["start_sample"] / 16000,
             "end_s": w["end_sample"] / 16000}
            for w in clip["words"]
        ]
        primary = [{"text": w["word"], "start_s": w["start"], "end_s": w["end"]}
                   for w in output["words"]]
        alt = [{"text": w["word"], "start_s": w["start"], "end_s": w["end"]}
               for w in output["words_duration_end"]]
        pairs = score.matched_word_pairs(reference, primary)
        pmetrics = score.timing_metrics(reference, primary, matches=pairs)
        ametrics = score.timing_metrics(reference, alt, matches=pairs)
        timing_clip_results[clip["clip_id"]] = {
            "matched_word_pairs": len(pairs),
            "next_word_start": pmetrics,
            "last_token_start_plus_duration": ametrics,
        }
        hyp_count += len(primary)
        missing += pmetrics["missing_alignment_words"]
        for ri, hi in pairs:
            r, p, a = reference[ri], primary[hi], alt[hi]
            vals = (r["start_s"], r["end_s"], p.get("start_s"),
                    p.get("end_s"), a.get("end_s"))
            if all(isinstance(x, (int, float)) and math.isfinite(x) for x in vals):
                matched += 1
                starts.append(abs(vals[0] - vals[2]) * 1000)
                ends_next.append(abs(vals[1] - vals[3]) * 1000)
                ends_duration.append(abs(vals[1] - vals[4]) * 1000)
    timing = {
        "timing_clip_count": len(timing_clip_results),
        "matched_word_pairs": matched,
        "hypothesized_words": hyp_count,
        "missing_alignment_words": missing,
        "missing_alignment_rate": missing / hyp_count if hyp_count else 0.0,
        "start_error": summarise(starts),
        "end_error_next_word_start": summarise(ends_next),
        "end_error_last_token_start_plus_duration": summarise(ends_duration),
        "per_clip": timing_clip_results,
    }
    return {
        "view": view_name,
        "speech_clips": len(speech), "speech_reference_words": refs,
        "wer": wer, "substitutions": subs, "deletions": dels, "insertions": ins,
        "target_words_all_clips": target,
        "silence_non_speech_hallucinations": hallucination,
        "timing": timing,
    }


def main():
    truth = json.loads(GT_PATH.read_text(encoding="utf-8"))
    clips = truth["clips"]
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    gate = {c["clip_id"]: c["gate_no_speech"] for c in manifest["clips"]}
    if len(gate) != 60 or sum(gate.values()) != 20:
        raise ValueError("Unexpected VAD manifest gate count")
    base_items, masked_items, gated_items = [], [], []
    clip_transcripts = {}
    for clip in clips:
        cid = clip["clip_id"]
        base = json.loads((BASE / f"{cid}.json").read_text(encoding="utf-8"))
        masked = json.loads((MASKED / f"{cid}.json").read_text(encoding="utf-8"))
        if masked["gate_no_speech"] != gate[cid]:
            raise ValueError(f"gate flag mismatch for {cid}")
        if masked["clip_set"] != clip["set"] or base["clip_set"] != clip["set"]:
            raise ValueError(f"clip_set mismatch for {cid}")
        base_view = {"text": base["text"], "words": base["words"],
                     "words_duration_end": base["words_duration_end"]}
        masked_view = {"text": masked["text"], "words": masked["words"],
                       "words_duration_end": masked["words_duration_end"]}
        if gate[cid]:
            skipped_view = {"text": "", "words": [], "words_duration_end": []}
        else:
            skipped_view = masked_view
        base_items.append((clip, base_view, gate[cid]))
        masked_items.append((clip, masked_view, gate[cid]))
        gated_items.append((clip, skipped_view, gate[cid]))
        clip_transcripts[cid] = {
            "clip_set": clip["set"], "category": clip["category"],
            "gate_no_speech": gate[cid], "reference": clip["transcript"],
            "unmasked": base["text"], "masked_run": masked["text"],
            "gated_skip": skipped_view["text"],
        }
    summaries = [
        metrics("unmasked-v2", base_items),
        metrics("masked-run", masked_items),
        metrics("gated-skip", gated_items),
    ]
    output = {
        "candidate": "sherpa-parakeet",
        "corpus": "WP18 corpus-v2 VAD-masked; timeline-preserved",
        "gate_no_speech_count": sum(gate.values()),
        "gate_false_negative_real_speech": ["timing_noise_pink_-5_01"],
        "passed_non_speech_example": "nonspeech_pink_noise_30s",
        "views": summaries,
        "clip_results": clip_transcripts,
    }
    (OUTPUT / "score-comparison.json").write_text(
        json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    compact = {}
    for summary in summaries:
        compact[summary["view"]] = {
            k: summary[k] for k in (
                "wer", "substitutions", "deletions", "insertions",
                "target_words_all_clips", "silence_non_speech_hallucinations")
        }
        compact[summary["view"]]["timing"] = {
            k: v for k, v in summary["timing"].items() if k != "per_clip"
        }
    print(json.dumps(compact, indent=2))


if __name__ == "__main__":
    main()
