"""Collect process/GPU telemetry in separate, untimed whisper.cpp passes."""
import json
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
PY = Path(r"C:\scratch\asr50\WP10\venv\Scripts\python.exe")
OUT = Path(r"C:\scratch\asr50\WP22")
CONFIGS = [
    ("turbo", "vulkan", 12, "turbo-vulkan-t12"),
    ("turbo", "cpu", 12, "turbo-cpu-t12"),
    ("turbo", "vulkan", 4, "turbo-vulkan-t4"),
    ("turbo", "cpu", 4, "turbo-cpu-t4-clean-python"),
    ("small-en", "cpu", 12, "small-en-cpu-t12"),
    ("small-en", "vulkan", 12, "small-en-vulkan-t12"),
    ("small-en", "vulkan", 4, "small-en-vulkan-t4"),
    ("small-en", "cpu", 4, "small-en-cpu-t4"),
    ("turbo", "vulkan", 12, "turbo-vulkan-t12-drift"),
]


def main():
    from whisper_cli_driver import preflight

    progress = OUT / "cli-telemetry-progress.jsonl"
    for model, device, threads, config in CONFIGS:
        preflight(f"{config}-telemetry-preflight", OUT)
        cmd = [str(PY), str(HERE / "gpu_telemetry_driver.py"),
               "--model", model, "--device", device, "--threads", str(threads),
               "--config", config]
        logfile = OUT / f"telemetry-{config}-python.log"
        start = time.perf_counter()
        try:
            with logfile.open("w", encoding="utf-8") as log:
                proc = subprocess.run(cmd, stdout=log, stderr=subprocess.STDOUT,
                                      timeout=700, check=False)
            row = {"config": config, "device": device, "status": "complete" if proc.returncode == 0
                   else "telemetry_failed", "exit_code": proc.returncode,
                   "elapsed_s": time.perf_counter() - start, "command": cmd}
        except subprocess.TimeoutExpired:
            row = {"config": config, "device": device, "status": "telemetry_timeout",
                   "elapsed_s": time.perf_counter() - start, "command": cmd}
        with progress.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row) + "\n")
            f.flush()
        print(json.dumps(row), flush=True)


if __name__ == "__main__":
    main()
