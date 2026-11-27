"""Run the WP22 matrix serially; each config owns its own quiet check/checkpoint."""
import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
PY = Path(r"C:\scratch\asr50\WP10\venv\Scripts\python.exe")
OUT = Path(r"C:\scratch\asr50\WP22")


def plan():
    cli = []
    # Preserve CPU/GPU alternation while pairing model/thread settings.
    for threads in (12, 4):
        cli.extend([
            ["--model", "turbo", "--device", "vulkan", "--threads", str(threads)],
            ["--model", "turbo", "--device", "cpu", "--threads", str(threads)],
            ["--model", "small-en", "--device", "vulkan", "--threads", str(threads)],
            ["--model", "small-en", "--device", "cpu", "--threads", str(threads)],
        ])
    library = []
    for kind in ("ort-turbo", "ort-small"):
        for device in ("dml", "cpu"):
            for threads in (12, 4):
                library.append(["--kind", kind, "--device", device, "--threads", str(threads)])
    for kind in ("parakeet", "moonshine", "vad", "aligner"):
        for threads in (12, 4):
            library.append(["--kind", kind, "--device", "cpu", "--threads", str(threads)])
    for beam in (1, 5):
        for threads in (12, 4):
            library.append(["--kind", "faster", "--device", "cpu", "--threads", str(threads),
                            "--beam", str(beam)])
    return cli, library


def run(cmd, log_path, timeout):
    start = time.perf_counter()
    try:
        with log_path.open("w", encoding="utf-8") as log:
            p = subprocess.run(cmd, stdout=log, stderr=subprocess.STDOUT, timeout=timeout, check=False)
        return {"status": "completed" if p.returncode == 0 else "driver_exit",
                "exit_code": p.returncode, "elapsed_s": time.perf_counter() - start}
    except subprocess.TimeoutExpired:
        return {"status": "driver_timeout", "exit_code": None,
                "elapsed_s": time.perf_counter() - start}


def gpu_telemetry(model, threads, config):
    command = [str(PY), str(HERE / "gpu_telemetry_driver.py"),
               "--model", model, "--threads", str(threads), "--config", config]
    return run(command, OUT / f"telemetry-{config}.log", 700)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--resume-at", default="", help="first config label to run")
    a = p.parse_args()
    cli, library = plan()
    tasks = []
    for argv in cli:
        label = f"{argv[1]}-{argv[3]}-t{argv[5]}"
        command = [sys.executable, str(HERE / "whisper_cli_driver.py"), *argv]
        # The prior PowerShell CPU/4 run was explicitly steering-cancelled;
        # preserve it and give the Python replacement a separate clean ledger.
        if label == "turbo-cpu-t4":
            command += ["--attempt", "clean-python"]
        tasks.append((label, command))
    for argv in library:
        kind = argv[1]
        device = argv[3]
        threads = argv[5]
        beam = argv[7] if "--beam" in argv else "5"
        label = f"{kind}-{device}-t{threads}-b{beam}"
        tasks.append((label, [str(PY), str(HERE / "library_driver.py"), *argv]))
    started = time.perf_counter()
    summary = OUT / "matrix-progress.jsonl"
    resume = not a.resume_at
    for label, command in tasks:
        if not resume:
            if label != a.resume_at:
                continue
            resume = True
        task_start = time.perf_counter()
        print(json.dumps({"event": "start", "config": label}), flush=True)
        # Per-run timeouts live in the drivers; this is only an outer recovery limit.
        timeout = 129600
        result = run(command, OUT / f"driver-{label}.log", timeout)
        if result["status"] == "completed" and "-vulkan-" in f"-{label}-":
            model = "small-en" if label.startswith("small-en-") else "turbo"
            threads = label.rsplit("-t", 1)[1]
            result["gpu_telemetry"] = gpu_telemetry(model, threads, label)
        row = {"config": label, **result, "started_elapsed_s": task_start,
               "finished_elapsed_s": time.perf_counter(), "command": command}
        with summary.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row) + "\n")
            f.flush()
        print(json.dumps({"event": "finish", **row}), flush=True)
    # Drift rerun of the first planned config, explicitly last.
    drift_label = "turbo-vulkan-t12-drift"
    cmd = [sys.executable, str(HERE / "whisper_cli_driver.py"), "--model", "turbo",
           "--device", "vulkan", "--threads", "12", "--drift"]
    if resume:
        drift_result = run(cmd, OUT / f"driver-{drift_label}.log", 129600)
        if drift_result["status"] == "completed":
            drift_result["gpu_telemetry"] = gpu_telemetry("turbo", "12", drift_label)
        row = {"config": drift_label, **drift_result,
               "total_elapsed_s": time.perf_counter() - started, "command": cmd}
        with summary.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row) + "\n")
            f.flush()
        print(json.dumps({"event": "finish", **row}), flush=True)


if __name__ == "__main__":
    main()
