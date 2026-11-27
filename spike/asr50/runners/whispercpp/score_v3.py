"""Central, deterministic scorer for the raw and VAD-masked corpus-v3 runs."""
from __future__ import annotations

import importlib.util
import json
from collections import defaultdict
from pathlib import Path

import benchmark_v2 as base

ROOT = base.ROOT
OUT = ROOT / "results_v3" / "whispercpp"
GT_PATH = ROOT / "corpus_v3_frozen" / "ground_truth_v3.json"
SCORE_PATH = base.SCORE_PATH
TARGETS = ("banana", "cobalt", "harbor")
DISTRACTORS = ("cobol", "arbor", "bandana")


def metric_row(ref_text: str, hyp_text: str, score) -> dict:
    edit = score.edit_counts(score.tokenize(ref_text), score.tokenize(hyp_text))
    return {key: edit[key] for key in ("substitutions", "deletions", "insertions")}


def lexical_summary(rows: list[dict], clips_by_id: dict, score) -> dict:
    speech = [r for r in rows if clips_by_id[r["clip_id"]]["transcript"]]
    substitutions = deletions = insertions = references = 0
    for row in speech:
        ref = clips_by_id[row["clip_id"]]["transcript"]
        hyp = row["hypothesis_text"]
        ops = metric_row(ref, hyp, score)
        substitutions += ops["substitutions"]
        deletions += ops["deletions"]
        insertions += ops["insertions"]
        references += len(score.tokenize(ref))

    def subset_metrics(subset):
        s = d = i = n = 0
        for row in subset:
            ref = clips_by_id[row["clip_id"]]["transcript"]
            ops = metric_row(ref, row["hypothesis_text"], score)
            s += ops["substitutions"]
            d += ops["deletions"]
            i += ops["insertions"]
            n += len(score.tokenize(ref))
        return {"clips": len(subset), "S": s, "D": d, "I": i,
                "WER": (s + d + i) / n if n else None}

    def target_set_summary(targets):
        counts = [score.target_metrics(
            clips_by_id[row["clip_id"]]["transcript"], row["hypothesis_text"], targets
        ) for row in rows]
        tp = sum(x["true_positives"] for x in counts)
        fp = sum(x["false_positives"] for x in counts)
        fn = sum(x["false_negatives"] for x in counts)
        return {
            "true_positives": tp, "false_positives": fp, "false_negatives": fn,
            "precision": tp / (tp + fp) if tp + fp else (1.0 if not fn else 0.0),
            "recall": tp / (tp + fn) if tp + fn else (1.0 if not fp else 0.0),
        }

    def per_word_summary(words):
        return {
            word: target_set_summary((word,))
            for word in words
        }

    non = [{
        "duration_s": float(clips_by_id[r["clip_id"]]["duration_s"]),
        "hypothesis": r["hypothesis_text"],
    } for r in rows if not clips_by_id[r["clip_id"]]["transcript"]]

    conditions = {}
    by_condition = defaultdict(list)
    for row in speech:
        by_condition[clips_by_id[row["clip_id"]]["condition"]].append(row)
    for condition, subset in sorted(by_condition.items()):
        conditions[condition] = subset_metrics(subset)

    clean = [r for r in speech if clips_by_id[r["clip_id"]]["condition"] == "clean"]
    by_voice, by_rate = defaultdict(list), defaultdict(list)
    for row in clean:
        clip = clips_by_id[row["clip_id"]]
        by_voice[clip["voice"]].append(row)
        by_rate[str(clip["rate"])].append(row)
    voice_metrics = {voice: subset_metrics(subset) for voice, subset in sorted(by_voice.items())
                     if len(subset) >= 10}
    rate_metrics = {rate: subset_metrics(subset) for rate, subset in sorted(by_rate.items(),
                                                                            key=lambda x: int(x[0]))
                    if len(subset) >= 10}

    return {
        "clips": len(rows), "speech_clips": len(speech),
        "WER": (substitutions + deletions + insertions) / references if references else None,
        "S": substitutions, "D": deletions, "I": insertions,
        "by_condition": conditions,
        "clean_by_voice": voice_metrics,
        "clean_by_rate": rate_metrics,
        "target_words": target_set_summary(TARGETS),
        "target_word_details": per_word_summary(TARGETS),
        "distractors": target_set_summary(DISTRACTORS),
        "distractor_details": per_word_summary(DISTRACTORS),
        "non_speech_hallucination": score.hallucination_metrics(non),
        "non_speech_clips": len(non),
    }


def main():
    gt = json.loads(GT_PATH.read_text(encoding="utf-8"))
    clips_by_id = {c["clip_id"]: c for c in gt["clips"]}
    observations = list(map(json.loads, (OUT / "results.jsonl").read_text(
        encoding="utf-8").splitlines()))
    if len(observations) != 3040:
        raise SystemExit(f"expected 3040 v3 observations, got {len(observations)}")
    spec = importlib.util.spec_from_file_location("score_v3_canonical", SCORE_PATH)
    score = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(score)

    summary = {}
    for model in ("turbo", "small.en"):
        for device in ("vulkan", "cpu"):
            for corpus in ("raw", "masked"):
                chosen = [r for r in observations
                          if r["candidate"] == f"whispercpp-v3-{corpus}-{model}-full"
                          and r["device"]["requested"] == device]
                views = {"raw": chosen} if corpus == "raw" else {
                    "masked-run": chosen,
                    "gated-skip": [
                        {**r, "hypothesis_text": ("" if r["gate_no_speech"]
                                                 else r["hypothesis"]["text"])}
                        for r in chosen
                    ],
                }
                for view, selected in views.items():
                    shaped = [{**r, "hypothesis_text": r["hypothesis"]["text"]}
                              if "hypothesis_text" not in r else r for r in selected]
                    summary[f"{corpus}/{model}/{device}/{view}"] = lexical_summary(
                        shaped, clips_by_id, score)

    agreements = {}
    for corpus in ("raw", "masked"):
        for model in ("turbo", "small.en"):
            for view in (("raw",) if corpus == "raw" else ("masked-run", "gated-skip")):
                diff = []
                compared = 0
                for clip in gt["clips"]:
                    gpu = next(r for r in observations if
                               r["candidate"] == f"whispercpp-v3-{corpus}-{model}-full"
                               and r["device"]["requested"] == "vulkan"
                               and r["clip_id"] == clip["clip_id"])
                    cpu = next(r for r in observations if
                               r["candidate"] == f"whispercpp-v3-{corpus}-{model}-full"
                               and r["device"]["requested"] == "cpu"
                               and r["clip_id"] == clip["clip_id"])
                    gtext = gpu["hypothesis"]["text"]
                    ctext = cpu["hypothesis"]["text"]
                    if view == "gated-skip":
                        if gpu["gate_no_speech"]:
                            gtext = ""
                        if cpu["gate_no_speech"]:
                            ctext = ""
                    compared += 1
                    if score.tokenize(gtext) != score.tokenize(ctext):
                        diff.append(clip["clip_id"])
                agreements[f"{corpus}/{model}/{view}"] = {
                    "compared_clips": compared,
                    "differing_clips": len(diff),
                    "identical_clips": compared - len(diff),
                    "differing_clip_ids": diff,
                }
    report = {"normalization": "benchmark.score.tokenize: NFKC, casefold, punctuation tokenization",
              "target_words": list(TARGETS), "distractors": list(DISTRACTORS),
              "metrics": summary, "gpu_cpu_text_agreement": agreements}
    (OUT / "score-summary.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"Scored {len(observations)} v3 observations -> {OUT / 'score-summary.json'}")


if __name__ == "__main__":
    main()
