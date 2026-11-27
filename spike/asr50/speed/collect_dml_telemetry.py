"""Collect separate, quiet-checked DirectML GPU telemetry passes."""
import json
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = Path(r"C:\scratch\asr50\WP22")
PY = Path(r"C:\scratch\asr50\WP10\venv\Scripts\python.exe")


def main():
    from whisper_cli_driver import preflight

    for kind in ("ort-turbo", "ort-small"):
        for threads in (12, 4):
            config = f"{kind}-dml-t{threads}-b5"
            preflight(f"{config}-telemetry-preflight", OUT)
            cmd = [str(PY), str(HERE / "dml_telemetry_driver.py"),
                   "--kind", kind, "--threads", str(threads), "--config", config]
            start = time.perf_counter()
            logpath = OUT / f"telemetry-{config}-python.log"
            try:
                with logpath.open("w", encoding="utf-8") as log:
                    p = subprocess.run(cmd, stdout=log, stderr=subprocess.STDOUT,
                                       timeout=700, check=False)
                row = {"config": config, "status": "complete" if p.returncode == 0 else "telemetry_failed",
                       "exit_code": p.returncode, "elapsed_s": time.perf_counter() - start}
            except subprocess.TimeoutExpired:
                row = {"config": config, "status": "telemetry_timeout",
                       "elapsed_s": time.perf_counter() - start}
            with (OUT / "dml-telemetry-progress.jsonl").open("a", encoding="utf-8") as f:
                f.write(json.dumps(row) + "\n")
                f.flush()
            print(json.dumps(row), flush=True)


if __name__ == "__main__":
    main()
