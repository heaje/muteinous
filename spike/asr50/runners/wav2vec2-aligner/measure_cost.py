"""Locked CPU latency/RAM measurements; launch separately for each thread count."""
import argparse
import ctypes
import json
import os
import time
from pathlib import Path
import sys

import numpy as np
import soundfile as sf

sys.path.insert(0, str(Path(__file__).resolve().parent))
from aligner import Aligner

BASE = Path(r"C:\scratch\asr50")
MODEL = BASE / "models" / "wav2vec2-base-960h-onnx"
AUDIO = BASE / "WP6" / "audio16k"
GT = json.loads((AUDIO / "ground_truth.json").read_text(encoding="utf-8"))["clips"]


def peak_working_set():
    class PM(ctypes.Structure):
        _fields_ = [("cb", ctypes.c_ulong), ("PageFaultCount", ctypes.c_ulong),
                    ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                    ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                    ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t)]
    pm = PM()
    pm.cb = ctypes.sizeof(pm)
    ctypes.windll.psapi.GetProcessMemoryInfo(ctypes.windll.kernel32.GetCurrentProcess(),
                                              ctypes.byref(pm), pm.cb)
    return int(pm.PeakWorkingSetSize)


def acquire_lock():
    lock = Path(r"C:\scratch\asr50\timing.lock.d")
    deadline = time.monotonic() + 20 * 60
    while True:
        try:
            os.mkdir(lock)
            return lock
        except FileExistsError:
            if time.time() - lock.stat().st_mtime > 1800:
                os.rmdir(lock)
                print("Removed timing lock older than 30 minutes")
                continue
            if time.monotonic() >= deadline:
                raise TimeoutError("timing lock acquisition exceeded 20 minutes")
            time.sleep(5)


def passes(aligner, audios):
    for audio, transcript in audios:
        aligner.align(audio, transcript)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--threads", type=int, required=True)
    args = parser.parse_args()
    os.environ.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", HF_HUB_DISABLE_TELEMETRY="1")
    load_start = time.perf_counter()
    aligner = Aligner(MODEL / "model.onnx", MODEL / "vocab.json", args.threads)
    load_s = time.perf_counter() - load_start
    audios = []
    for clip in GT:
        wav, rate = sf.read(AUDIO / f"{clip['clip_id']}.wav", dtype="float32")
        audios.append((wav, clip["transcript"]))
    lock = acquire_lock()
    try:
        cold_start = time.perf_counter()
        passes(aligner, audios)
        cold_s = time.perf_counter() - cold_start
        warm = []
        for _ in range(3):
            start = time.perf_counter()
            passes(aligner, audios)
            warm.append(time.perf_counter() - start)
    finally:
        os.rmdir(lock)
    audio_s = sum(len(a) for a, _ in audios) / 16000
    import onnxruntime
    result = {"threads": args.threads, "runtime": "onnxruntime", "version": onnxruntime.__version__,
              "model_load_s": load_s, "cold_corpus_s": cold_s, "warm_corpus_s": warm,
              "audio_seconds": audio_s, "cold_rtf": cold_s / audio_s,
              "warm_rtf": [v / audio_s for v in warm],
              "warm_cpu_seconds_per_audio_second": float(np.mean(warm)) / audio_s,
              "peak_working_set_bytes": peak_working_set(), "timing_lock": str(lock)}
    out = BASE / "results" / "wav2vec2-aligner" / "cost"
    out.mkdir(parents=True, exist_ok=True)
    (out / f"threads-{args.threads}.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
