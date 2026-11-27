"""Execute one library inference in a killable child process."""
import argparse
import json
import os
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import library_timing as lt


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--kind", required=True)
    p.add_argument("--device", required=True)
    p.add_argument("--threads", required=True, type=int)
    p.add_argument("--beam", required=True, type=int)
    p.add_argument("--clip-id", required=True)
    p.add_argument("--out", required=True, type=Path)
    a = p.parse_args()
    os.environ.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", HF_HUB_DISABLE_TELEMETRY="1")
    item = next(x for x in lt.selected() if x["clip_id"] == a.clip_id)
    process = lt.psutil.Process()
    backend = lt.Backend(a.kind, a.threads, a.beam, a.device)
    active_providers = (backend.sessions[0].get_providers()
                        if a.kind in ("ort-small", "ort-turbo") else [])
    provider_verified = (a.kind not in ("ort-small", "ort-turbo") or
                         (("DmlExecutionProvider" if a.device == "dml" else "CPUExecutionProvider")
                          in active_providers))
    audio = lt.read_f32_wav(item["path"])
    warm_start = time.perf_counter()
    warm_text = backend.infer(audio, item["transcript"])
    warm_s = time.perf_counter() - warm_start
    cpu_before = sum(process.cpu_times()[:2])
    start = time.perf_counter()
    text = backend.infer(audio, item["transcript"])
    elapsed = time.perf_counter() - start
    cpu_after = sum(process.cpu_times()[:2])
    baseline = lt.accuracy_baseline(a.kind, a.device, a.beam, a.clip_id)
    row = {
        "kind": a.kind, "clip_id": item["clip_id"], "class": item["class"],
        "status": ("backend_not_verified" if not provider_verified else
                   "ok" if text.strip() else "empty_output"),
        "runtime_providers": active_providers,
        "provider_verified": provider_verified,
        "wall_seconds": elapsed, "timer": "time.perf_counter",
        "audio_seconds": item["duration_s"], "rtf": elapsed / item["duration_s"],
        "speed_multiple": item["duration_s"] / elapsed if elapsed else None,
        "text": text, "transcript": item["transcript"],
        "text_matches_reference": None if a.kind in ("vad", "aligner") else
            lt.tokens(text) == lt.tokens(item["transcript"]),
        "accuracy_baseline_text": baseline,
        "matches_accuracy_baseline_words": (
            lt.tokens(text) == lt.tokens(baseline) if baseline is not None else None),
        "warmup_seconds": warm_s, "warmup_text": warm_text,
        "model_load_s": backend.model_load_s,
        "process_cpu_seconds": cpu_after - cpu_before,
        "cores_used": (cpu_after - cpu_before) / elapsed if elapsed else None,
        "peak_working_set_bytes": getattr(process.memory_info(), "peak_wset", None),
        "pid": os.getpid(), "counter_sampling_during_timing": False,
        "runtime_versions": lt.runtime_versions(a.kind),
    }
    a.out.write_text(json.dumps(row, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()
