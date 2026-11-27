"""Separate untimed Vulkan pass with a below-normal PID-scoped sampler watchdog."""
import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import psutil

BASE = Path(r"C:\scratch\asr50")
HERE = Path(__file__).resolve().parent
OUT = BASE / "WP22"


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--model", choices=("turbo", "small-en"), required=True)
    p.add_argument("--threads", type=int, choices=(4, 12), required=True)
    p.add_argument("--config", required=True)
    p.add_argument("--device", choices=("cpu", "vulkan"), default="vulkan")
    a = p.parse_args()
    model_rel = ("whisper-large-v3-turbo-whisper-cpp-q5-0/ggml-large-v3-turbo-q5_0.bin"
                 if a.model == "turbo" else
                 "whisper-small-en-whisper-cpp-q5-1/ggml-small.en-q5_1.bin")
    exe = BASE / "WP2" / "artifacts" / (
        "whisper-vulkan-dl-windows-x64" if a.device == "vulkan" else
        "whisper-cpu-dl-windows-x64") / "whisper-cli.exe"
    model = BASE / "models" / model_rel
    clip = "natural_sentences_00"
    corpus = BASE / "corpus_v2_frozen"
    dest = OUT / f"{a.config}-{'gpu' if a.device == 'vulkan' else 'system'}-sample-python"
    dest.mkdir(parents=True, exist_ok=True)
    prefix = dest / clip
    counters = dest / "pid-counters.jsonl"
    sampler_script = HERE / "sample_gpu_pid_wait.ps1"
    pid_file = dest / "target.pid"
    ready_file = dest / "sampler.ready"
    pid_file.unlink(missing_ok=True)
    ready_file.unlink(missing_ok=True)
    sampler_stderr = (dest / "sampler.stderr").open("wb")
    env = os.environ.copy()
    env.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1",
               HF_HUB_DISABLE_TELEMETRY="1", GGML_VK_VISIBLE_DEVICES="0")
    cmd = [str(exe), "-m", str(model), "-f", str(corpus / f"{clip}.wav"),
           "-l", "en", "-t", str(a.threads), "-ojf", "-of", str(prefix)]
    cmd += ["-dev", "0"] if a.device == "vulkan" else ["-ng"]
    with (dest / "candidate.stdout").open("wb") as stdout, (dest / "candidate.stderr").open("wb") as stderr:
        sampler = None
        sampler_status = "not_required" if a.device == "cpu" else "starting"
        sampler_started = datetime.now(timezone.utc).isoformat()
        if a.device == "vulkan":
            sampler_cmd = ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
                           "-File", str(sampler_script), "-PidFile", str(pid_file),
                           "-ReadyFile", str(ready_file),
                           "-OutFile", str(counters)]
            sampler = subprocess.Popen(sampler_cmd, stdout=subprocess.DEVNULL,
                                       stderr=sampler_stderr)
            ready_deadline = time.monotonic() + 20
            while not ready_file.exists() and sampler.poll() is None and time.monotonic() < ready_deadline:
                time.sleep(0.1)
            if ready_file.exists():
                sampler_status = "sampling"
            else:
                sampler_status = "sampler_failed_to_start"
                if sampler.poll() is None:
                    sampler.kill()
                    sampler.wait()
                sampler = None
        candidate = subprocess.Popen(cmd, stdout=stdout, stderr=stderr, env=env)
        if sampler is not None:
            pid_file.write_text(str(candidate.pid), encoding="ascii")
        process = psutil.Process(candidate.pid)
        cpu_start = sum(process.cpu_times()[:2])
        peak_rss = process.memory_info().rss
        deadline = time.monotonic() + 600
        timed_out = False
        last_progress = time.monotonic()
        previous_mtime = None
        candidate_started = time.perf_counter()
        cpu_end = cpu_start
        while candidate.poll() is None:
            if time.monotonic() >= deadline:
                timed_out = True
                candidate.kill()
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
            try:
                cpu_end = sum(process.cpu_times()[:2])
                peak_rss = max(peak_rss, process.memory_info().rss)
            except psutil.NoSuchProcess:
                pass
            time.sleep(0.25)
        exit_code = candidate.wait()
        elapsed = time.perf_counter() - candidate_started
        try:
            cpu_end = sum(process.cpu_times()[:2])
            peak_rss = max(peak_rss, process.memory_info().rss)
        except psutil.NoSuchProcess:
            pass
        if sampler is not None and sampler.poll() is None:
            sampler.kill()
        if sampler is not None:
            try:
                sampler.wait(timeout=5)
            except subprocess.TimeoutExpired:
                sampler.kill()
                sampler.wait()
    sampler_stderr.close()
    samples = []
    if counters.is_file():
        for line in counters.read_text(encoding="utf-8-sig", errors="replace").splitlines():
            try:
                samples.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    engine_adapter = [r.get("value") for r in samples
                      if r.get("counter_set") == "GPU Engine" and isinstance(r.get("value"), (int, float))
                      and any(e in r.get("path", "").lower() for e in ("engtype_3d", "engtype_compute"))]
    engine_pid = [r.get("value") for r in samples if r.get("counter_set") == "GPU Engine"
                  and r.get("pid_matched") and isinstance(r.get("value"), (int, float))]
    dedicated = [r.get("value") for r in samples
                 if r.get("counter_set") == "GPU Process Memory" and
                 isinstance(r.get("value"), (int, float))]
    dedicated_pid = [r.get("value") for r in samples
                     if r.get("counter_set") == "GPU Process Memory" and r.get("pid_matched")
                     and isinstance(r.get("value"), (int, float))]
    stderr_text = (dest / "candidate.stderr").read_text(encoding="utf-8", errors="replace")
    backend_verified = "using Vulkan0 backend" in stderr_text
    cpu_seconds = max(0.0, cpu_end - cpu_start)
    cpu_cores = cpu_seconds / elapsed if elapsed else None
    result = {
        "config": a.config, "clip_id": clip, "candidate_pid": candidate.pid,
        "candidate_exit_code": exit_code, "candidate_timeout": timed_out,
        "device": a.device, "backend_verified": backend_verified,
        "untimed_pass_wall_seconds": elapsed, "process_cpu_seconds": cpu_seconds,
        "process_cores_used": cpu_cores,
        "process_cpu_percent_of_logical": (
            100 * cpu_cores / (psutil.cpu_count(logical=True) or 1) if cpu_cores is not None else None),
        "peak_working_set_bytes": peak_rss,
        "pass": "separate untimed ASR telemetry; excluded from latency/RTF",
        "sampler_started_utc": sampler_started,
        "sampler_priority": "BelowNormal (set inside sampler)" if sampler is not None else None,
        "sampler_status": "stopped_after_candidate" if sampler_status == "sampling" else sampler_status,
        "sample_period_s": 1,
        "watchdog": "sampler killed after >20s without counter-file progress; candidate timeout 600s",
        "counter_records": len(samples), "gpu_engine_sample_count": len(engine_adapter),
        "gpu_pid_engine_sample_count": len(engine_pid),
        "gpu_3d_compute_peak_percent": max(engine_adapter) if engine_adapter else None,
        "gpu_pid_3d_compute_peak_percent": max(engine_pid) if engine_pid else None,
        "dedicated_gpu_bytes_peak": max(dedicated) if dedicated else None,
        "dedicated_gpu_pid_bytes_peak": max(dedicated_pid) if dedicated_pid else None,
        "counter_file": str(counters), "command": cmd,
    }
    (dest / "metadata.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result), flush=True)
    raise SystemExit(0 if exit_code == 0 and not timed_out else 1)


if __name__ == "__main__":
    main()
