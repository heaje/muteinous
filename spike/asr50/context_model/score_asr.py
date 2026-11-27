"""Score WP23 ASR output when the Vulkan runner has completed."""
import json
import re
import argparse
from collections import Counter, defaultdict
from pathlib import Path

root = Path(r"C:\scratch\asr50\WP23")
parser = argparse.ArgumentParser()
parser.add_argument("--engine", choices=("whispercpp-vulkan", "parakeet-cpu"), required=True)
args = parser.parse_args()
audio = root / "corpus" / "audio16k_v3"
truth = json.loads((audio / "ground_truth_v3.json").read_text(encoding="utf-8"))
labels = json.loads((root / "labels" / "wp23_authored.json").read_text(encoding="utf-8"))
by_sentence = {r["sentence"]: r for r in labels}
outputs = json.loads((root / "asr" / args.engine / "outputs.json").read_text(encoding="utf-8"))
by_clip = {r["clip_id"]: r for r in outputs}

def words(text):
    return re.findall(r"[^\W_]+(?:'[^\W_]+)*", text.casefold(), flags=re.UNICODE)

def distance(a, b):
    row = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        nxt = [i]
        for j, cb in enumerate(b, 1):
            nxt.append(min(nxt[-1] + 1, row[j] + 1, row[j - 1] + (ca != cb)))
        row = nxt
    return row[-1]

def target_status(target, hyp):
    t = target.casefold()
    tokens = words(hyp)
    if t in tokens:
        return "exact"
    stems = {t, t.rstrip("s"), t.rstrip("ed"), t.rstrip("ing"), t.rstrip("es")}
    if any(token in stems or token.rstrip("s") in stems or token.rstrip("ed") in stems
           or token.rstrip("ing") in stems for token in tokens):
        return "variant"
    if any(len(t) >= 4 and distance(t, token) <= 1 for token in tokens):
        return "mangled"
    return "missing"

def wer(ref, hyp):
    a, b = words(ref), words(hyp)
    row = list(range(len(b) + 1))
    for i, wa in enumerate(a, 1):
        nxt = [i]
        for j, wb in enumerate(b, 1):
            nxt.append(min(nxt[-1] + 1, row[j] + 1, row[j - 1] + (wa != wb)))
        row = nxt
    return row[-1] / max(1, len(a)), row[-1], len(a)

rows = []
for clip in truth["clips"]:
    result = by_clip.get(clip["clip_id"], {})
    if result.get("error"):
        continue
    case = by_sentence.get(clip["transcript"])
    if not case:
        continue
    rate, edits, ref_words = wer(clip["transcript"], result.get("text", ""))
    rows.append({"clip_id": clip["clip_id"], "condition": clip["condition"],
                 "voice": clip.get("voice"), "wer": rate, "edits": edits,
                 "reference_words": ref_words,
                 "target_status": target_status(case["target_word"], result.get("text", "")),
                 "text": clip["transcript"], "transcript": result.get("text", ""),
                 "target": case["target_word"], "label": case["label"],
                 "category": case["category"]})
summary = {}
for condition in sorted({r["condition"] for r in rows}):
    subset = [r for r in rows if r["condition"] == condition]
    counts = Counter(r["target_status"] for r in subset)
    summary[condition] = {"clips": len(subset),
                          "WER": sum(r["edits"] for r in subset) / max(1, sum(r["reference_words"] for r in subset)),
                          "target_status": dict(counts)}
(root / "asr" / args.engine / "score.json").write_text(
    json.dumps({"summary": summary, "rows": rows}, ensure_ascii=False, indent=2) + "\n",
    encoding="utf-8")
print(json.dumps(summary, indent=2))
