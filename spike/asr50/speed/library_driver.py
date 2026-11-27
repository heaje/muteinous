"""Serial library benchmark controller with a hard child-process timeout per run."""
import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import psutil

HERE = Path(__file__).resolve().parent
BASE = Path(r"C:\scratch\asr50")
OUT = BASE / "WP22"
KINDS = ("ort-turbo", "ort-small", "parakeet", "faster", "moonshine", "vad", "aligner")


def worker_python(kind, device):
    mapping = {
        "ort-turbo": BASE / "WP12" / "venv" / device / "Scripts" / "python.exe",
        "ort-small": BASE / "WP13" / f"venv-{('dml' if device == 'dml' else 'cpu')}" /
                     "Scripts" / "python.exe",
        "parakeet": BASE / "WP9" / "venv" / "Scripts" / "python.exe",
        "faster": BASE / "WP10" / "venv" / "Scripts" / "python.exe",
        "moonshine": BASE / "WP10" / "venv" / "Scripts" / "python.exe",
        "vad": BASE / "WP14" / "venv" / "Scripts" / "python.exe",
        "aligner": BASE / "WP10" / "venv" / "Scripts" / "python.exe",
    }
    return mapping[kind]


def quiet_check(config):
    started = time.monotonic()
    deadline = started + 60
    samples = []
    while time.monotonic() < deadline:
        cpu = [psutil.cpu_percent(interval=1) for _ in range(3)]
        cmd = (
            "$s=Get-Counter '\\GPU Engine(*)\\Utilization Percentage' -SampleInterval 1 -MaxSamples 3; "
            "$v=@($s.CounterSamples|?{$_.Path -match 'luid_0x00000000_0x000164ac' -and "
            "$_.Path -match 'engtype_(3d|compute)'}|%{[double]$_.CookedValue});"
            "if($v.Count){($v|Measure-Object -Maximum).Maximum}else{0}"
        )
        r = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", cmd],
                           capture_output=True, text=True, timeout=20)
        gpu = float(r.stdout.strip().splitlines()[-1]) if r.returncode == 0 else None
        samples.append({"utc": datetime.now(timezone.utc).isoformat(),
                        "cpu_percent": cpu, "rx7900_3d_compute_max_percent": gpu})
        if max(cpu) < 5 and gpu is not None and gpu < 0.1:
            processes = []
            for proc in psutil.process_iter(["pid", "name", "cpu_times", "memory_info"]):
                try:
                    info = proc.info
                    times = info["cpu_times"]
                    mem = info["memory_info"]
                    processes.append({"pid": info["pid"], "name": info["name"],
                                      "cpu_seconds": times.user + times.system if times else None,
                                      "working_set_bytes": mem.rss if mem else None})
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
            (OUT / f"{config}-preflight.json").write_text(
                json.dumps({"config": config, "idle_samples": samples, "background_processes": processes,
                            "idle_wait_seconds": time.monotonic() - started}, indent=2), encoding="utf-8")
            return
    (OUT / f"{config}-preflight.json").write_text(
        json.dumps({"config": config, "idle_samples": samples}, indent=2), encoding="utf-8")
    raise RuntimeError(f"Idle threshold not met for {config}")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--kind", choices=KINDS, required=True)
    p.add_argument("--device", choices=("cpu", "dml"), default="cpu")
    p.add_argument("--threads", type=int, choices=(4, 12), required=True)
    p.add_argument("--beam", type=int, choices=(1, 5), default=5)
    p.add_argument("--clips", choices=("all", "short", "medium", "long"), default="all")
    p.add_argument("--timeout", type=float, default=600)
    p.add_argument("--attempt", default="")
    a = p.parse_args()
    config = f"{a.kind}-{a.device}-t{a.threads}-b{a.beam}"
    checkpoint_stem = f"{config}-{a.attempt}" if a.attempt else config
    checkpoint = OUT / f"{checkpoint_stem}.jsonl"
    OUT.mkdir(parents=True, exist_ok=True)
    quiet_check(checkpoint_stem)
    truth = {x["clip_id"]: x for x in __import__("library_timing").selected()}
    chosen = [x for x in truth.values() if a.clips == "all" or x["class"] == a.clips]
    existing = set()
    if checkpoint.exists():
        for line in checkpoint.read_text(encoding="utf-8-sig").splitlines():
            try:
                row = json.loads(line)
                valid_runtime = (
                    a.kind not in ("ort-turbo", "ort-small") or
                    row.get("provider_verified") is True)
                if row.get("status") == "ok" and valid_runtime:
                    existing.add((row.get("clip_id"), int(row.get("repeat", 1))))
            except (ValueError, json.JSONDecodeError):
                pass
    env = os.environ.copy()
    env.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", HF_HUB_DISABLE_TELEMETRY="1")
    with checkpoint.open("a", encoding="utf-8", buffering=1) as out:
        for item in chosen:
            reps = 3 if item["class"] == "long" else 5
            for repeat in range(1, reps + 1):
                if (item["clip_id"], repeat) in existing:
                    continue
                worker_out = OUT / f".{checkpoint_stem}-{item['clip_id']}-r{repeat}.worker.json"
                child_python = worker_python(a.kind, a.device)
                command = [str(child_python), str(HERE / "library_worker.py"),
                           "--kind", a.kind, "--device", a.device, "--threads", str(a.threads),
                           "--beam", str(a.beam), "--clip-id", item["clip_id"], "--out", str(worker_out)]
                started = datetime.now(timezone.utc).isoformat()
                t0 = time.perf_counter()
                try:
                    result = subprocess.run(command, capture_output=True, text=True,
                                            env=env, timeout=a.timeout, check=False)
                    elapsed = time.perf_counter() - t0
                    if worker_out.is_file():
                        row = json.loads(worker_out.read_text(encoding="utf-8"))
                        row["status"] = row["status"] if result.returncode == 0 else "child_nonzero_exit"
                    else:
                        row = {"status": "child_nonzero_exit", "error": result.stderr[-4000:]}
                    row["child_wall_seconds_including_load"] = elapsed
                    row["child_exit_code"] = result.returncode
                except subprocess.TimeoutExpired as exc:
                    elapsed = time.perf_counter() - t0
                    row = {"status": "timeout", "error": "per-run child hard timeout",
                           "timeout_seconds": a.timeout, "child_stdout": str(exc.stdout or "")[-1000:],
                           "child_stderr": str(exc.stderr or "")[-4000:]}
                finally:
                    worker_out.unlink(missing_ok=True)
                row.update({"config": config, "kind": a.kind, "device": a.device,
                            "threads": a.threads, "beam": a.beam,
                            "clip_id": item["clip_id"], "class": item["class"],
                            "repeat": repeat, "started_utc": started,
                            "attempt": a.attempt or "initial",
                            "counter_sampling_during_timing": False})
                out.write(json.dumps(row, ensure_ascii=False) + "\n")
                out.flush()
                print(json.dumps({"config": config, "clip": item["clip_id"],
                                  "repeat": repeat, "status": row["status"]}), flush=True)
    expected = {(x["clip_id"], n) for x in chosen
                for n in range(1, (3 if x["class"] == "long" else 5) + 1)}
    successful = set()
    if checkpoint.exists():
        for line in checkpoint.read_text(encoding="utf-8-sig").splitlines():
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            valid_runtime = (
                a.kind not in ("ort-turbo", "ort-small") or
                row.get("provider_verified") is True)
            if row.get("config") == config and row.get("status") == "ok" and valid_runtime:
                successful.add((row.get("clip_id"), int(row.get("repeat", 1))))
    missing = sorted(expected - successful)
    if missing:
        print(json.dumps({"config": config, "event": "incomplete",
                          "successful": len(expected & successful), "expected": len(expected),
                          "missing": missing}), flush=True)
        raise SystemExit(2)


if __name__ == "__main__":
    main()
