"""Serialize measured candidate process launches using the shared timing lock."""
import os
import pathlib
import subprocess
import sys
import time

LOCK = pathlib.Path(r"C:\scratch\asr50\timing.lock.d")
PYTHON = pathlib.Path(r"C:\scratch\asr50\WP9\venv\Scripts\python.exe")
RUNNER = pathlib.Path(__file__).with_name("run.py")
SCRATCH = pathlib.Path(r"C:\scratch\asr50\WP9")


def acquire():
    deadline = time.monotonic() + 20 * 60
    while True:
        try:
            LOCK.mkdir()
            (LOCK / "owner.txt").write_text(
                f"WP9 pid={os.getpid()} at={time.time()}\n", encoding="utf-8")
            return
        except FileExistsError:
            try:
                age = time.time() - LOCK.stat().st_mtime
                if age > 1800:
                    print(f"Removing stale timing lock (age {age:.1f}s)", flush=True)
                    (LOCK / "owner.txt").unlink(missing_ok=True)
                    LOCK.rmdir()
                    continue
            except FileNotFoundError:
                continue
            if time.monotonic() >= deadline:
                raise TimeoutError("gave up waiting for timing.lock.d after 20 minutes")
            time.sleep(5)


def run(tag, threads, passes, clips=None, provider="cpu", run_kind="cold"):
    out = SCRATCH / tag
    log = SCRATCH / f"{tag}.log"
    command = [str(PYTHON), "-I", str(RUNNER), "--threads", str(threads),
               "--provider", provider, "--passes", str(passes), "--run-kind",
               run_kind, "--out", str(out)]
    if clips:
        command += ["--clips", *clips]
    env = os.environ.copy()
    env.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1",
               HF_HUB_DISABLE_TELEMETRY="1")
    start = time.perf_counter()
    with log.open("w", encoding="utf-8") as fp:
        result = subprocess.run(command, env=env, stdout=fp, stderr=subprocess.STDOUT)
    wall = time.perf_counter() - start
    print(f"{tag}: exit={result.returncode} wall={wall:.3f}s log={log}", flush=True)
    if result.returncode:
        raise RuntimeError(f"run failed; inspect {log}")


def main():
    acquire()
    try:
        # Focused CPU scaling subset, then a fresh cold process and a separate
        # warmed process (3 measured repeats after that process's first pass).
        subset = ["clean_001", "noise_0db", "quiet_m30"]
        for threads in (4, 12, 24):
            run(f"thread-{threads}", threads, 1, subset)
        run("cold_cpu_t4", 4, 1)
        run("warm_cpu_t4", 4, 4, run_kind="warm")
    finally:
        (LOCK / "owner.txt").unlink(missing_ok=True)
        LOCK.rmdir()


if __name__ == "__main__":
    main()
