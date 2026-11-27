"""Explicitly rerun only library configs missing the 66 required good observations."""
import json
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = Path(r"C:\scratch\asr50\WP22")
PY = Path(r"C:\scratch\asr50\WP10\venv\Scripts\python.exe")

# DML/CPU pairs stay interleaved where an accelerator option exists.
TASKS = [
    ("ort-turbo", "dml", 12, 5), ("ort-turbo", "cpu", 12, 5),
    ("ort-turbo", "dml", 4, 5), ("ort-turbo", "cpu", 4, 5),
    ("ort-small", "dml", 12, 5), ("ort-small", "cpu", 12, 5),
    ("ort-small", "dml", 4, 5), ("ort-small", "cpu", 4, 5),
    ("parakeet", "cpu", 12, 5), ("parakeet", "cpu", 4, 5),
    ("faster", "cpu", 12, 1), ("faster", "cpu", 4, 1),
    ("faster", "cpu", 12, 5), ("faster", "cpu", 4, 5),
    ("moonshine", "cpu", 12, 5), ("moonshine", "cpu", 4, 5),
    ("vad", "cpu", 12, 5), ("vad", "cpu", 4, 5),
    ("aligner", "cpu", 12, 5), ("aligner", "cpu", 4, 5),
]
CLIPS = {"short": 40, "medium": 20, "long": 6}


def status(stem):
    kind = stem.split("-")[0]
    corrected = stem.startswith(("ort-turbo-", "ort-small-", "parakeet-", "vad-"))
    ledger = f"{stem}-corrected-runtime" if corrected else stem
    path = OUT / f"{ledger}.jsonl"
    rows = []
    if path.is_file():
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    is_ort = stem.startswith(("ort-turbo-", "ort-small-"))
    good = {(r.get("clip_id"), int(r.get("repeat", 1))) for r in rows
            if r.get("config") == stem and r.get("status") == "ok" and
            (not is_ort or r.get("provider_verified") is True)}
    expected = sum(CLIPS.values())
    return len(good), expected


def main():
    progress = OUT / "library-retry-progress.jsonl"
    for kind, device, threads, beam in TASKS:
        stem = f"{kind}-{device}-t{threads}-b{beam}"
        good, expected = status(stem)
        if good == expected:
            continue
        command = [str(PY), str(HERE / "library_driver.py"), "--kind", kind,
                   "--device", device, "--threads", str(threads), "--beam", str(beam),
                   "--attempt", "corrected-runtime"]
        started = time.perf_counter()
        print(json.dumps({"event": "retry_start", "config": stem,
                          "prior_successful": good, "expected": expected}), flush=True)
        logfile = OUT / f"retry-driver-{stem}.log"
        try:
            with logfile.open("w", encoding="utf-8") as log:
                p = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT,
                                   timeout=129600, check=False)
            code = p.returncode
            result = "complete" if code == 0 else "still_incomplete"
        except subprocess.TimeoutExpired:
            code, result = None, "driver_timeout"
        row = {"config": stem, "attempt": "corrected-runtime",
               "status": result, "exit_code": code,
               "prior_successful": good, "expected": expected,
               "elapsed_s": time.perf_counter() - started,
               "command": command}
        with progress.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row) + "\n")
            f.flush()
        print(json.dumps(row), flush=True)
        if result != "complete":
            print(json.dumps({"event": "stopped_at_incomplete_config", "config": stem}), flush=True)
            break


if __name__ == "__main__":
    main()
