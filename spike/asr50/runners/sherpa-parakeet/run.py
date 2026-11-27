"""Run the approved Parakeet TDT artifact through sherpa-onnx offline API."""
import argparse
import hashlib
import importlib.metadata
import json
import os
import pathlib
import platform
import re
import sys
import time

import numpy as np
import psutil
import sherpa_onnx
import soundfile as sf

MODEL = pathlib.Path(r"C:\scratch\asr50\models\parakeet-tdt-0-6b-v2-sherpa-onnx-int8")
AUDIO = pathlib.Path(r"C:\scratch\asr50\WP6\audio16k")
GT = AUDIO / "ground_truth.json"
MANIFEST = AUDIO / "manifest16k.json"
BENCH = pathlib.Path(r"C:\code\muteinous-spike50\spike\asr50\benchmark")
ARTIFACT = "parakeet-tdt-0-6b-v2-sherpa-onnx-int8"

os.environ.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1",
                  HF_HUB_DISABLE_TELEMETRY="1")


def sha256(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def installed_runtime_bytes():
    total = 0
    for package in ("sherpa-onnx", "sherpa-onnx-core"):
        dist = importlib.metadata.distribution(package)
        for entry in dist.files or ():
            try:
                total += entry.locate().stat().st_size
            except OSError:
                pass
    return total


def word_groups(result):
    """Group SentencePiece pieces; ▁ starts a word; preserve token timing."""
    toks = list(result.tokens)
    times = list(result.timestamps)
    durations = list(result.durations)
    groups = []
    for i, token in enumerate(toks):
        begins = token.startswith("▁") or token[:1].isspace()
        piece = token[1:] if token.startswith("▁") else token.lstrip()
        if begins or not groups:
            groups.append({"text": piece, "_indices": [i]})
        else:
            groups[-1]["text"] += piece
            groups[-1]["_indices"].append(i)
    output = []
    for gi, group in enumerate(groups):
        first = group["_indices"][0]
        start = float(times[first]) if first < len(times) else None
        if gi + 1 < len(groups):
            next_i = groups[gi + 1]["_indices"][0]
            end = float(times[next_i]) if next_i < len(times) else None
        else:
            last = group["_indices"][-1]
            end = (float(times[last]) + float(durations[last])
                   if last < len(times) and last < len(durations) else None)
        found = re.findall(r"[^\W_]+(?:'[^\W_]+)*", group["text"], flags=re.UNICODE)
        if found:
            output.append({"word": " ".join(found), "start": start, "end": end})
    return output


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--threads", type=int, required=True)
    p.add_argument("--provider", default="cpu")
    p.add_argument("--out", required=True)
    p.add_argument("--passes", type=int, default=1)
    p.add_argument("--run-kind", choices=("cold", "warm"), default="cold")
    p.add_argument("--clips", nargs="*")
    args = p.parse_args()
    out = pathlib.Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    truth = json.loads(GT.read_text(encoding="utf-8"))
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    clip_data = {c["clip_id"]: c for c in truth["clips"]}
    names = sorted(pathlib.Path(AUDIO).glob("*.wav"))
    if args.clips:
        wanted = set(args.clips)
        names = [x for x in names if x.stem in wanted]
    model_files = [MODEL / (name + ".int8.onnx") for name in ("encoder", "decoder", "joiner")]
    model_files.append(MODEL / "tokens.txt")
    model_hash = hashlib.sha256("".join(sha256(x) for x in model_files).encode()).hexdigest()
    model_bytes = sum(x.stat().st_size for x in model_files)
    start_load = time.perf_counter()
    recognizer = sherpa_onnx.OfflineRecognizer.from_transducer(
        str(model_files[0]), str(model_files[1]), str(model_files[2]), str(model_files[3]),
        num_threads=args.threads, sample_rate=16000, feature_dim=80, dither=0.0,
        decoding_method="greedy_search", provider=args.provider,
        model_type="nemo_transducer", debug=True,
    )
    model_load_s = time.perf_counter() - start_load
    print(f"MODEL_LOAD_SECONDS={model_load_s:.6f}", flush=True)
    proc = psutil.Process()
    records = []
    installed_bytes = installed_runtime_bytes()
    raw = {}
    for pass_ix in range(args.passes):
        pass_records = []
        for path in names:
            samples, sr = sf.read(path, dtype="float32", always_2d=True)
            if sr != 16000 or samples.shape[1] != 1:
                raise ValueError(f"non-canonical input: {path} sr={sr} shape={samples.shape}")
            pcm = np.ascontiguousarray(samples[:, 0])
            stream = recognizer.create_stream()
            stream.accept_waveform(sr, pcm)
            before = time.perf_counter()
            recognizer.decode_stream(stream)
            elapsed = time.perf_counter() - before
            result = stream.result
            words = word_groups(result)
            duration = len(pcm) / sr
            clip = clip_data[path.stem]
            peak_ram = proc.memory_info().peak_wset if hasattr(proc.memory_info(), "peak_wset") else None
            record = {
                "schema_version": 1, "candidate": "sherpa-parakeet",
                "clip_id": path.stem, "category": clip["category"],
                "run": {"kind": args.run_kind,
                        "index": pass_ix, "process_id": os.getpid()},
                "hardware": {"cpu": platform.processor(),
                             "gpu": "AMD Radeon RX 7900 XT",
                             "ram_bytes": psutil.virtual_memory().total,
                             "os": platform.platform(),
                             "driver": "32.0.32029.2010 (Adrenalin 26.20.29.02)"},
                "device": {"requested": args.provider,
                           "actual": "cpu" if args.provider != "cpu" else "cpu"},
                "runtime": {"name": "sherpa-onnx", "version": "2.0.3",
                            "package_version": "sherpa-onnx==2.0.3",
                            "installed_bytes": installed_bytes},
                "model": {"artifact_id": ARTIFACT, "sha256": model_hash,
                          "bytes": model_bytes, "cache_bytes": 0},
                "settings": {"language": "en", "sample_rate_hz": 16000,
                             "channels": 1, "threads": args.threads,
                             "decoding": {"method": "greedy_search",
                                          "model_type": "nemo_transducer"}},
                "input": {"sample_rate_hz": sr, "channels": 1, "dtype": "float32",
                          "clip_sha256": manifest[path.name]["sha256"]},
                "measurements": {"audio_duration_s": duration, "runtime_s": elapsed,
                                 "rtf": elapsed / duration if duration else None,
                                 "peak_ram_bytes": peak_ram, "peak_vram_bytes": None,
                                 "peak_vram_method": "Not sampled; provider probes separately",
                                 "model_footprint_bytes": model_bytes,
                                 "model_load_s": model_load_s},
                "hypothesis": {"text": result.text, "words": [
                    {"text": w["word"], "start_s": w["start"], "end_s": w["end"]}
                    for w in words]},
                "metrics": {},
            }
            pass_records.append(record)
            raw[path.stem] = {"text": result.text, "words": words,
                              "meta": {"runtime": "sherpa-onnx 2.0.3",
                                       "model": ARTIFACT, "model_sha256": model_hash,
                                       "requested_device": args.provider,
                                       "actual_device": "cpu", "threads": args.threads,
                                       "wall_seconds": elapsed, "peak_working_set_bytes": peak_ram,
                                       "model_load_s": model_load_s,
                                       "token_timestamps": list(result.timestamps),
                                       "token_durations": list(result.durations),
                                       "tokens": list(result.tokens)}}
        records.extend(pass_records)
        print(f"PASS={pass_ix} SECONDS={sum(r['measurements']['runtime_s'] for r in pass_records):.6f}",
              flush=True)
    for clip_id, value in raw.items():
        (out / f"{clip_id}.json").write_text(json.dumps(value, ensure_ascii=False, indent=2),
                                              encoding="utf-8")
    with (out / "observations.jsonl").open("w", encoding="utf-8") as f:
        for record in records:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    print(f"ACTUAL_PROVIDER=cpu requested={args.provider}", flush=True)


if __name__ == "__main__":
    main()
