"""Short, process-filtered Vulkan ASR evidence pass for WP24."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import time
from pathlib import Path

import numpy as np
import soundfile as sf

ROOT = Path(r"C:\scratch\asr50\WP24")
BASE = Path(r"C:\scratch\asr50")
SAMPLER = Path(r"C:\code\muteinous-spike50\spike\asr50\speed\sample_gpu_pid_wait.ps1")
BIN = BASE / "WP2" / "artifacts" / "whisper-vulkan-dl-windows-x64" / "whisper-cli.exe"


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--model", choices=("turbo", "small-en"), required=True)
    a = p.parse_args()
    rows = json.loads((ROOT / "sample_manifest.json").read_text(encoding="utf-8"))["sampled"]
    model_rel = (
        "whisper-large-v3-turbo-whisper-cpp-q5-0/ggml-large-v3-turbo-q5_0.bin"
        if a.model == "turbo" else
        "whisper-small-en-whisper-cpp-q5-1/ggml-small.en-q5_1.bin"
    )
    dest = ROOT / "gpu_evidence" / a.model
    dest.mkdir(parents=True, exist_ok=True)
    probe_rows = sorted((r for r in rows if r["sample_kind"] == "speech"),
                        key=lambda r: r["duration_s"], reverse=True)[:4]
    chunks = []
    repeats = 1 if a.model == "turbo" else 6
    for _ in range(repeats):
        for item in probe_rows:
            audio, sr = sf.read(item["wav"], dtype="float32")
            if sr != 16000:
                raise ValueError("probe requires 16 kHz audio")
            chunks.extend((audio, np.zeros(1600, dtype=np.float32)))
    probe_audio = dest / "probe_audio.wav"
    sf.write(probe_audio, np.concatenate(chunks), 16000, subtype="FLOAT")
    pid_file, ready_file = dest / "target.pid", dest / "sampler.ready"
    counters = dest / "pid-counters.jsonl"
    pid_file.unlink(missing_ok=True)
    ready_file.unlink(missing_ok=True)
    outbase = dest / "probe"
    dtw = "large.v3.turbo" if a.model == "turbo" else "small.en"
    command = [str(BIN), "-m", str(BASE / "models" / model_rel), "-f", str(probe_audio),
               "-l", "en", "-t", "4", "-ojf", "-of", str(outbase), "-nfa", "-dtw", dtw]
    command += ["-dev", "0"]
    env = os.environ | {"HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1",
                        "HF_HUB_DISABLE_TELEMETRY": "1", "GGML_VK_VISIBLE_DEVICES": "0"}
    sampler = subprocess.Popen(
        ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
         str(SAMPLER), "-PidFile", str(pid_file), "-ReadyFile", str(ready_file),
         "-OutFile", str(counters)],
        stdout=subprocess.DEVNULL,
        stderr=(dest / "sampler.stderr").open("wb"),
    )
    deadline = time.monotonic() + 20
    while not ready_file.exists() and sampler.poll() is None and time.monotonic() < deadline:
        time.sleep(.1)
    started = time.perf_counter()
    try:
        candidate = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                     env=env)
        pid_file.write_text(str(candidate.pid), encoding="ascii")
        stdout, stderr = candidate.communicate(timeout=600)
        elapsed = time.perf_counter() - started
        stdout = stdout.decode("utf-8", errors="replace")
        stderr = stderr.decode("utf-8", errors="replace")
        log = stdout + stderr
        (dest / "candidate.log").write_text(log, encoding="utf-8")
        (dest / "candidate.stdout").write_text(stdout, encoding="utf-8")
        (dest / "candidate.stderr").write_text(stderr, encoding="utf-8")
        if candidate.returncode:
            raise RuntimeError(f"whisper-cli exit {candidate.returncode}")
    finally:
        if sampler.poll() is None:
            sampler.terminate()
            try:
                sampler.wait(timeout=5)
            except subprocess.TimeoutExpired:
                sampler.kill()
                sampler.wait()
    entries = []
    if counters.is_file():
        for line in counters.read_text(encoding="utf-8-sig", errors="replace").splitlines():
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    metrics = {
        "model": a.model,
        "clip_count": len(probe_rows),
        "repeat_count": repeats,
        "audio_duration_s": len(np.concatenate(chunks)) / 16000,
        "elapsed_s_observation_only": elapsed,
        "pid": int(pid_file.read_text(encoding="ascii").strip()),
        "exit_code": candidate.returncode,
        "vulkan0_log_line": "using Vulkan0 backend" in log,
        "counter_records": len(entries),
        "pid_matched_gpu_engine_max_pct": max(
            (float(x["value"]) for x in entries
             if x.get("counter_set") == "GPU Engine" and x.get("pid_matched")
             and isinstance(x.get("value"), (float, int))), default=None),
        "pid_matched_dedicated_bytes_max": max(
            (float(x["value"]) for x in entries
             if x.get("counter_set") == "GPU Process Memory" and x.get("pid_matched")
             and isinstance(x.get("value"), (float, int))), default=None),
        "counter_errors": sum("error" in x for x in entries),
    }
    (dest / "evidence.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    print(json.dumps(metrics))


if __name__ == "__main__":
    main()
