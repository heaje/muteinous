"""Aggregate per-engine ASR target survival and ASR-plus-context decisions."""
import json
from collections import defaultdict
from pathlib import Path

root = Path(r"C:\scratch\asr50\WP23")

def metrics(rows):
    tp = sum(int(r["label"]) == 1 and int(r["pred"]) == 1 for r in rows)
    tn = sum(int(r["label"]) == 0 and int(r["pred"]) == 0 for r in rows)
    fp = sum(int(r["label"]) == 0 and int(r["pred"]) == 1 for r in rows)
    fn = sum(int(r["label"]) == 1 and int(r["pred"]) == 0 for r in rows)
    n = len(rows)
    return {"n": n, "accuracy": (tp + tn) / n if n else None,
            "censor_precision": tp / (tp + fp) if tp + fp else None,
            "censor_recall": tp / (tp + fn) if tp + fn else None,
            "false_keep": fn, "false_censor": fp, "tp": tp, "tn": tn}

def run(engine, context_file):
    match = json.loads((root / "asr" / engine / "target_matches.json").read_text(encoding="utf-8"))
    combined_path = root / "context_winml17_cpu_asr_all.json"
    if combined_path.exists() and engine in ("parakeet-cpu", "whispercpp-vulkan"):
        decisions = [r for r in json.loads(combined_path.read_text(encoding="utf-8"))["results"]
                     if r.get("engine") == engine]
    else:
        decisions = json.loads((root / context_file).read_text(encoding="utf-8"))["results"]
    by_id = {r["clip_id"]: r for r in decisions}
    score = json.loads((root / "asr" / engine / "score.json").read_text(encoding="utf-8"))
    score_rows = score["rows"]
    survivors = {r["clip_id"] for r in score_rows if r["target_status"] in ("exact", "variant", "mangled")}
    labelled_censors = [r for r in score_rows if int(r["label"]) == 1]
    context_kept_or_censored = [r for r in labelled_censors if r["clip_id"] in by_id and int(by_id[r["clip_id"]]["pred"]) == 1]
    clean = [r for r in score_rows if r["condition"] == "clean"]
    clean_censors = [r for r in clean if int(r["label"]) == 1]
    clean_survivors = [r for r in clean_censors if r["clip_id"] in survivors]
    clean_e2e = [r for r in clean_censors if r["clip_id"] in by_id and int(by_id[r["clip_id"]]["pred"]) == 1]
    categorized = defaultdict(list)
    for r in decisions:
        categorized[r["category"]].append(r)
    bases = {}
    for key, pred in (("censor_all", 1), ("keep_all", 0)):
        bases[key] = metrics([{**r, "pred": pred} for r in decisions])
    category_bases = {}
    for category, rows in categorized.items():
        category_bases[category] = {
            key: metrics([{**r, "pred": pred} for r in rows])
            for key, pred in (("censor_all", 1), ("keep_all", 0))}
    return {"matched_decisions": len(decisions), "unmatched_target_cases": match["unmatched"],
            "decision_metrics": metrics(decisions),
            "per_category": {k: metrics(v) for k, v in sorted(categorized.items())},
            "decision_baselines": bases,
            "per_category_baselines": category_bases,
            "end_to_end_all_clips": {
                "labeled_censor_instances": len(labelled_censors),
                "asr_target_survived_exact_or_variant_or_mangled": len(survivors & {r["clip_id"] for r in labelled_censors}),
                "asr_only_censor_all_fraction": len(survivors & {r["clip_id"] for r in labelled_censors}) / max(1, len(labelled_censors)),
                "asr_plus_context_censored_instances": len(context_kept_or_censored),
                "asr_plus_context_fraction": len(context_kept_or_censored) / max(1, len(labelled_censors))},
            "end_to_end_clean_only": {
                "labeled_censor_instances": len(clean_censors),
                "asr_only_censor_all_fraction": len(clean_survivors) / max(1, len(clean_censors)),
                "asr_plus_context_censored_instances": len(clean_e2e),
                "asr_plus_context_fraction": len(clean_e2e) / max(1, len(clean_censors))}}

result = {}
for engine, context_file in (("parakeet-cpu", "context_parakeet_cpu.json"),
                             ("whispercpp-vulkan", "context_whispercpp_vulkan.json")):
    if (root / context_file).exists():
        result[engine] = run(engine, context_file)
(root / "asr_context_metrics.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n",
                                               encoding="utf-8")
print(json.dumps(result, ensure_ascii=False, indent=2))
