"""Acquire the shared benchmark lock, then capture PID-filtered PDH counters."""
import os
import pathlib
import subprocess
import time

lock = pathlib.Path(r"C:\scratch\asr50\timing.lock.d")
deadline = time.monotonic() + 1200
while True:
    try:
        lock.mkdir()
        (lock / "owner.txt").write_text("WP9 GPU counter capture", encoding="utf-8")
        break
    except FileExistsError:
        if time.time() - lock.stat().st_mtime > 1800:
            print("Stale lock (>30 minutes); removing it")
            (lock / "owner.txt").unlink(missing_ok=True)
            lock.rmdir()
            continue
        if time.monotonic() > deadline:
            raise TimeoutError("timing lock wait exceeded 20 minutes")
        time.sleep(5)
try:
    script = pathlib.Path(__file__).with_name("gpu_capture.ps1")
    subprocess.run(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
                    "-File", str(script)], check=True)
finally:
    (lock / "owner.txt").unlink(missing_ok=True)
    lock.rmdir()
