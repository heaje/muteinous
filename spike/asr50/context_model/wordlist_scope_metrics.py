"""Measure results on Hushpatch word-list candidates without copying the list."""
import json
import tomllib
from collections import defaultdict
from pathlib import Path

root = Path(r"C:\scratch\asr50\WP23")
source_list = Path(r"C:\code\hushpatch\src\muteinous\data\wordlist.toml")
entries = tomllib.loads(source_list.read_text(encoding="utf-8")).get("word", [])
lookup = {}
for entry in entries:
    for form in (entry["text"], *entry.get("forms", [])):
        lookup[form.casefold()] = entry

def metrics(rows):
    tp = sum(int(r["label"]) == 1 and int(r["pred"]) == 1 for r in rows)
    tn = sum(int(r["label"]) == 0 and int(r["pred"]) == 0 for r in rows)
    fp = sum(int(r["label"]) == 0 and int(r["pred"]) == 1 for r in rows)
    fn = sum(int(r["label"]) == 1 and int(r["pred"]) == 0 for r in rows)
    n = len(rows)
    return {"n": n, "accuracy": (tp + tn) / n if n else None,
            "precision": tp / (tp + fp) if tp + fp else None,
            "recall": tp / (tp + fn) if tp + fn else None,
            "false_keep": fn, "false_censor": fp}

def views(rows, target_key):
    candidate = [r for r in rows if r[target_key].casefold() in lookup]
    ambiguous = [r for r in candidate if lookup[r[target_key].casefold()].get("ambiguous", False)]
    return {"all": metrics(rows), "wordlist_candidate": metrics(candidate),
            "wordlist_ambiguous": metrics(ambiguous),
            "candidate_by_category": {cat: metrics([r for r in candidate if r["category"] == cat])
                                      for cat in sorted({r["category"] for r in candidate})},
            "ambiguous_by_category": {cat: metrics([r for r in ambiguous if r["category"] == cat])
                                     for cat in sorted({r["category"] for r in ambiguous})}}

run = json.loads((root / "context_winml17_cpu_all.json").read_text(encoding="utf-8"))
result = {"authored": views([r for r in run["results"] if "group" in r], "target_word")}
asr_path = root / "context_winml17_cpu_asr_all.json"
if asr_path.exists():
    asr_results = json.loads(asr_path.read_text(encoding="utf-8"))["results"]
    result["asr"] = {engine: views([r for r in asr_results if r.get("engine") == engine],
                                   "source_target")
                     for engine in ("parakeet-cpu", "whispercpp-vulkan", "ort-dml20")}
(root / "wordlist_scope_metrics.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n",
                                                  encoding="utf-8")
print(json.dumps(result, ensure_ascii=False, indent=2))
