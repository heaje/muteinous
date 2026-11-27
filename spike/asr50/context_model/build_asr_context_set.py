"""Locate labeled targets in each ASR transcript using normalized edit distance."""
import json
import re
import argparse
from pathlib import Path

root = Path(r"C:\scratch\asr50\WP23")
parser = argparse.ArgumentParser()
parser.add_argument("--engine", choices=("whispercpp-vulkan", "parakeet-cpu"), required=True)
args = parser.parse_args()
audio = root / "corpus" / "audio16k_v3"
clips = json.loads((audio / "ground_truth_v3.json").read_text(encoding="utf-8"))["clips"]
labels = json.loads((root / "labels" / "wp23_authored.json").read_text(encoding="utf-8"))
label_by_text = {r["sentence"]: r for r in labels}
outputs = json.loads((root / "asr" / args.engine / "outputs.json").read_text(encoding="utf-8"))
output_by_id = {r["clip_id"]: r for r in outputs}

def edit(a, b):
    row = list(range(len(b) + 1))
    for i, x in enumerate(a, 1):
        nxt = [i]
        for j, y in enumerate(b, 1):
            nxt.append(min(nxt[-1] + 1, row[j] + 1, row[j - 1] + (x != y)))
        row = nxt
    return row[-1]

cases, misses = [], []
for clip in clips:
    label = label_by_text.get(clip["transcript"])
    if not label:
        continue
    out = output_by_id.get(clip["clip_id"], {})
    hyp = out.get("text", "")
    tokens = list(re.finditer(r"[^\W_]+(?:'[^\W_]+)*", hyp, re.UNICODE))
    target = label["target_word"].casefold()
    # Exact/inflection-aware nearest token, with edit distance <=1 as mangled.
    def norm(token):
        t = token.casefold()
        for suffix in ("ing", "ed", "es", "s"):
            if t.endswith(suffix) and len(t) > len(suffix) + 2:
                t = t[:-len(suffix)]
        return t
    ranked = sorted(((edit(norm(m.group()), norm(target)), m.start(), m.end(), m.group())
                     for m in tokens), key=lambda x: (x[0], x[1]))
    if not ranked or ranked[0][0] > 1:
        misses.append({"clip_id": clip["clip_id"], "condition": clip["condition"],
                       "sentence": clip["transcript"], "transcript": hyp,
                       "target": label["target_word"], "label": label["label"],
                       "category": label["category"], "status": "missing"})
        continue
    _, start, end, found = ranked[0]
    cases.append({"sentence": hyp, "target_word": found, "start": start, "end": end,
                  "category": label["category"], "label": label["label"],
                  "clip_id": clip["clip_id"], "condition": clip["condition"],
                  "reference": clip["transcript"], "source_target": label["target_word"]})
dest = root / "labels" / f"asr_context_cases_{args.engine}.json"
dest.write_text(json.dumps(cases, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
(root / "asr" / args.engine / "target_matches.json").write_text(
    json.dumps({"matched": len(cases), "unmatched": len(misses), "misses": misses},
               ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(f"matched {len(cases)}; unmatched {len(misses)}")
