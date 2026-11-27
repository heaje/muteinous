"""Timed whisper.cpp invocation with no counter polling in the timed window."""
import argparse
import ctypes
import json
import os
import subprocess
import time
from pathlib import Path
from ctypes import wintypes


class FILETIME(ctypes.Structure):
    _fields_ = [("low", ctypes.c_uint32), ("high", ctypes.c_uint32)]


class PROCESS_MEMORY_COUNTERS(ctypes.Structure):
    _fields_ = [
        ("cb", ctypes.c_uint32), ("PageFaultCount", ctypes.c_uint32),
        ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
        ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t),
    ]


def filetime_seconds(value):
    return ((int(value.high) << 32) | int(value.low)) / 10_000_000


def process_stats(handle):
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.GetProcessTimes.argtypes = [
        wintypes.HANDLE, ctypes.POINTER(FILETIME), ctypes.POINTER(FILETIME),
        ctypes.POINTER(FILETIME), ctypes.POINTER(FILETIME)]
    kernel32.GetProcessTimes.restype = wintypes.BOOL
    kernel, user = FILETIME(), FILETIME()
    creation, exit_time = FILETIME(), FILETIME()
    cpu = None
    try:
        ok = kernel32.GetProcessTimes(
            wintypes.HANDLE(int(handle)), ctypes.byref(creation), ctypes.byref(exit_time),
            ctypes.byref(kernel), ctypes.byref(user))
        if ok:
            cpu = filetime_seconds(kernel) + filetime_seconds(user)
    except Exception:
        pass
    memory = PROCESS_MEMORY_COUNTERS()
    memory.cb = ctypes.sizeof(memory)
    peak = None
    try:
        ok = ctypes.windll.psapi.GetProcessMemoryInfo(
            ctypes.c_void_p(handle), ctypes.byref(memory), memory.cb)
        if ok:
            peak = int(memory.PeakWorkingSetSize)
    except Exception:
        pass
    return cpu, peak


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--stdout", required=True, type=Path)
    parser.add_argument("--stderr", required=True, type=Path)
    parser.add_argument("--meta", required=True, type=Path)
    parser.add_argument("--timeout", type=float, default=600.0)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command
    if command and command[0] == "--":
        command = command[1:]
    if not command:
        raise SystemExit("missing command")
    os.environ.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1",
                      HF_HUB_DISABLE_TELEMETRY="1")
    args.stdout.parent.mkdir(parents=True, exist_ok=True)
    args.stderr.parent.mkdir(parents=True, exist_ok=True)
    status = "ok"
    timed_out = False
    with args.stdout.open("wb") as stdout, args.stderr.open("wb") as stderr:
        start = time.perf_counter()
        process = subprocess.Popen(command, stdout=stdout, stderr=stderr,
                                   env=os.environ.copy())
        pid = process.pid
        try:
            code = process.wait(timeout=args.timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            status = "timeout"
            process.terminate()
            try:
                code = process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                code = process.wait()
        wall = time.perf_counter() - start
        cpu, peak = process_stats(process._handle)
    if not timed_out and code != 0:
        status = "nonzero_exit"
    row = {
        "status": status, "pid": pid, "exit_code": code,
        "wall_seconds": wall, "timeout_seconds": args.timeout,
        "process_cpu_seconds": cpu, "peak_working_set_bytes": peak,
        "cores_used": cpu / wall if cpu is not None and wall > 0 else None,
        "timer": "time.perf_counter",
        "counter_sampling_during_timing": False,
        "command": command,
    }
    args.meta.write_text(json.dumps(row, indent=2), encoding="utf-8")
    print(json.dumps(row), flush=True)
    raise SystemExit(124 if timed_out else (code or 0))


if __name__ == "__main__":
    main()
