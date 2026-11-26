"""Optional source-fingerprint benchmark; stdlib, psutil and blake3 only."""

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
SMALL_PROFILES = ((512, 4096), (2048, 16384), (8192, 65536))


def hasher(name, threads):
    if name == "sha256":
        return hashlib.sha256()
    if name == "blake2b-256":
        return hashlib.blake2b(digest_size=32)
    from blake3 import blake3

    return blake3(max_threads=min(4, os.cpu_count() or 1) if threads == 0 else threads)


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


def sample_memory(process):
    info = process.memory_info()
    return getattr(info, "peak_wset", info.rss), info.rss


def cache_mode(paths, size, ram):
    free = psutil.virtual_memory().available
    if size > ram or (size >= 10_000_000_000 and free < 10_000_000_000):
        return "cold", free
    for path in paths:
        with path.open("rb") as stream:
            while stream.read(BLOCK):
                pass
    return "warm", free


def read_only(paths, size):
    start = time.perf_counter()
    passes = 0
    while passes == 0 or time.perf_counter() - start < 0.25:
        for path in paths:
            with path.open("rb") as stream:
                while stream.read(BLOCK):
                    pass
        passes += 1
    elapsed = time.perf_counter() - start
    return dict(
        bytes=size * passes,
        passes=passes,
        seconds=elapsed,
        MB_s=size * passes / elapsed / 1e6,
    )


def competitor_baseline(seconds=2.0):
    payload = bytes(BLOCK)
    start = time.perf_counter()
    end = start + seconds
    total = 0
    while time.perf_counter() < end:
        hashlib.sha256(payload).digest()
        total += len(payload)
    elapsed = time.perf_counter() - start
    return total / elapsed / 1e6


def trial(paths, size, name, workers, threads, contention, solo_competitor):
    process = psutil.Process()
    peak_wset, rss_baseline = sample_memory(process)
    peak_rss = rss_baseline
    peak_threads = process.num_threads()
    stop = threading.Event()
    work = [0]
    payload = bytes(BLOCK)
    pool = ThreadPoolExecutor(max_workers=workers) if workers > 1 else None

    def sample():
        nonlocal peak_wset, peak_rss, peak_threads
        while not stop.wait(0.01):
            working_set, rss = sample_memory(process)
            peak_wset = max(peak_wset, working_set)
            peak_rss = max(peak_rss, rss)
            peak_threads = max(peak_threads, process.num_threads())

    def competing_job():
        while not stop.is_set():
            hashlib.sha256(payload).digest()
            work[0] += len(payload)

    def batch(part):
        return [(i, digest(paths[i], name, threads)) for i in part]

    sampler = threading.Thread(target=sample)
    competitor = threading.Thread(target=competing_job) if contention else None
    try:
        sampler.start()
        if competitor:
            competitor.start()
        cpu_start = time.process_time()
        start = time.perf_counter()
        passes = 0
        while True:
            passes += 1
            if pool is None:
                values = batch(range(len(paths)))
            else:
                parts = (range(i, len(paths), workers) for i in range(workers))
                values = [v for group in pool.map(batch, parts) for v in group]
            elapsed = time.perf_counter() - start
            if elapsed >= 0.5:
                break
        cpu = time.process_time() - cpu_start
        stop.set()
        values.sort()
    finally:
        stop.set()
        if competitor and competitor.ident is not None:
            competitor.join()
        if pool:
            pool.shutdown(wait=True)
        if sampler.ident is not None:
            sampler.join()
    return dict(
        record="trial",
        algorithm=name,
        workers=workers,
        hash_threads=threads,
        contention=contention,
        bytes=size * passes,
        passes=passes,
        assets=len(paths),
        seconds=elapsed,
        MB_s=size * passes / elapsed / 1e6,
        cpu_seconds=cpu,
        cpu_util_percent=cpu / elapsed * 100,
        rss_baseline_bytes=rss_baseline,
        process_peak_working_set_bytes=peak_wset,
        rss_sampled_peak_bytes=peak_rss,
        threads_sampled_peak=peak_threads,
        competitor_MB_s=work[0] / elapsed / 1e6,
        competitor_solo_MB_s=solo_competitor if contention else None,
        digest_list_sha256=hashlib.sha256(
            "".join(v for _, v in values).encode("ascii")
        ).hexdigest(),
    )


def emit(row):
    print(json.dumps(row, sort_keys=True), flush=True)


def run_workload(paths, label, size, algorithms, repeats, ram, shared50):
    mode, free_ram = cache_mode(paths, size, ram)
    emit(
        dict(
            record="workload-baseline",
            workload=label,
            cache_mode=mode,
            free_ram_bytes=free_ram,
            total_ram_bytes=ram,
            **read_only(paths, size),
        )
    )
    configs = [(name, 1, 1, False) for name in algorithms]
    configs += [(name, 1, 1, True) for name in algorithms]
    if len(paths) > 1:
        configs += [
            (name, 2, 1, contention)
            for contention in (False, True)
            for name in algorithms
        ]
    if "blake3" in algorithms:
        configs += [("blake3", 1, 2, contention) for contention in (False, True)]
        configs += [("blake3", 1, 0, contention) for contention in (False, True)]
    known = {}
    for repeat in range(repeats):
        order = configs[repeat % len(configs) :] + configs[: repeat % len(configs)]
        emit(
            dict(
                record="order",
                workload=label,
                repeat=repeat,
                candidate_order=[f"{n}/w{w}/t{t}/c{int(c)}" for n, w, t, c in order],
                shared_50gb_fixture=shared50,
            )
        )
        for name, workers, threads, contention in order:
            solo = competitor_baseline() if contention else None
            trial_mode, trial_free_ram = cache_mode(paths, size, ram)
            row = trial(paths, size, name, workers, threads, contention, solo)
            if (
                known.setdefault(name, row["digest_list_sha256"])
                != row["digest_list_sha256"]
            ):
                raise RuntimeError(f"Inconsistent digest across {name} configurations")
            emit(
                row
                | dict(
                    workload=label,
                    repeat=repeat,
                    cache_mode=trial_mode,
                    free_ram_bytes=trial_free_ram,
                    total_ram_bytes=ram,
                )
            )


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--scratch", type=Path, required=True)
    p.add_argument("--storage", required=True)
    p.add_argument("--large-mb", type=int, nargs="*", default=[100, 1000])
    p.add_argument(
        "--shared-50gb",
        action="store_true",
        help="Create one 50 GB fixture; all candidates reuse it.",
    )
    p.add_argument(
        "--small-profile",
        action="append",
        default=[],
        metavar="COUNTxBYTES",
        help="Repeatable; default 512x4096,2048x16384,8192x65536.",
    )
    p.add_argument(
        "--skip-small",
        action="store_true",
        help="Do not include the default small-asset profiles.",
    )
    p.add_argument("--repeats", type=int, default=3)
    p.add_argument("--algorithms", nargs="+", choices=NAMES, default=NAMES)
    a = p.parse_args()
    try:
        profiles = [
            tuple(map(int, item.lower().split("x"))) for item in a.small_profile
        ]
    except ValueError:
        p.error("Small profiles must be COUNTxBYTES")
    if not profiles and not a.skip_small:
        profiles = list(SMALL_PROFILES)
    if (
        not all(0 < n <= 50_000 for n in a.large_mb)
        or not all(
            1 <= count <= 100_000 and 1 <= size <= BLOCK for count, size in profiles
        )
        or not 1 <= a.repeats <= 10
    ):
        p.error("Workload or repeats outside bounded range")
    vectors(a.algorithms)
    a.scratch.mkdir(parents=True, exist_ok=True)
    ram = psutil.virtual_memory().total
    emit(
        dict(
            record="environment",
            platform=platform.platform(),
            python=platform.python_version(),
            openssl=ssl.OPENSSL_VERSION,
            cpu=platform.processor(),
            logical_cpus=os.cpu_count(),
            ram_bytes=ram,
            psutil=psutil.__version__,
            blake3=importlib.metadata.version("blake3")
            if "blake3" in a.algorithms
            else None,
            block_bytes=BLOCK,
            storage=a.storage,
            arguments={**vars(a), "scratch": str(a.scratch)},
        )
    )
    workloads = [(f"large-{mb}MB", 1, mb * 1_000_000) for mb in a.large_mb]
    workloads.extend((f"small-{count}x{size}", count, size) for count, size in profiles)
    if a.shared_50gb:
        workloads.append(("large-50GB-shared", 1, 50_000_000_000))
    with tempfile.TemporaryDirectory(prefix="fingerprint-", dir=a.scratch) as directory:
        directory = Path(directory)
        shared = None
        for label, count, each in workloads:
            size = count * each
            if shared is not None and label == "large-50GB-shared":
                paths = [shared]
            else:
                margin = max(512 * BLOCK, size // 20)
                if shutil.disk_usage(a.scratch).free < size + margin:
                    raise RuntimeError(f"Insufficient scratch space for {label}")
                fixture_dir = directory / label
                fixture_dir.mkdir()
                paths = [fixture_dir / f"asset-{i:05d}.bin" for i in range(count)]
                for i, path in enumerate(paths):
                    fixture(path, each, i)
                if label == "large-50GB-shared":
                    shared = paths[0]
            run_workload(
                paths,
                label,
                size,
                a.algorithms,
                a.repeats,
                ram,
                label == "large-50GB-shared",
            )
            if label != "large-50GB-shared":
                shutil.rmtree(paths[0].parent)


if __name__ == "__main__":
    main()
