"""Offline whisper.cpp benchmark for the approved WP6 corpus/models.

Run from PowerShell with Python 3.14.10. --matrix executes all model/device/
timing-mode/clip combinations. Timed runs take the shared timing lock.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import os
import re
import struct
import subprocess
import sys
import time
import wave
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(r"C:\scratch\asr50")
WP8 = ROOT / "WP8"
AUDIO = ROOT / "WP6" / "audio16k"
MODELS = {
    "turbo": ROOT / "models" / "whisper-large-v3-turbo-whisper-cpp-q5-0" / "ggml-large-v3-turbo-q5_0.bin",
    "small.en": ROOT / "models" / "whisper-small-en-whisper-cpp-q5-1" / "ggml-small.en-q5_1.bin",
}
MODEL_SHA = {
    "turbo": "394221709cd5ad1f40c46e6031ca61bce88931e6e088c188294c6d5a55ffa7e2",
    "small.en": "bfdff4894dcb76bbf647d56263ea2a96645423f1669176f4844a1bf8e478ad30",
}
CLI = {"vulkan": WP8 / "bin" / "vulkan" / "whisper-cli.exe",
       "cpu-vulkan": WP8 / "bin" / "vulkan" / "whisper-cli.exe",
       "cpu": WP8 / "bin" / "cpu" / "whisper-cli.exe"}
OUT = ROOT / "results" / "whispercpp"
LOG = WP8 / "logs"
LOCK = ROOT / "timing.lock.d"


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def duration(path: Path) -> float:
    # stdlib wave rejects IEEE float32 format tag 3; parse canonical RIFF chunks.
    with path.open("rb") as f:
        if f.read(4) != b"RIFF":
            raise ValueError(f"Not RIFF WAV: {path}")
        f.read(4)
        if f.read(4) != b"WAVE":
            raise ValueError(f"Not WAV: {path}")
        rate = align = data_size = None
        while chunk := f.read(8):
            if len(chunk) < 8:
                break
            name, size = struct.unpack("<4sI", chunk)
            data = f.read(size)
            if size & 1:
                f.read(1)
            if name == b"fmt " and len(data) >= 16:
                _, _, rate, _, align, _ = struct.unpack("<HHIIHH", data[:16])
            elif name == b"data":
                data_size = size
        if not rate or not align or data_size is None:
            raise ValueError(f"Missing WAV format/data chunk: {path}")
        return data_size / align / rate


def json_seconds(token: dict, key: str) -> float | None:
    value = token.get("offsets", {}).get(key)
    return value / 1000 if isinstance(value, (int, float)) else None


def words_from_json(doc: dict) -> tuple[str, list[dict]]:
    # New token if leading whitespace; join continuation subword tokens.
    # Special/control tokens and punctuation-only fragments are discarded.
    groups = []
    for segment in doc.get("transcription", []):
        for token in segment.get("tokens", []):
            text = token.get("text", "")
            stripped = text.strip()
            if (not text or text.startswith("[_") or stripped.startswith("[_")
                    or stripped in {"[BLANK_AUDIO]", "[_BEG_]"}):
                continue
            starts = text[:1].isspace()
            piece = text.strip()
            if not re.search(r"[\w]", piece, re.UNICODE):
                continue
            if starts or not groups:
                groups.append({"parts": [piece], "start_s": json_seconds(token, "from"),
                               "end_s": json_seconds(token, "to")})
            else:
                groups[-1]["parts"].append(piece)
                end = json_seconds(token, "to")
                if end is not None:
                    groups[-1]["end_s"] = end
    words = []
    for g in groups:
        text = "".join(g["parts"])
        # Keep internal apostrophes; trim leading/trailing punctuation.
        text = re.sub(r"^[^\w']+|[^\w']+$", "", text, flags=re.UNICODE)
        if text and text.casefold() not in {"blank_audio"}:
            words.append({"text": text, "start_s": g["start_s"], "end_s": g["end_s"]})
    text = " ".join(w["text"] for w in words)
    return text, words


def invoke(model_key: str, device: str, clip: Path, mode: str, threads: int,
           run_kind: str, run_index: int) -> dict:
    model = MODELS[model_key]
    exe = CLI[device]
    tag_kind = "cold" if run_kind == "functional" else run_kind
    tag = f"{model_key}_{device}_{mode}_{clip.stem}_{tag_kind}{run_index}"
    outbase = LOG / tag
    logpath = LOG / f"{tag}.log"
    jp = Path(str(outbase) + ".json")
    # Recover completed observations if an external timeout interrupted a run.
    if logpath.exists() and jp.exists():
        prior = logpath.read_text(encoding="utf-8", errors="replace")
        doc = json.loads(jp.read_text(encoding="utf-8"))
        text, words = words_from_json(doc)
        total = parse_timing(prior, r"total time") or 0.0
        load = parse_timing(prior, r"load time") or 0.0
        return {"model": model_key, "device": device, "mode": mode, "clip": clip,
                "threads": threads, "kind": run_kind, "index": run_index,
                "cmd": [], "exit": 0, "elapsed": total + load, "pid": None, "log": prior,
                "json": doc, "text": text, "words": words, "logpath": logpath,
                "jsonpath": jp}
    cmd = [str(exe), "-m", str(model), "-f", str(clip), "-l", "en",
           "-t", str(threads), "-ojf", "-of", str(outbase)]
    if device != "vulkan":
        cmd.append("-ng")
    else:
        cmd += ["-dev", "0"]
    if mode == "ml1":
        cmd += ["-ml", "1"]
    elif mode == "dtw":
        cmd += ["-nfa", "-dtw", "large.v3.turbo" if model_key == "turbo" else "small.en"]
    env = os.environ.copy()
    env.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", HF_HUB_DISABLE_TELEMETRY="1")
    start = time.perf_counter()
    proc = subprocess.Popen(cmd, env=env, text=True, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, errors="replace")
    process_id = proc.pid
    stdout, _ = proc.communicate()
    elapsed = time.perf_counter() - start
    logpath.write_text(stdout, encoding="utf-8")
    doc = json.loads(jp.read_text(encoding="utf-8")) if jp.exists() else {}
    text, words = words_from_json(doc)
    return {"model": model_key, "device": device, "mode": mode, "clip": clip,
            "threads": threads, "kind": run_kind, "index": run_index, "cmd": cmd,
            "exit": proc.returncode, "elapsed": elapsed, "pid": process_id, "log": stdout,
            "json": doc, "text": text, "words": words, "logpath": logpath,
            "jsonpath": jp}


def parse_timing(log: str, pattern: str) -> float | None:
    m = re.search(pattern + r"\s*=\s*([0-9.]+)\s*ms", log)
    return float(m.group(1)) / 1000 if m else None


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--matrix", action="store_true")
    p.add_argument("--threads", action="store_true")
    p.add_argument("--quick", action="store_true")
    p.add_argument("--cpu-vulkan", action="store_true")
    p.add_argument("--model", choices=tuple(MODELS))
    p.add_argument("--device", choices=tuple(CLI))
    p.add_argument("--mode", choices=("full", "ml1", "dtw"))
    p.add_argument("--functional", action="store_true")
    a = p.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    LOG.mkdir(parents=True, exist_ok=True)
    gt = json.loads((AUDIO / "ground_truth.json").read_text(encoding="utf-8"))
    manifest = json.loads((AUDIO / "manifest16k.json").read_text(encoding="utf-8"))
    clips = sorted(AUDIO.glob("*.wav"))
    if len(clips) != 14:
        raise SystemExit(f"Expected 14 WAV clips; found {len(clips)}")
    cats = {x["clip_id"] + ".wav": x["category"] for x in gt["clips"]}
    refs = {x["clip_id"]: x for x in gt["clips"]}
    records = []
    modes = ([a.mode] if a.mode else
             (["full"] if a.functional else ["full", "ml1", "dtw"]))
    devices = ("vulkan", "cpu-vulkan", "cpu")
    grid = [(m, d, mode, c) for m in MODELS for d in devices
            for mode in modes for c in clips]
    if a.cpu_vulkan:
        grid = [(m, "cpu-vulkan", mode, c) for m in MODELS
                for mode in modes for c in clips]
    if a.model:
        grid = [x for x in grid if x[0] == a.model]
    if a.device:
        grid = [x for x in grid if x[1] == a.device]
    if a.mode:
        grid = [x for x in grid if x[2] == a.mode]
    if a.quick:
        grid = [("small.en", "cpu", "dtw", AUDIO / "clean_001.wav")]

    def execute_grid():
        for model_key, device, mode, clip in grid:
            r = invoke(model_key, device, clip, mode, 12,
                       "functional" if a.functional else "cold", 0)
            records.append(r)
            # 3 repeated independent CLI launches on the clean clip give
            # explicit warm-cache observations without conflating process state.
            if not a.functional and clip.name == "clean_001.wav" and mode == "full":
                for i in range(1, 4):
                    records.append(invoke(model_key, device, clip, mode, 12, "warm", i))
        if a.threads and not a.functional:
            selected_models = (a.model,) if a.model else tuple(MODELS)
            for model_key in selected_models:
                thread_devices = ((a.device,) if a.device else
                                  (("cpu-vulkan",) if a.cpu_vulkan else ("vulkan", "cpu-vulkan", "cpu")))
                for device in thread_devices:
                    for clip in (AUDIO / "clean_001.wav", AUDIO / "rapid_001.wav",
                                 AUDIO / "silence_001.wav", AUDIO / "repeated_001.wav"):
                        for n in (4, 12, 24):
                            records.append(invoke(model_key, device, clip, "full", n, "threads", n))
    if a.functional:
        execute_grid()
    else:
        # Timed study only; functional ASR mode deliberately skips the lock.
        deadline = time.time() + 20 * 60
        while True:
            try:
                LOCK.mkdir()
                (LOCK / "owner.txt").write_text(str(os.getpid()), encoding="ascii")
                break
            except FileExistsError:
                if time.time() > deadline:
                    raise SystemExit("Could not acquire timing lock within 20 minutes")
                time.sleep(5)
        try:
            execute_grid()
        finally:
            (LOCK / "owner.txt").unlink(missing_ok=True)
            LOCK.rmdir()

    spec = importlib.util.spec_from_file_location(
        "score", r"C:\code\muteinous-spike50\spike\asr50\benchmark\score.py")
    score = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(score)
    jsonl = []
    rawroot = OUT
    for r in records:
        model_key, device, mode, clip = r["model"], r["device"], r["mode"], r["clip"]
        clip_id = clip.stem
        ref = refs[clip_id]
        hyp_words = r["words"]
        metric = score.edit_counts(score.tokenize(ref["transcript"]), score.tokenize(r["text"]))
        targets = score.target_metrics(ref["transcript"], r["text"])
        time_metrics = score.timing_metrics(ref["words"], hyp_words, metric["matches"])
        peak = None
        try:
            import ctypes
            class PMC(ctypes.Structure):
                _fields_ = [("cb", ctypes.c_ulong), ("PageFaultCount", ctypes.c_ulong),
                            ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                            ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                            ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                            ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t)]
            # Exe has exited; per-process peak working set cannot be queried afterwards.
            _ = PMC
        except Exception:
            pass
        duration_s = duration(clip)
        infer_s = None if a.functional else parse_timing(r["log"], r"total time")
        if not a.functional and infer_s is None:
            infer_s = r["elapsed"]
        runtime_dir = CLI[device].parent
        runtime_bytes = sum(f.stat().st_size for f in runtime_dir.iterdir() if f.is_file())
        category = cats[clip.name]
        actual_device = ("vulkan0" if "using Vulkan0 backend" in r["log"] else "cpu")
        meta = {"runtime": "whisper.cpp", "version": "1.9.6-dev",
                "model_artifact": model_key, "model_sha256": MODEL_SHA[model_key],
                "requested_device": device, "actual_device": actual_device,
                "actual_device_verified_by": ("log line `using Vulkan0 backend`" if actual_device == "vulkan0"
                                              else "CPU DLL and `CPU total size` log"),
                "settings": {"language": "en", "mode": mode, "threads": r["threads"],
                             "decoding": {"full_json": True}},
                "wall_seconds": None if a.functional else r["elapsed"],
                "process_peak_working_set_bytes": peak,
                "model_load_seconds": None if a.functional else parse_timing(r["log"], r"load time"),
                "peak_dedicated_gpu_bytes": None}
        normalized = {"text": r["text"],
                      "words": [{"word": w["text"], "start": w["start_s"], "end": w["end_s"]}
                                for w in hyp_words],
                      "meta": meta}
        dest = rawroot / model_key / device / mode
        dest.mkdir(parents=True, exist_ok=True)
        (dest / f"{clip_id}_{r['kind']}{r['index']}.json").write_text(
            json.dumps(normalized, ensure_ascii=False, indent=2), encoding="utf-8")
        record = {"schema_version": 1, "candidate": f"whispercpp-{model_key}-{mode}",
                  "clip_id": clip_id, "category": category,
                  "run": {"kind": r["kind"], "index": r["index"], "process_id": r.get("pid")},
                  "hardware": {"cpu": "AMD Ryzen 9 9900X", "gpu": "AMD Radeon RX 7900 XT",
                               "ram_bytes": 31600000000, "os": "Windows 11 Pro",
                               "driver": "32.0.32029.2010"},
                  "device": {"requested": device, "actual": actual_device},
                  "runtime": {"name": "whisper.cpp", "version": "1.9.6-dev",
                              "package_version": "CI binary 96ec4d98",
                              "installed_bytes": runtime_bytes},
                  "model": {"artifact_id": model_key, "sha256": MODEL_SHA[model_key],
                            "bytes": MODELS[model_key].stat().st_size, "cache_bytes": 0},
                  "settings": {"language": "en", "sample_rate_hz": 16000, "channels": 1,
                               "threads": r["threads"], "decoding": {"mode": mode}},
                  "input": {"sample_rate_hz": 16000, "channels": 1, "dtype": "float32",
                            "clip_sha256": manifest[clip.name]["sha256"]},
                  "measurements": {"audio_duration_s": duration_s, "runtime_s": infer_s,
                                   "process_wall_s": None if a.functional else r["elapsed"],
                                   "rtf": infer_s / duration_s if infer_s is not None and duration_s else None,
                                   "model_load_s": None if a.functional else parse_timing(r["log"], r"load time"),
                                   "peak_ram_bytes": None, "peak_vram_bytes": None,
                                   "peak_vram_method": "PDH sampler not yet implemented",
                                   "model_footprint_bytes": MODELS[model_key].stat().st_size},
                  "hypothesis": {"text": r["text"],
                                 "words": [{"text": w["text"], "start_s": w["start_s"],
                                            "end_s": w["end_s"]} for w in hyp_words]},
                  "metrics": {"wer": metric["wer"], "substitutions": metric["substitutions"],
                              "deletions": metric["deletions"], "insertions": metric["insertions"],
                              "targets": targets, "timing": time_metrics,
                              "exit_code": r["exit"], "log": str(r["logpath"])}}
        jsonl.append(record)
    results_path = OUT / "results.jsonl"
    if results_path.exists() and not (a.matrix and not any((a.cpu_vulkan, a.model, a.device, a.mode))):
        old = [json.loads(line) for line in results_path.read_text(encoding="utf-8").splitlines()]
        replacement_keys = {(x["candidate"], x["device"]["requested"], x["clip_id"],
                             x["run"]["kind"], x["run"]["index"]) for x in jsonl}
        replacements_base = {(x[0], x[1], x[2], x[4]) for x in replacement_keys}
        old = [x for x in old if
               (x["candidate"], x["device"]["requested"], x["clip_id"],
                x["run"]["index"]) not in replacements_base]
        jsonl = old + jsonl
    results_path.write_text(
        "".join(json.dumps(x, ensure_ascii=False) + "\n" for x in jsonl), encoding="utf-8")
    print(f"Wrote {len(jsonl)} observations to {OUT}")


if __name__ == "__main__":
    main()
