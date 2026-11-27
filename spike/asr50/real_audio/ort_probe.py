"""Run an existing offline ORT Whisper runner on a short sample under PID counters."""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import time
from pathlib import Path

ROOT = Path(r"C:\scratch\asr50\WP24")
SAMPLER = Path(r"C:\code\muteinous-spike50\spike\asr50\speed\sample_gpu_pid_wait.ps1")
SMALL_RUNNER = Path(r"C:\code\muteinous-spike50\spike\asr50\runners\ort-whisper-small-en\run.py")
TURBO_RUNNER = Path(r"C:\code\muteinous-spike50\spike\asr50\runners\ort-whisper-turbo\runner_v3.py")
SMALL_PYTHON = Path(r"C:\scratch\asr50\WP13\venv-dml\Scripts\python.exe")
TURBO_PYTHON = Path(r"C:\scratch\asr50\WP23\venv_ort\Scripts\python.exe")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", choices=("small-en", "turbo"), required=True)
    parser.add_argument("--count", type=int, default=8)
    args = parser.parse_args()
    rows = json.loads((ROOT / "sample_manifest.json").read_text(encoding="utf-8"))["sampled"]
    chosen = [r for r in rows if r["sample_kind"] == "speech"][:args.count]
    ids = [r["clip_id"] for r in chosen]
    dest = ROOT / "gpu_evidence" / f"ort-{args.model}"
    dest.mkdir(parents=True, exist_ok=True)
    pid_file, ready_file = dest / "target.pid", dest / "sampler.ready"
    counter_file = dest / "pid-counters.jsonl"
    pid_file.unlink(missing_ok=True)
    ready_file.unlink(missing_ok=True)
    sampler_err = (dest / "sampler.stderr").open("wb")
    sampler = subprocess.Popen(
        ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
         str(SAMPLER), "-PidFile", str(pid_file), "-ReadyFile", str(ready_file),
         "-OutFile", str(counter_file)],
        stdout=subprocess.DEVNULL, stderr=sampler_err,
    )
    deadline = time.monotonic() + 20
    while not ready_file.exists() and sampler.poll() is None and time.monotonic() < deadline:
        time.sleep(.1)
    if args.model == "small-en":
        python, runner = SMALL_PYTHON, SMALL_RUNNER
        command = [str(python), "-I", str(runner), "--device", "dml",
                   "--threads", "4", "--audio-root", str(ROOT / "audio16k"),
                   "--out", str(dest / "results"), "--kind", "gpu-probe", "--policy", "on"]
        for clip_id in ids:
            command += ["--clip-id", clip_id]
    else:
        python, runner = TURBO_PYTHON, TURBO_RUNNER
        probe_root = dest / "audio"
        probe_root.mkdir(parents=True, exist_ok=True)
        truth = json.loads((ROOT / "ground_truth.json").read_text(encoding="utf-8"))
        by_id = {r["clip_id"]: r for r in truth["clips"]}
        small_truth = {**{k: v for k, v in truth.items() if k != "clips"},
                       "clips": [by_id[clip_id] for clip_id in ids]}
        for clip in small_truth["clips"]:
            shutil.copyfile(ROOT / "audio16k" / clip["wav"], probe_root / clip["wav"])
        gt_path = probe_root / "ground_truth.json"
        gt_path.write_text(json.dumps(small_truth, ensure_ascii=False), encoding="utf-8")
        command = [str(python), "-I", str(runner), "--device", "dml",
                   "--corpus-root", str(probe_root), "--output-root", str(dest / "results"),
                   "--ground-truth", str(gt_path)]
    env = os.environ | {"HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1",
                        "HF_HUB_DISABLE_TELEMETRY": "1"}
    started = time.perf_counter()
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                               env=env)
    pid_file.write_text(str(process.pid), encoding="ascii")
    try:
        stdout, _ = process.communicate(timeout=1800)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()
        raise
    elapsed = time.perf_counter() - started
    (dest / "runner.log").write_bytes(stdout)
    if sampler.poll() is None:
        sampler.terminate()
        try:
            sampler.wait(timeout=5)
        except subprocess.TimeoutExpired:
            sampler.kill()
            sampler.wait()
    sampler_err.close()
    counter_rows = []
    if counter_file.exists():
        for line in counter_file.read_text(encoding="utf-8-sig", errors="replace").splitlines():
            try:
                counter_rows.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    result = {
        "model": args.model, "sample_clips": len(ids), "pid": process.pid,
        "exit_code": process.returncode, "elapsed_s_observation_only": elapsed,
        "counter_records": len(counter_rows),
        "pid_matched_gpu_engine_max_pct": max(
            (float(x["value"]) for x in counter_rows
             if x.get("counter_set") == "GPU Engine" and x.get("pid_matched")
             and isinstance(x.get("value"), (float, int))), default=None),
        "pid_matched_dedicated_bytes_max": max(
            (float(x["value"]) for x in counter_rows
             if x.get("counter_set") == "GPU Process Memory" and x.get("pid_matched")
             and isinstance(x.get("value"), (float, int))), default=None),
        "counter_errors": sum("error" in x for x in counter_rows),
    }
    (dest / "evidence.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result))


if __name__ == "__main__":
    main()
