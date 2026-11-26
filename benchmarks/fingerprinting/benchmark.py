"""Optional fingerprint experiment; no production imports or dependencies."""

import argparse
import hashlib
import importlib.metadata
import json
import os
import platform
import shutil
import ssl
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import psutil

BLOCK = 1024 * 1024
NAMES = ("sha256", "blake2b-256", "blake3")


def hasher(name, threads):
    if name == "sha256":
        return hashlib.sha256()
    if name == "blake2b-256":
        return hashlib.blake2b(digest_size=32)
    from blake3 import blake3

    return blake3(max_threads=threads)


def fixture(path, size, asset):
    with path.open("xb") as stream:
        for offset in range(0, size, BLOCK):
            seed = f"muteinous-17-v1:{asset}:{offset}".encode("ascii")
            stream.write(hashlib.shake_256(seed).digest(min(BLOCK, size - offset)))
        stream.flush()
        os.fsync(stream.fileno())


def digest(path, name, threads):
    h = hasher(name, threads)
    with path.open("rb") as stream:
        while block := stream.read(BLOCK):
            h.update(block)
    return h.hexdigest()


def vectors(names):
    expected = {
        "sha256": "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad",
        "blake2b-256": "bddd813c634239723171ef3fee98579b94964e3bb1cb3e427262c8c068d52319",
        "blake3": "6437b3ac38465133ffb63b75273a8db548c558465d79db03fd359c6cd5bd9d85",
    }
    for name in names:
        h = hasher(name, 1)
        h.update(b"a")
        h.update(b"bc")
        if h.hexdigest() != expected[name]:
            raise RuntimeError(f"Digest vector failed: {name}")


def trial(paths, size, name, workers, threads, contention):
    process = psutil.Process()
    baseline = process.memory_info().rss
    peak = [baseline, process.num_threads()]
    stop = threading.Event()
    work = [0]
    payload = bytes(BLOCK)

    def sample():
        while not stop.wait(0.01):
            peak[0] = max(peak[0], process.memory_info().rss)
            peak[1] = max(peak[1], process.num_threads())

    def competing_job():
        while not stop.is_set():
            hashlib.sha256(payload).digest()
            work[0] += len(payload)

    def batch(part):
        return [(i, digest(paths[i], name, threads)) for i in part]

    sampler = threading.Thread(target=sample)
    competitor = threading.Thread(target=competing_job) if contention else None
    sampler.start()
    cpu = time.process_time()
    start = time.perf_counter()
    try:
        if competitor:
            competitor.start()
        if workers == 1:
            values = batch(range(len(paths)))
        else:
            with ThreadPoolExecutor(max_workers=workers) as pool:
                parts = (range(i, len(paths), workers) for i in range(workers))
                values = [v for group in pool.map(batch, parts) for v in group]
        values.sort()
    finally:
        elapsed = time.perf_counter() - start
        stop.set()
        if competitor:
            competitor.join()
        sampler.join()
    cpu = time.process_time() - cpu
    return dict(algorithm=name, workers=workers, hash_threads=threads,
                contention=contention, bytes=size, assets=len(paths),
                seconds=elapsed, MB_s=size / elapsed / 1e6, cpu_seconds=cpu,
                rss_baseline_bytes=baseline, rss_sampled_peak_bytes=peak[0],
                threads_sampled_peak=peak[1], competing_MB_s=work[0] / elapsed / 1e6,
                digest_list_sha256=hashlib.sha256(
                    "".join(v for _, v in values).encode("ascii")).hexdigest())


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--scratch", type=Path, required=True)
    p.add_argument("--storage", required=True)
    p.add_argument("--large-mb", type=int, nargs="+", default=[100, 1000])
    p.add_argument("--small-count", type=int, default=2048)
    p.add_argument("--small-bytes", type=int, default=16384)
    p.add_argument("--repeats", type=int, default=3)
    p.add_argument("--algorithms", nargs="+", choices=NAMES, default=NAMES)
    a = p.parse_args()
    if not (all(0 < n <= 50_000 for n in a.large_mb) and 1 <= a.small_count <= 10_000
            and 1 <= a.small_bytes <= BLOCK and 2 <= a.repeats <= 10):
        p.error("Workload or repeats outside bounded range")
    vectors(a.algorithms)
    print(json.dumps(dict(environment=dict(platform=platform.platform(),
        python=platform.python_version(), openssl=ssl.OPENSSL_VERSION,
        cpu=platform.processor(), logical_cpus=os.cpu_count(),
        ram_bytes=psutil.virtual_memory().total, psutil=psutil.__version__,
        blake3=importlib.metadata.version("blake3") if "blake3" in a.algorithms else None,
        block_bytes=BLOCK, arguments=vars(a) | {"scratch": str(a.scratch)}))), flush=True)
    workloads = [(f"large-{mb}MB", 1, mb * 1_000_000) for mb in a.large_mb]
    workloads.append(("small", a.small_count, a.small_bytes))
    for label, count, each in workloads:
        size = count * each
        if shutil.disk_usage(a.scratch).free < size + 512 * BLOCK + count * 4096:
            raise RuntimeError(f"Insufficient scratch space for {label}")
        with tempfile.TemporaryDirectory(prefix="fingerprint-", dir=a.scratch) as directory:
            paths = [Path(directory) / f"asset-{i:05d}.bin" for i in range(count)]
            for i, path in enumerate(paths):
                fixture(path, each, i)
            configs = [(n, 1, 1, c) for c in (False, True) for n in a.algorithms]
            if count > 1:
                configs += [(n, 2, 1, False) for n in a.algorithms]
            elif "blake3" in a.algorithms:
                configs += [("blake3", 1, 2, c) for c in (False, True)]
            known = {}
            for repeat in range(a.repeats):
                for index in range(len(configs)):
                    config = configs[(index + repeat) % len(configs)]
                    row = trial(paths, size, *config)
                    key = row["digest_list_sha256"]
                    if known.setdefault(row["algorithm"], key) != key:
                        raise RuntimeError("Inconsistent digest across configurations")
                    print(json.dumps(row | dict(workload=label, repeat=repeat,
                        cache="first-after-generation" if repeat == index == 0
                        else "uncontrolled-repeated-read")), flush=True)


if __name__ == "__main__":
    main()
