"""Offline one-pass corpus-v2 runner for the approved faster-whisper model."""
import hashlib
import json
import os
import pathlib
import sys
import time

os.environ.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1",
                  HF_HUB_DISABLE_TELEMETRY="1")

import av
import ctranslate2
import faster_whisper
import numpy as np
import psutil
from faster_whisper import WhisperModel

MODEL = pathlib.Path(r"C:\scratch\asr50\models\whisper-small-en-faster-whisper-ct2")
AUDIO = pathlib.Path(r"C:\scratch\asr50\corpus_v2_frozen")
OUT = pathlib.Path(r"C:\scratch\asr50\results_v2\faster-whisper")
SLUG = MODEL.name

def sha(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()

def main():
    truth_doc = json.loads((AUDIO / "ground_truth_v2.json").read_text(encoding="utf-8"))
    truth = {c["clip_id"]: c for c in truth_doc["clips"]}
    model_bytes = sum(p.stat().st_size for p in MODEL.rglob("*") if p.is_file())
    model_hash = sha(MODEL / "model.bin")
    runtime_bytes = sum(p.stat().st_size for p in pathlib.Path(sys.prefix).rglob("*") if p.is_file())
    configs = (("beam5-vad-off", 5, False), ("beam5-vad-on", 5, True),
               ("beam1-vad-off", 1, False))
    OUT.mkdir(parents=True, exist_ok=True)
    all_rows = []
    proc = psutil.Process()
    for config, beam, vad in configs:
        model = WhisperModel(str(MODEL), device="cpu", compute_type="int8_float32",
                             cpu_threads=12)
        rawdir = OUT / config
        rawdir.mkdir(parents=True, exist_ok=True)
        load_s = None
        for clip_id, gt in truth.items():
            path = AUDIO / gt.get("wav", f"{clip_id}.wav")
            with av.open(str(path)) as container:
                stream = container.streams.audio[0]
                rate, channels = stream.rate, len(stream.layout.channels)
                arr = np.concatenate([
                    frame.to_ndarray().reshape(-1).astype(np.float32, copy=False)
                    for frame in container.decode(stream)])
            clip_hash = hashlib.sha256(arr.astype("<f4", copy=False).tobytes()).hexdigest()
            started = time.perf_counter()
            segments, _ = model.transcribe(arr, language="en", beam_size=beam,
                                            word_timestamps=True, vad_filter=vad)
            segments = list(segments)
            elapsed = time.perf_counter() - started
            words, texts = [], []
            for seg in segments:
                texts.append(seg.text)
                if seg.words:
                    words.extend({"word": w.word, "start": w.start, "end": w.end}
                                 for w in seg.words)
            text = "".join(texts).strip()
            raw = {"text": text, "words": words, "clip_set": gt["set"], "meta": {
                "runtime": "faster-whisper", "runtime_version": faster_whisper.__version__,
                "ctranslate2_version": ctranslate2.__version__, "model_artifact": SLUG,
                "model_sha256": model_hash, "requested_device": "cpu", "actual_device": "cpu",
                "compute_type": "int8_float32", "threads": 12, "language": "en",
                "beam_size": beam, "vad_filter": vad, "word_timestamps": True,
                "wall_seconds": elapsed, "model_load_seconds": load_s,
                "peak_working_set_bytes": proc.memory_info().peak_wset,
                "pid": os.getpid(), "peak_vram_bytes": None}}
            (rawdir / f"{clip_id}.json").write_text(
                json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")
            duration = len(arr) / rate
            all_rows.append({"schema_version": 1, "candidate": "faster-whisper-small-en",
                "clip_id": clip_id, "clip_set": gt["set"], "category": gt["category"],
                "run": {"kind": "single", "index": 0, "process_id": os.getpid()},
                "hardware": {"cpu": "AMD Ryzen 9 9900X", "gpu": "AMD Radeon RX 7900 XT",
                    "ram_bytes": 31600000000, "os": "Windows 11 Pro build 26300",
                    "driver": "32.0.32029.2010"},
                "device": {"requested": "cpu", "actual": "cpu"},
                "runtime": {"name": "faster-whisper", "version": faster_whisper.__version__,
                    "package_version": ctranslate2.__version__, "installed_bytes": runtime_bytes},
                "model": {"artifact_id": SLUG, "sha256": model_hash, "bytes": model_bytes,
                    "cache_bytes": 0},
                "settings": {"language": "en", "sample_rate_hz": rate, "channels": channels,
                    "threads": 12, "decoding": {"beam_size": beam, "compute_type": "int8_float32",
                    "vad_filter": vad, "word_timestamps": True}},
                "input": {"sample_rate_hz": rate, "channels": channels, "dtype": "float32",
                    "clip_sha256": clip_hash},
                "measurements": {"audio_duration_s": duration, "runtime_s": elapsed,
                    "rtf": elapsed / duration, "peak_ram_bytes": raw["meta"]["peak_working_set_bytes"],
                    "peak_vram_bytes": None, "peak_vram_method": "unavailable; CPU inference",
                    "model_footprint_bytes": model_bytes},
                "hypothesis": {"text": text, "words": [{"text": w["word"],
                    "start_s": w["start"], "end_s": w["end"]} for w in words]},
                "metrics": {}})
        del model
    with (OUT / "results.jsonl").open("w", encoding="utf-8") as f:
        for row in all_rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(json.dumps({"clips": len(truth), "records": len(all_rows),
                      "configs": [c[0] for c in configs]}))

if __name__ == "__main__":
    main()
