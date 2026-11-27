"""Offline faster-whisper ASR benchmark/probe for WP10."""
import argparse, hashlib, json, os, pathlib, sys, time
from datetime import datetime

os.environ.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1",
                  HF_HUB_DISABLE_TELEMETRY="1")

import psutil
import ctranslate2
from faster_whisper import WhisperModel
import faster_whisper

MODEL = pathlib.Path(r"C:\scratch\asr50\models\whisper-small-en-faster-whisper-ct2")
AUDIO = pathlib.Path(r"C:\scratch\asr50\WP6\audio16k")
OUT = pathlib.Path(r"C:\scratch\asr50\results\faster-whisper")
SLUG = MODEL.name

def sha(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()

def pcm(path):
    import av
    import numpy as np
    # PyAV decodes IEEE-float WAV to float32 without candidate-specific resampling.
    with av.open(str(path)) as container:
        stream = container.streams.audio[0]
        rate, channels = stream.rate, len(stream.layout.channels)
        chunks = [frame.to_ndarray().reshape(-1).astype(np.float32, copy=False)
                  for frame in container.decode(stream)]
    arr = np.concatenate(chunks)
    digest = hashlib.sha256(arr.astype("<f4", copy=False).tobytes()).hexdigest()
    return arr, rate, channels, len(arr) / rate, digest

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--device", default="cpu")
    ap.add_argument("--compute", default="int8")
    ap.add_argument("--threads", type=int, default=12)
    ap.add_argument("--beam", type=int, default=5)
    ap.add_argument("--vad", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--passes", type=int, default=1)
    ap.add_argument("--kind", default="warm")
    args = ap.parse_args()
    files = sorted(AUDIO.glob("*.wav"))
    files = [p for p in files if p.name != "ground_truth.json"]
    if args.limit:
        files = files[:args.limit]
    gt = json.loads((AUDIO / "ground_truth.json").read_text(encoding="utf-8"))
    truth = {x.get("clip_id", x.get("id")): x for x in gt.get("clips", [])}
    model_bytes = sum(p.stat().st_size for p in MODEL.rglob("*") if p.is_file())
    artifacts = sorted(p for p in MODEL.rglob("*") if p.is_file())
    model_hash = sha(MODEL / "model.bin")
    runtime_bytes = sum(p.stat().st_size for p in pathlib.Path(sys.prefix).rglob("*")
                        if p.is_file())
    OUT.mkdir(parents=True, exist_ok=True)
    rawdir = OUT / args.device
    rawdir.mkdir(parents=True, exist_ok=True)
    proc = psutil.Process()
    start_load = time.perf_counter()
    model = WhisperModel(str(MODEL), device=args.device, compute_type=args.compute,
                         cpu_threads=args.threads)
    load_s = time.perf_counter() - start_load
    rows = []
    for pass_i in range(args.passes):
        for path in files:
            arr, rate, channels, duration, clip_hash = pcm(path)
            start = time.perf_counter()
            segments, info = model.transcribe(arr, language="en", beam_size=args.beam,
                 word_timestamps=True, vad_filter=args.vad)
            segments = list(segments)
            elapsed = time.perf_counter() - start
            words, texts = [], []
            for seg in segments:
                texts.append(seg.text)
                if seg.words:
                    words.extend({"word": w.word, "start": w.start, "end": w.end}
                                 for w in seg.words)
            text = "".join(texts).strip()
            record = {"text": text, "words": words, "meta": {
                "runtime": "faster-whisper", "runtime_version": faster_whisper.__version__,
                "ctranslate2_version": ctranslate2.__version__, "model_artifact": SLUG,
                "model_sha256": model_hash, "requested_device": args.device,
                "actual_device": args.device, "actual_device_verified": "successful inference; CPU counters only for CPU; GPU telemetry not captured",
                "compute_type": args.compute, "beam_size": args.beam, "vad_filter": args.vad,
                "word_timestamps": True, "language": "en", "threads": args.threads,
                "wall_seconds": elapsed, "model_load_seconds": load_s if pass_i == 0 else None,
                "peak_working_set_bytes": proc.memory_info().peak_wset if hasattr(proc.memory_info(), "peak_wset") else None,
                "pid": os.getpid(), "peak_vram_bytes": None}}
            (rawdir / f"{path.stem}.json").write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
            gtrow = truth.get(path.stem, {})
            rows.append({"schema_version": 1, "candidate": "faster-whisper-small-en",
                "clip_id": path.stem, "category": gtrow.get("category", "unknown"),
                "run": {"kind": args.kind if pass_i == 0 else "warm", "index": pass_i, "process_id": os.getpid()},
                "hardware": {"cpu": "AMD Ryzen 9 9900X", "gpu": "AMD Radeon RX 7900 XT",
                    "ram_bytes": 31600000000, "os": "Windows 11 Pro build 26300", "driver": "32.0.32029.2010"},
                "device": {"requested": args.device, "actual": args.device},
                "runtime": {"name": "faster-whisper", "version": faster_whisper.__version__,
                "package_version": ctranslate2.__version__, "installed_bytes": runtime_bytes},
                "model": {"artifact_id": SLUG, "sha256": model_hash, "bytes": model_bytes, "cache_bytes": 0},
                "settings": {"language": "en", "sample_rate_hz": rate, "channels": channels,
                    "threads": args.threads, "decoding": {"beam_size": args.beam, "compute_type": args.compute, "vad_filter": args.vad, "word_timestamps": True}},
                "input": {"sample_rate_hz": rate, "channels": channels, "dtype": "float32", "clip_sha256": clip_hash},
                "measurements": {"audio_duration_s": duration, "runtime_s": elapsed, "rtf": elapsed / duration,
                    "peak_ram_bytes": record["meta"]["peak_working_set_bytes"], "peak_vram_bytes": None,
                    "peak_vram_method": "unavailable; no GPU process sampling performed",
                    "model_footprint_bytes": model_bytes},
                "hypothesis": {"text": text, "words": [{"text": w["word"], "start_s": w["start"], "end_s": w["end"]} for w in words]},
                "metrics": {}})
    with (OUT / "results.jsonl").open("a", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(json.dumps({"load_seconds": load_s, "pid": os.getpid(), "clips": len(files),
        "rows": len(rows), "supported_cpu_compute_types": sorted(ctranslate2.get_supported_compute_types("cpu")),
        "cuda_device_count": ctranslate2.get_cuda_device_count()}))

if __name__ == "__main__":
    main()
