"""Clean full Turbo/Vulkan/12 ledger followed by the required final drift rerun."""
import json
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = Path(r"C:\scratch\asr50\WP22")
PY = Path(r"C:\scratch\asr50\WP10\venv\Scripts\python.exe")
COMMANDS = [
    ("turbo-vulkan-t12-direct-python", [
        str(PY), str(HERE / "whisper_cli_driver.py"), "--model", "turbo",
        "--device", "vulkan", "--threads", "12", "--attempt", "direct-python"]),
    ("turbo-vulkan-t12-drift-clean-python", [
        str(PY), str(HERE / "whisper_cli_driver.py"), "--model", "turbo",
        "--device", "vulkan", "--threads", "12", "--drift", "--attempt", "clean-python"]),
]


def main():
    progress = OUT / "final-cli-reruns.jsonl"
    for config, command in COMMANDS:
        started = time.perf_counter()
        logpath = OUT / f"final-driver-{config}.log"
        try:
            with logpath.open("w", encoding="utf-8") as log:
                p = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT,
                                   timeout=129600, check=False)
            row = {"config": config, "status": "complete" if p.returncode == 0 else "failed",
                   "exit_code": p.returncode, "elapsed_s": time.perf_counter() - started}
        except subprocess.TimeoutExpired:
            row = {"config": config, "status": "timeout",
                   "elapsed_s": time.perf_counter() - started}
        row["command"] = command
        with progress.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row) + "\n")
            f.flush()
        print(json.dumps(row), flush=True)
        if row["status"] != "complete":
            break


if __name__ == "__main__":
    main()
