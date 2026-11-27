"""Crash-resilient, one-record-per-run whisper.cpp benchmark driver."""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

BASE = Path(r"C:\scratch\asr50")
OUT = BASE / "WP22"
CLASSES = {
    "short": [f"v3_clean_{i:03d}_0" for i in range(1, 9)],
    "medium": ["natural_18s_00", "natural_25s_00", "natural_18s_01", "natural_25s_01"],
    "long": ["natural_sentences_00", "natural_sentences_01"],
}
WORD = re.compile(r"[a-z0-9]+(?:'[a-z0-9]+)*")


def now():
    return datetime.now(timezone.utc).isoformat()


def tokenize(s):
    return WORD.findall((s or "").casefold())


def load_truth():
    truth = {}
    for path in (BASE / "corpus_v3_frozen" / "ground_truth_v3.json",
                 BASE / "corpus_v2_frozen" / "ground_truth_v2.json"):
        for clip in json.loads(path.read_text(encoding="utf-8-sig"))["clips"]:
            truth[clip["clip_id"]] = clip
    return truth


def baseline_text(model, device, clip_id):
    root = (BASE / ("results_v3" if clip_id.startswith("v3_") else "results_v2") /
            "whispercpp" / "raw" if clip_id.startswith("v3_") else
            BASE / "results_v2" / "whispercpp")
    slug = "turbo" if model == "turbo" else "small.en"
    path = root / f"{slug}-{device}-full" / f"{clip_id}.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        return data.get("text") or "".join(
            x.get("text", "") for x in data.get("transcription", []))
    except (OSError, json.JSONDecodeError):
        return None


def preflight(config, out):
    import psutil

    started = time.monotonic()
    deadline = started + 60
    samples = []
    while time.monotonic() < deadline:
        cpu = [psutil.cpu_percent(interval=1) for _ in range(3)]
        # GPU counters are queried only in this untimed quiet check.
        command = (
            "$ErrorActionPreference='Stop'; "
            "$s=Get-Counter '\\GPU Engine(*)\\Utilization Percentage' "
            "-SampleInterval 1 -MaxSamples 3; "
            "$v=@($s.CounterSamples | Where-Object { "
            "$_.Path -match 'luid_0x00000000_0x000164ac' -and "
            "$_.Path -match 'engtype_(3d|compute)' } | "
            "ForEach-Object { [double]$_.CookedValue }); "
            "if($v.Count){($v|Measure-Object -Maximum).Maximum}else{0}"
        )
        gpu_run = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command],
            capture_output=True, text=True, timeout=20)
        gpu_max = float(gpu_run.stdout.strip().splitlines()[-1]) if gpu_run.returncode == 0 else None
        sample = {"utc": now(), "cpu_percent": cpu, "rx7900_3d_compute_max_percent": gpu_max}
        samples.append(sample)
        if max(cpu) < 5 and gpu_max is not None and gpu_max < 0.1:
            procs = []
            for p in psutil.process_iter(["pid", "name", "cpu_times", "memory_info"]):
                try:
                    info = p.info
                    ct = info["cpu_times"]
                    procs.append({"name": info["name"], "pid": info["pid"],
                                  "cpu_seconds": ct.user + ct.system if ct else None,
                                  "working_set_bytes": info["memory_info"].rss if info["memory_info"] else None})
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
            (out / f"{config}-preflight.json").write_text(json.dumps({
                "config": config, "idle_samples": samples, "background_processes": procs,
                "idle_wait_seconds": time.monotonic() - started,
            }, indent=2), encoding="utf-8")
            return
    (out / f"{config}-preflight.json").write_text(json.dumps(
        {"config": config, "idle_samples": samples, "idle_wait_seconds": time.monotonic() - started},
        indent=2), encoding="utf-8")
    raise RuntimeError(f"idle threshold not met within 60 seconds for {config}")


def completed_ids(checkpoint):
    done = set()
    if not checkpoint.exists():
        return done
    for line in checkpoint.read_text(encoding="utf-8-sig").splitlines():
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if row.get("status") in ("ok", "partial_valid_timing") and row.get("wall_seconds") is not None:
            done.add((row.get("clip_id"), int(row.get("repeat", 1))))
    return done


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", choices=("turbo", "small-en"), required=True)
    ap.add_argument("--device", choices=("cpu", "vulkan"), required=True)
    ap.add_argument("--threads", type=int, choices=(4, 12), required=True)
    ap.add_argument("--drift", action="store_true")
    ap.add_argument("--timeout", type=float, default=600)
    ap.add_argument("--attempt", default="")
    args = ap.parse_args()
    model = ("whisper-large-v3-turbo-whisper-cpp-q5-0/ggml-large-v3-turbo-q5_0.bin"
             if args.model == "turbo" else
             "whisper-small-en-whisper-cpp-q5-1/ggml-small.en-q5_1.bin")
    binary = (BASE / "WP2" / "artifacts" /
              ("whisper-vulkan-dl-windows-x64" if args.device == "vulkan" else "whisper-cpu-dl-windows-x64") /
              "whisper-cli.exe")
    model_path = BASE / "models" / model
    config = f"{args.model}-{args.device}-t{args.threads}" + ("-drift" if args.drift else "")
    suffix = f"-{args.attempt}" if args.attempt else ""
    logdir = OUT / f"{config}{suffix}-logs"
    logdir.mkdir(parents=True, exist_ok=True)
    checkpoint = OUT / f"{config}{suffix}.jsonl"
    if not binary.is_file() or not model_path.is_file():
        raise FileNotFoundError(f"approved executable/model missing: {binary} / {model_path}")
    preflight(f"{config}{suffix}", OUT)
    env = os.environ.copy()
    env.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1",
               HF_HUB_DISABLE_TELEMETRY="1", GGML_VK_VISIBLE_DEVICES="0")
    truth = load_truth()
    done = completed_ids(checkpoint)
    with checkpoint.open("a", encoding="utf-8", buffering=1) as out:
        for klass, clips in CLASSES.items():
            repeats = 3 if klass == "long" else 5
            for clip_id in clips:
                item = truth[clip_id]
                corpus = BASE / ("corpus_v3_frozen" if clip_id.startswith("v3_") else "corpus_v2_frozen")
                for repeat in range(1, repeats + 1):
                    if (clip_id, repeat) in done:
                        continue
                    prefix = logdir / f"{clip_id}-r{repeat}"
                    command = [str(binary), "-m", str(model_path), "-f", str(corpus / f"{clip_id}.wav"),
                               "-l", "en", "-t", str(args.threads), "-ojf", "-of", str(prefix)]
                    command += ["-dev", "0"] if args.device == "vulkan" else ["-ng"]
                    started = now()
                    t0 = time.perf_counter()
                    status, exit_code, stdout, stderr = "ok", None, "", ""
                    try:
                        result = subprocess.run(command, capture_output=True, text=True, timeout=args.timeout,
                                                env=env, check=False)
                        exit_code, stdout, stderr = result.returncode, result.stdout, result.stderr
                        if exit_code:
                            status = "nonzero_exit"
                    except subprocess.TimeoutExpired as exc:
                        status, exit_code = "timeout", None
                        stdout = exc.stdout.decode(errors="replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
                        stderr = exc.stderr.decode(errors="replace") if isinstance(exc.stderr, bytes) else (exc.stderr or "")
                    wall = time.perf_counter() - t0
                    (Path(str(prefix) + ".log")).write_text(stdout, encoding="utf-8")
                    (Path(str(prefix) + ".err")).write_text(stderr, encoding="utf-8")
                    json_path = Path(str(prefix) + ".json")
                    text = ""
                    try:
                        doc = json.loads(json_path.read_text(encoding="utf-8-sig"))
                        text = "".join(x.get("text", "") for x in doc.get("transcription", [])).strip()
                    except (OSError, json.JSONDecodeError):
                        if status == "ok":
                            status = "missing_json"
                    # whisper.cpp emits backend and timing diagnostics on stderr.
                    log = stderr
                    internal = {}
                    for key in ("load", "encode", "decode", "batchd", "total"):
                        m = re.search(rf"(?im)whisper_print_timings:\s*{key} time\s*=\s*([0-9.]+)\s*ms", log)
                        if not m and key == "load":
                            m = re.search(r"(?im)whisper_print_timings:\s*load time\s*=\s*([0-9.]+)\s*ms", log)
                        internal[key + "_ms"] = float(m.group(1)) if m else None
                    backend_ok = "using Vulkan0 backend" in log
                    if status == "ok" and not text:
                        status = "empty_output"
                    if status == "ok" and args.device == "vulkan" and not backend_ok:
                        status = "gpu_not_verified"
                    if status == "ok" and args.device == "cpu" and backend_ok:
                        status = "unexpected_gpu"
                    baseline = baseline_text(args.model, args.device, clip_id)
                    row = {
                        "config": config, "class": klass, "clip_id": clip_id, "repeat": repeat,
                        "status": status, "started_utc": started, "exit_code": exit_code,
                        "wall_seconds": wall, "timer": "time.perf_counter",
                        "counter_sampling_during_timing": False, "command": command,
                        "internal": internal, "text": text, "transcript": item["transcript"],
                        "text_matches_reference": tokenize(text) == tokenize(item["transcript"]),
                        "accuracy_baseline_text": baseline,
                        "matches_accuracy_baseline_words": (
                            tokenize(text) == tokenize(baseline) if baseline is not None else None),
                        "backend_verified": backend_ok,
                        "peak_working_set_bytes": None, "process_cpu_seconds": None,
                        "process_gpu_counters": "separate untimed pass pending",
                        "audio_seconds": item["duration_s"], "rtf": wall / item["duration_s"],
                        "speed_multiple": item["duration_s"] / wall if wall else None,
                    }
                    out.write(json.dumps(row, ensure_ascii=False) + "\n")
                    out.flush()
                    print(json.dumps({"config": config, "clip": clip_id, "repeat": repeat,
                                      "status": status, "wall_seconds": wall}), flush=True)
    print(f"Completed requested run set for {config}; checkpoint={checkpoint}")


if __name__ == "__main__":
    main()
