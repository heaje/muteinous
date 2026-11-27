"""Summarize the exact Windows GenAI WinML 0.17.1 context run."""
import json
from collections import defaultdict
from pathlib import Path

root = Path(r"C:\scratch\asr50\WP23")
run = json.loads((root / "context_winml17_cpu_all.json").read_text(encoding="utf-8"))
rows = run["results"]

def metrics(items):
    tp = sum(int(r["label"]) == 1 and int(r["pred"]) == 1 for r in items)
    tn = sum(int(r["label"]) == 0 and int(r["pred"]) == 0 for r in items)
    fp = sum(int(r["label"]) == 0 and int(r["pred"]) == 1 for r in items)
    fn = sum(int(r["label"]) == 1 and int(r["pred"]) == 0 for r in items)
    n = len(items)
    return {"n": n, "accuracy": (tp + tn) / n if n else None,
            "precision": tp / (tp + fp) if tp + fp else None,
            "recall": tp / (tp + fn) if tp + fn else None,
            "false_keep": fn, "false_censor": fp, "tp": tp, "tn": tn}

def category_tables(items):
    grouped = defaultdict(list)
    for row in items:
        grouped[row["category"]].append(row)
    baseline = {cat: {
        name: metrics([{**r, "pred": pred} for r in subset])
        for name, pred in (("censor_all", 1), ("keep_all", 0))}
        for cat, subset in grouped.items()}
    return {k: metrics(v) for k, v in sorted(grouped.items())}, baseline

authored = [r for r in rows if "group" in r]
hush_synthetic = [r for r in rows if "group" not in r and "language" not in r]
multilingual = [r for r in rows if "language" in r]
summary = {}
for name, items in (("authored", authored), ("hushpatch_synthetic", hush_synthetic),
                    ("multilingual", multilingual)):
    cats, bases = category_tables(items)
    summary[name] = {"metrics": metrics(items), "by_category": cats,
                     "category_baselines": bases,
                     "false_rows": [{"text": r["sentence"], "target": r["target_word"],
                                     "label": r["label"], "pred": r["pred"],
                                     "category": r["category"]}
                                    for r in items if r["label"] != r["pred"]]}
    if name == "multilingual":
        summary[name]["by_language"] = {
            lang: metrics([r for r in items if r["language"] == lang])
            for lang in sorted({r["language"] for r in items})}

# Compare exact decision agreement with the newer CPU GenAI runtime.
newer = json.loads((root / "context_cpu_authored.json").read_text(encoding="utf-8"))["results"]
new_by = {(r["sentence"], r["target_word"], r["category"]): r["pred"] for r in newer}
summary["authored"]["agreement_with_genai_0_20"] = sum(
    int(r["pred"]) == int(new_by.get((r["sentence"], r["target_word"], r["category"]), -1))
    for r in authored) / max(1, len(authored))

(root / "context_winml17_metrics.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
                                                   encoding="utf-8")
print(json.dumps({k: v["metrics"] for k, v in summary.items()}, ensure_ascii=False, indent=2))
