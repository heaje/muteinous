"""Functional whisper.cpp Vulkan pass on WP23's generated corpus."""
import json
import os
import subprocess
from pathlib import Path

os.environ.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1",
                  HF_HUB_DISABLE_TELEMETRY="1")
root = Path(r"C:\scratch\asr50\WP23")
audio = root / "corpus" / "audio16k_v3"
gt = json.loads((audio / "ground_truth_v3.json").read_text(encoding="utf-8"))
binary = Path(r"C:\scratch\asr50\WP2\artifacts\whisper-vulkan-dl-windows-x64\whisper-cli.exe")
model = Path(r"C:\scratch\asr50\models\whisper-large-v3-turbo-whisper-cpp-q5-0\ggml-large-v3-turbo-q5_0.bin")
out = root / "asr" / "whispercpp-vulkan"
out.mkdir(parents=True, exist_ok=True)
records = []
for i, clip in enumerate(gt["clips"], 1):
    wav = audio / clip["wav"]
    base = out / clip["clip_id"]
    proc = subprocess.run([str(binary), "-m", str(model), "-f", str(wav), "-l", "en",
                           "-t", "12", "-ojf", "-of", str(base), "-dev", "0"],
                          capture_output=True, text=True, errors="replace", env=os.environ.copy())
    (out / f"{clip['clip_id']}.log").write_text(proc.stdout + proc.stderr, encoding="utf-8")
    if proc.returncode or "using Vulkan0 backend" not in proc.stdout + proc.stderr:
        records.append({"clip_id": clip["clip_id"], "error": proc.returncode,
                        "log": proc.stdout + proc.stderr})
        continue
    doc_path = Path(str(base) + ".json")
    doc = json.loads(doc_path.read_text(encoding="utf-8"))
    text = " ".join(seg.get("text", "").strip() for seg in doc.get("transcription", []))
    records.append({"clip_id": clip["clip_id"], "text": text, "transcript": clip["transcript"],
                    "condition": clip["condition"], "voice": clip.get("voice"),
                    "error": None})
    if i % 50 == 0:
        (out / "partial.json").write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"completed {i}/{len(gt['clips'])}", flush=True)
(out / "outputs.json").write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"finished {len(records)} clips; failures={sum(bool(x.get('error')) for x in records)}")
