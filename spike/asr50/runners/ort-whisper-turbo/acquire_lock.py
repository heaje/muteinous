"""Atomically acquire the shared ASR timing lock; caller releases it."""
import os
import sys
import time

path = r"C:\scratch\asr50\timing.lock.d"
deadline = time.monotonic() + 20 * 60
while True:
    try:
        os.mkdir(path)
        break
    except FileExistsError:
        if time.monotonic() >= deadline:
            print("timing lock wait exceeded 20 minutes", file=sys.stderr)
            raise SystemExit(1)
        time.sleep(5)
