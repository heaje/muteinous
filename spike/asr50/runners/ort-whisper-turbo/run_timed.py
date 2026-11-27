"""Run one measured child while holding the shared benchmark timing lock."""
import os
import subprocess
import sys
import time

lock = r"C:\scratch\asr50\timing.lock.d"
deadline = time.monotonic() + 20 * 60
while True:
    try:
        os.mkdir(lock)
        break
    except FileExistsError:
        if time.monotonic() >= deadline:
            raise SystemExit("timing lock wait exceeded 20 minutes")
        time.sleep(5)
try:
    env = os.environ.copy()
    env.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", HF_HUB_DISABLE_TELEMETRY="1")
    result = subprocess.run(sys.argv[1:], env=env, check=False)
    raise SystemExit(result.returncode)
finally:
    os.rmdir(lock)
