"""Separate untimed DirectML library pass and low-priority process-scoped sampler."""
import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import psutil

BASE = Path(r"C:\scratch\asr50")
HERE = Path(__file__).resolve().parent
OUT = BASE / "WP22"


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--kind", choices=("ort-turbo", "ort-small"), required=True)
    p.add_argument("--threads", choices=("4", "12"), required=True)
    p.add_argument("--config", required=True)
    a = p.parse_args()
    beam = 5
    child_python = (BASE / "WP12" / "venv" / "dml" / "Scripts" / "python.exe"
                    if a.kind == "ort-turbo" else
                    BASE / "WP13" / "venv-dml" / "Scripts" / "python.exe")
    dest = OUT / f"{a.config}-gpu-sample-python"
    dest.mkdir(parents=True, exist_ok=True)
    counters = dest / "pid-counters.jsonl"
    worker_out = dest / "worker.json"
    pid_file = dest / "target.pid"
    ready_file = dest / "sampler.ready"
    pid_file.unlink(missing_ok=True)
    ready_file.unlink(missing_ok=True)
    sampler_stderr = (dest / "sampler.stderr").open("wb")
    env = os.environ.copy()
    env.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", HF_HUB_DISABLE_TELEMETRY="1")
    worker_cmd = [str(child_python), str(HERE / "library_worker.py"),
                  "--kind", a.kind, "--device", "dml", "--threads", a.threads,
                  "--beam", str(beam), "--clip-id", "natural_sentences_00",
                  "--out", str(worker_out)]
    with (dest / "worker.stdout").open("wb") as stdout:
        sampler_cmd = ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
                       "-File", str(HERE / "sample_gpu_pid_wait.ps1"), "-PidFile", str(pid_file),
                       "-ReadyFile", str(ready_file),
                       "-OutFile", str(counters)]
        sampler = subprocess.Popen(sampler_cmd, stdout=subprocess.DEVNULL, stderr=sampler_stderr)
        ready_deadline = time.monotonic() + 20
        while not ready_file.exists() and sampler.poll() is None and time.monotonic() < ready_deadline:
            time.sleep(0.1)
        sampler_status = "sampling" if ready_file.exists() else "sampler_failed_to_start"
        if not ready_file.exists() and sampler.poll() is None:
            sampler.kill()
            sampler.wait()
            sampler = None
        worker = subprocess.Popen(worker_cmd, stdout=stdout, stderr=(dest / "worker.stderr").open("wb"),
                                  env=env)
        if sampler is not None:
            pid_file.write_text(str(worker.pid), encoding="ascii")
        started = time.monotonic()
        deadline = started + 600
        last_progress = started
        previous_mtime = None
        timed_out = False
        while worker.poll() is None:
            if time.monotonic() >= deadline:
                timed_out = True
                worker.kill()
                break
            try:
                mtime = counters.stat().st_mtime
                if previous_mtime is None or mtime != previous_mtime:
                    previous_mtime = mtime
                    last_progress = time.monotonic()
            except OSError:
                pass
            if sampler is not None and sampler.poll() is not None and sampler_status == "sampling":
                sampler_status = f"sampler_exited_{sampler.returncode}"
            elif sampler is not None and sampler_status == "sampling" and time.monotonic() - last_progress > 20:
                sampler.kill()
                sampler_status = "watchdog_killed_stalled_sampler"
            time.sleep(0.25)
        exit_code = worker.wait()
        if sampler is not None and sampler.poll() is None:
            sampler.kill()
        if sampler is not None:
            try:
                sampler.wait(timeout=5)
            except subprocess.TimeoutExpired:
                sampler.kill()
                sampler.wait()
    sampler_stderr.close()
    telemetry = {}
    if worker_out.is_file():
        try:
            telemetry = json.loads(worker_out.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    samples = []
    if counters.is_file():
        for line in counters.read_text(encoding="utf-8-sig", errors="replace").splitlines():
            try:
                samples.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    engine_adapter = [r["value"] for r in samples if r.get("counter_set") == "GPU Engine"
                      and isinstance(r.get("value"), (int, float))
                      and any(s in r.get("path", "").lower() for s in ("engtype_3d", "engtype_compute"))]
    engine_pid = [r["value"] for r in samples if r.get("counter_set") == "GPU Engine"
                  and r.get("pid_matched") and isinstance(r.get("value"), (int, float))]
    dedicated = [r["value"] for r in samples if r.get("counter_set") == "GPU Process Memory"
                 and isinstance(r.get("value"), (int, float))]
    dedicated_pid = [r["value"] for r in samples
                     if r.get("counter_set") == "GPU Process Memory" and r.get("pid_matched")
                     and isinstance(r.get("value"), (int, float))]
    result = {
        "config": a.config, "kind": a.kind, "device": "dml",
        "clip_id": "natural_sentences_00", "worker_pid": worker.pid,
        "worker_exit_code": exit_code, "worker_timeout": timed_out,
        "pass": "separate untimed DirectML telemetry; inference excluded from benchmark",
        "sampler_status": "stopped_after_candidate" if sampler_status == "sampling" else sampler_status,
        "sampler_priority": "BelowNormal (set inside sampler)",
        "sample_period_s": 1,
        "watchdog": "sampler killed after >20s without counter-file progress; worker timeout 600s",
        "counter_records": len(samples), "gpu_engine_sample_count": len(engine_adapter),
        "gpu_pid_engine_sample_count": len(engine_pid),
        "gpu_3d_compute_peak_percent": max(engine_adapter) if engine_adapter else None,
        "gpu_pid_3d_compute_peak_percent": max(engine_pid) if engine_pid else None,
        "dedicated_gpu_bytes_peak": max(dedicated) if dedicated else None,
        "dedicated_gpu_pid_bytes_peak": max(dedicated_pid) if dedicated_pid else None,
        "worker_latency_s": telemetry.get("wall_seconds"),
        "process_cpu_seconds": telemetry.get("process_cpu_seconds"),
        "process_cores_used": telemetry.get("cores_used"),
        "peak_working_set_bytes": telemetry.get("peak_working_set_bytes"),
        "worker_text_matches_reference": telemetry.get("text_matches_reference"),
        "counter_file": str(counters), "command": worker_cmd,
    }
    (dest / "metadata.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result), flush=True)
    raise SystemExit(0 if exit_code == 0 and not timed_out else 1)


if __name__ == "__main__":
    main()
