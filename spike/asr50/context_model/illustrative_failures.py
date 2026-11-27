"""Collect up to 15 representative errors with the ASR text shown."""
import json
from pathlib import Path

root = Path(r"C:\scratch\asr50\WP23")
truth_path = root / "context_winml17_cpu_all.json"
if truth_path.exists():
    truth_rows = json.loads(truth_path.read_text(encoding="utf-8"))["results"]
    truth_errors = [r for r in truth_rows if "group" in r]
else:
    truth_errors = json.loads((root / "context_cpu_authored.json").read_text(encoding="utf-8"))["results"]
truth_errors = [r for r in truth_errors if "group" in r]
truth_errors = [r for r in truth_errors if int(r["label"]) != int(r["pred"])]
audio_clips = json.loads((root / "corpus" / "audio16k_v3" / "ground_truth_v3.json")
                         .read_text(encoding="utf-8"))["clips"]
whisper = json.loads((root / "asr" / "whispercpp-vulkan" / "outputs.json")
                     .read_text(encoding="utf-8"))
whisper_by_id = {r["clip_id"]: r for r in whisper}
asr_by_text = {}
for clip in audio_clips:
    if clip["condition"] == "clean" and clip.get("voice", "").endswith("Zira Desktop"):
        asr_by_text[clip["transcript"]] = whisper_by_id.get(clip["clip_id"], {}).get("text", "")
records = []
for row in truth_errors:
    transcript = row["sentence"]
    records.append({"source": "true text", "text": transcript,
                    "asr_transcript": asr_by_text.get(transcript, "— ASR output unavailable"),
                    "target": row["target_word"], "label": row["label"],
                    "decision": "censor" if row["pred"] else "keep", "failure": "wrong"})

for engine, context_file in (("parakeet-cpu", "context_parakeet_cpu.json"),
                             ("whispercpp-vulkan", "context_whispercpp_vulkan.json")):
    combined = root / "context_winml17_cpu_asr_all.json"
    if combined.exists():
        decisions = [r for r in json.loads(combined.read_text(encoding="utf-8"))["results"]
                     if r.get("engine") == engine]
    else:
        p = root / context_file
        if not p.exists():
            continue
        decisions = json.loads(p.read_text(encoding="utf-8"))["results"]
    for row in decisions:
        if int(row["label"]) != int(row["pred"]):
            records.append({"source": engine, "text": row["reference"],
                            "asr_transcript": row["sentence"], "target": row["source_target"],
                            "label": row["label"], "decision": "censor" if row["pred"] else "keep",
                            "failure": "wrong"})

# Include missed targets as end-to-end failures; the context model cannot see them.
for engine in ("parakeet-cpu", "whispercpp-vulkan"):
    p = root / "asr" / engine / "target_matches.json"
    if not p.exists():
        continue
    data = json.loads(p.read_text(encoding="utf-8"))
    for row in data["misses"]:
        if int(row["label"]) == 1:
            records.append({"source": engine, "text": row["sentence"],
                            "asr_transcript": row["transcript"], "target": row["target"],
                            "label": row["label"], "decision": "ASR miss → not censored",
                            "failure": "missing target"})

# Sample several failure modes instead of letting missing-target examples crowd
# out context-model errors: ASR+context false-keeps, true-text false-keeps,
# then ASR misses. False-censors fill any remaining slots.
groups = [
    [r for r in records if r["source"] != "true text" and r["failure"] == "wrong"
     and r["label"] == 1 and r["decision"] == "keep"],
    [r for r in records if r["source"] == "true text"],
    [r for r in records if r["failure"] == "missing target"],
    [r for r in records if r["label"] == 0 and r["decision"] == "censor"],
]
selected, seen = [], set()
for group, target_n in zip(groups, (5, 5, 5, 15)):
    added = 0
    for row in group:
        key = (row["source"], row["text"], row["asr_transcript"], row["target"], row["decision"])
        if key in seen:
            continue
        seen.add(key)
        selected.append(row)
        added += 1
        if added >= target_n:
            break
records = selected[:15]
(root / "illustrative_failures.json").write_text(json.dumps(records, ensure_ascii=False, indent=2) + "\n",
                                                   encoding="utf-8")
print(f"wrote {len(records)} illustrative failures")
