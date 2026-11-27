"""Normalize/repair records after an interrupted matrix and long-run sampling."""
import json
import re
from pathlib import Path

ROOT = Path(r"C:\scratch\asr50")
OUT = ROOT / "results/whispercpp"
LOGS = ROOT / "WP8/logs"
RESULTS = OUT / "results.jsonl"

def timing(log: str, name: str):
    m = re.search(re.escape(name) + r"\s*=\s*([0-9.]+)\s*ms", log)
    return float(m.group(1)) / 1000 if m else None

rows = [json.loads(line) for line in RESULTS.read_text(encoding="utf-8").splitlines()]
gt = {x["clip_id"]: x for x in json.loads(
    (ROOT / "WP6/audio16k/ground_truth.json").read_text(encoding="utf-8"))["clips"]}
for row in rows:
    candidate = row["candidate"].removeprefix("whispercpp-")
    model, mode = candidate.rsplit("-", 1)
    requested = row["device"]["requested"]
    device_dir = requested
    clip = row["clip_id"]
    run = row["run"]
    raw_path = OUT / model / device_dir / mode / f"{clip}_{run['kind']}{run['index']}.json"
    tag = f"{model}_{requested}_{mode}_{clip}_{run['kind']}{run['index']}"
    log_path = LOGS / f"{tag}.log"
    if not log_path.exists() and requested == "cpu-vulkan":
        log_path = LOGS / f"{model}_vulkan_{mode}_{clip}_{run['kind']}{run['index']}.log"
    if log_path.exists():
        log = log_path.read_text(encoding="utf-8", errors="replace")
        actual = "vulkan0" if "using Vulkan0 backend" in log else "cpu"
        load = timing(log, "load time")
        infer = timing(log, "total time")
        if raw_path.exists():
            raw = json.loads(raw_path.read_text(encoding="utf-8"))
            raw["words"] = [{"word": w.get("text", w.get("word")),
                             "start": w.get("start_s", w.get("start")),
                             "end": w.get("end_s", w.get("end"))}
                            for w in raw.get("words", [])]
            raw["meta"]["actual_device"] = actual
            raw["meta"]["actual_device_verified_by"] = (
                "log line `using Vulkan0 backend`" if actual == "vulkan0"
                else "CPU DLL and CPU model-size log")
            raw["meta"]["model_load_seconds"] = load
            raw["meta"]["inference_seconds"] = infer
            raw_path.write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")
        row["device"]["actual"] = actual
        if infer is not None:
            row["measurements"]["runtime_s"] = infer
            row["measurements"]["rtf"] = infer / row["measurements"]["audio_duration_s"]
        row["measurements"]["model_load_s"] = load
        row["metrics"]["log"] = str(log_path)
        row["runtime"]["installed_bytes"] = sum(
            f.stat().st_size for f in (ROOT / "WP8/bin" / ("cpu" if requested == "cpu" else "vulkan")).iterdir()
            if f.is_file())
    row["metrics"]["reference_transcript"] = gt[clip]["transcript"]
RESULTS.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
                   encoding="utf-8")
print(f"Repaired {len(rows)} rows")
