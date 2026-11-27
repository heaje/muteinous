"""Append one completed CLI invocation after its timer has stopped."""
import argparse
import json
import re
from pathlib import Path


def tokens(text):
    return re.findall(r"[a-z0-9]+(?:'[a-z0-9]+)*", text.casefold())


def read(path):
    return Path(path).read_text(encoding="utf-8-sig") if Path(path).is_file() else ""


def accuracy_baseline(clip_id, device):
    if clip_id.startswith("v3_"):
        root = Path(r"C:\scratch\asr50\results_v3\whispercpp\raw")
    else:
        root = Path(r"C:\scratch\asr50\results_v2\whispercpp")
    path = root / f"turbo-{device}-full" / f"{clip_id}.json"
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8-sig")).get("text")
    except (OSError, json.JSONDecodeError):
        return None


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--config", required=True)
    p.add_argument("--clip-class", required=True)
    p.add_argument("--clip-id", required=True)
    p.add_argument("--repeat", required=True, type=int)
    p.add_argument("--device", choices=("cpu", "vulkan"), required=True)
    p.add_argument("--started", required=True)
    p.add_argument("--meta", required=True, type=Path)
    p.add_argument("--stdout", required=True, type=Path)
    p.add_argument("--stderr", required=True, type=Path)
    p.add_argument("--json", required=True, type=Path)
    p.add_argument("--checkpoint", required=True, type=Path)
    a = p.parse_args()
    meta = json.loads(a.meta.read_text(encoding="utf-8")) if a.meta.is_file() else {}
    stdout, stderr = read(a.stdout), read(a.stderr)
    log = stdout + "\n" + stderr
    doc = json.loads(a.json.read_text(encoding="utf-8-sig")) if a.json.is_file() else {}
    text = "".join(item.get("text", "") for item in doc.get("transcription", [])).strip()
    gt_paths = (Path(r"C:\scratch\asr50\corpus_v3_frozen\ground_truth_v3.json"),
                Path(r"C:\scratch\asr50\corpus_v2_frozen\ground_truth_v2.json"))
    transcript = None
    for path in gt_paths:
        if path.is_file():
            data = json.loads(path.read_text(encoding="utf-8-sig"))
            clip = next((c for c in data["clips"] if c["clip_id"] == a.clip_id), None)
            if clip:
                transcript = clip["transcript"]
                break
    internal = {}
    for key in ("load time", "encode time", "decode time", "total time", "batchd time"):
        match = re.search(
            rf"(?im)whisper_print_timings:\s*{re.escape(key)}\s*=\s*([0-9.]+)\s*ms",
            log)
        internal[key.replace(" ", "_") + "_ms"] = float(match.group(1)) if match else None
    backend = "using Vulkan0 backend" in log
    baseline_text = accuracy_baseline(a.clip_id, a.device)
    status = meta.get("status", "missing_meta")
    if status == "ok" and (not text or transcript is None):
        status = "empty_output_or_missing_reference"
    if status == "ok" and a.device == "vulkan" and not backend:
        status = "gpu_not_verified"
    if status == "ok" and a.device == "cpu" and backend:
        status = "unexpected_gpu"
    row = {
        "config": a.config, "class": a.clip_class, "clip_id": a.clip_id,
        "repeat": a.repeat, "status": status, "started_utc": a.started,
        "process_id": meta.get("pid"), "exit_code": meta.get("exit_code"),
        "wall_seconds": meta.get("wall_seconds"), "timer": meta.get("timer"),
        "internal": internal, "text": text, "transcript": transcript,
        "text_matches_reference": tokens(text) == tokens(transcript or ""),
        "accuracy_baseline_text": baseline_text,
        "matches_accuracy_baseline_words": (
            tokens(text) == tokens(baseline_text) if baseline_text is not None else None),
        "backend_verified": backend, "backend_evidence": (
            "whisper_backend_init_gpu: using Vulkan0 backend" if backend else None),
        "peak_working_set_bytes": meta.get("peak_working_set_bytes"),
        "process_cpu_seconds": meta.get("process_cpu_seconds"),
        "cores_used": meta.get("cores_used"),
        "counter_sampling_during_timing": meta.get("counter_sampling_during_timing"),
        "process_gpu_counters": "separate untimed GPU telemetry pass",
        "error": stderr if status != "ok" else None,
    }
    a.checkpoint.parent.mkdir(parents=True, exist_ok=True)
    with a.checkpoint.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(json.dumps({"status": status, "clip_id": a.clip_id, "repeat": a.repeat}))


if __name__ == "__main__":
    main()
