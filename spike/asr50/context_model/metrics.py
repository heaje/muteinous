"""Summarize WP23 labels and context predictions without external scoring assets."""
import json
from collections import defaultdict
from pathlib import Path

root = Path(r"C:\scratch\asr50\WP23")

def score(rows):
    labels = [int(x["label"]) for x in rows]
    preds = [int(x["pred"]) for x in rows]
    tp = sum(y == 1 and p == 1 for y, p in zip(labels, preds))
    tn = sum(y == 0 and p == 0 for y, p in zip(labels, preds))
    fp = sum(y == 0 and p == 1 for y, p in zip(labels, preds))
    fn = sum(y == 1 and p == 0 for y, p in zip(labels, preds))
    return {"n": len(rows), "accuracy": (tp + tn) / len(rows) if rows else None,
            "censor_precision": tp / (tp + fp) if tp + fp else None,
            "censor_recall": tp / (tp + fn) if tp + fn else None,
            "false_keep": fn, "false_censor": fp, "tp": tp, "tn": tn}

def dataset(path):
    data = json.loads(path.read_text(encoding="utf-8"))
    rows = data["results"]
    output = {"device": data["device"], "runtime_version": data["runtime_version"],
              "load_s": data["load_s"], "median_decision_s": data["median_s"],
              "p95_decision_s": data["p95_s"], "context": score(rows)}
    by_category = defaultdict(list)
    for row in rows:
        by_category[row["category"]].append(row)
    output["categories"] = {key: score(value) for key, value in sorted(by_category.items())}
    output["baselines"] = {}
    for name, pred in (("censor_all", 1), ("keep_all", 0)):
        output["baselines"][name] = score([{**row, "pred": pred} for row in rows])
    output["failures"] = [{"sentence": r["sentence"], "target": r["target_word"],
                           "category": r["category"], "label": r["label"],
                           "pred": r["pred"], "p_yes": r["p_yes"]}
                          for r in rows if int(r["label"]) != int(r["pred"])]
    return output

all_data = {}
for name, file in (("authored", "context_cpu_authored.json"),
                   ("hushpatch_synthetic", "context_cpu_hush_synthetic.json"),
                   ("multilingual", "context_cpu_multilingual.json")):
    path = root / file
    if path.exists():
        all_data[name] = dataset(path)
(root / "context_metrics.json").write_text(json.dumps(all_data, ensure_ascii=False, indent=2) + "\n",
                                            encoding="utf-8")
print(json.dumps({k: v["context"] for k, v in all_data.items()}, indent=2))
