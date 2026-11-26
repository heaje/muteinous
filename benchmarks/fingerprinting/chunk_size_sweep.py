"""Read-size sweep for single-thread BLAKE3 streaming (Issue #17, Stage 2).

Usage: python -I benchmarks/fingerprinting/chunk_size_sweep.py [FILE_MIB]

Warm-cache, synthetic, single-machine evidence only; see docs/source-validity.md.
"""

import os
import statistics
import sys
import tempfile
import time
from pathlib import Path

from blake3 import blake3

SIZES = [4, 16, 64, 128, 256, 512, 1024, 4096, 16384]  # KiB
FILE_MIB = int(sys.argv[1]) if len(sys.argv) > 1 else 1024
REPEATS = 7


def hash_read(path, n):
    h = blake3(max_threads=1)
    with open(path, "rb") as f:
        while c := f.read(n):
            h.update(c)
    return h.hexdigest()


def hash_readinto(path, n):
    h = blake3(max_threads=1)
    buf = bytearray(n)
    mv = memoryview(buf)
    with open(path, "rb", buffering=0) as f:
        while k := f.readinto(buf):
            h.update(mv[:k])
    return h.hexdigest()


def timeit(fn, path, n):
    t = time.perf_counter()
    d = fn(path, n)
    return time.perf_counter() - t, d


def main():
    tmp = Path(tempfile.mkdtemp(prefix="chunksweep_"))
    big = tmp / "big.bin"
    block = os.urandom(1024 * 1024)
    with open(big, "wb") as f:
        for _ in range(FILE_MIB):
            f.write(block)
        f.flush()
        os.fsync(f.fileno())
    ref = hash_read(big, 1 << 20)  # also warms cache
    mb = FILE_MIB * 1.048576
    print(
        f"file {FILE_MIB} MiB, warm cache, {REPEATS} repeats interleaved; MB/s median [min-max]"
    )
    results = {}
    for r in range(REPEATS):
        for name, fn in (("read", hash_read), ("readinto", hash_readinto)):
            for kib in SIZES:
                dt, d = timeit(fn, big, kib * 1024)
                assert d == ref
                results.setdefault((name, kib), []).append(mb / dt)
    for name in ("read", "readinto"):
        print(f"-- {name}")
        for kib in SIZES:
            v = results[(name, kib)]
            tag = "  <- current" if (name == "read" and kib == 1024) else ""
            print(
                f"{kib:>6} KiB  {statistics.median(v):8.0f} [{min(v):.0f}-{max(v):.0f}]{tag}"
            )

    # many small files
    small = tmp / "small"
    small.mkdir()
    files = []
    for i in range(2000):
        p = small / f"{i}.bin"
        p.write_bytes(os.urandom(64 * 1024))
        files.append(p)
    total_mb = len(files) * 64 * 1024 / 1e6
    for p in files:
        hash_read(p, 1 << 20)
    print("\n2000 x 64 KiB files, warm cache; MB/s median [min-max]")
    res2 = {}
    for r in range(REPEATS):
        for name, fn in (("read", hash_read), ("readinto", hash_readinto)):
            for kib in (16, 64, 256, 1024, 4096):
                t = time.perf_counter()
                for p in files:
                    fn(p, kib * 1024)
                res2.setdefault((name, kib), []).append(
                    total_mb / (time.perf_counter() - t)
                )
    for name in ("read", "readinto"):
        print(f"-- {name}")
        for kib in (16, 64, 256, 1024, 4096):
            v = res2[(name, kib)]
            tag = "  <- current" if (name == "read" and kib == 1024) else ""
            print(
                f"{kib:>6} KiB  {statistics.median(v):8.0f} [{min(v):.0f}-{max(v):.0f}]{tag}"
            )
    import shutil

    shutil.rmtree(tmp, ignore_errors=True)


main()
