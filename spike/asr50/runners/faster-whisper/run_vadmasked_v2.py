"""Offline faster-whisper pass over WP18's masked corpus; built-in VAD disabled."""
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
AUDIO = pathlib.Path(r"C:\scratch\asr50\WP18\corpus_v2_vadmasked")
OUT = pathlib.Path(r"C:\scratch\asr50\results_v2_vadmasked\faster-whisper\beam5-vad0-masked")

def sha(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()

def main():
    truth_doc = json.loads((AUDIO / "ground_truth_v2.json").read_text(encoding="utf-8"))
    truth = {c["clip_id"]: c for c in truth_doc["clips"]}
    manifest = json.loads((AUDIO / "manifest.json").read_text(encoding="utf-8"))
    gate = {c["clip_id"]: c for c in manifest["clips"]}
    model_bytes = sum(p.stat().st_size for p in MODEL.rglob("*") if p.is_file())
    model_hash = sha(MODEL / "model.bin")
    runtime_bytes = sum(p.stat().st_size for p in pathlib.Path(sys.prefix).rglob("*") if p.is_file())
    model = WhisperModel(str(MODEL), device="cpu", compute_type="int8_float32",
                         cpu_threads=12)
    proc = psutil.Process()
    OUT.mkdir(parents=True, exist_ok=True)
    rows = []
    for clip_id, gt in truth.items():
        path = AUDIO / gate[clip_id]["file"]
        with av.open(str(path)) as container:
            stream = container.streams.audio[0]
            rate, channels = stream.rate, len(stream.layout.channels)
            arr = np.concatenate([f.to_ndarray().reshape(-1).astype(np.float32, copy=False)
                                  for f in container.decode(stream)])
        clip_hash = hashlib.sha256(arr.astype("<f4", copy=False).tobytes()).hexdigest()
        started = time.perf_counter()
        segments, _ = model.transcribe(arr, language="en", beam_size=5,
                                        word_timestamps=True, vad_filter=False)
        segments = list(segments)
        elapsed = time.perf_counter() - started
        words, text_parts = [], []
        for seg in segments:
            text_parts.append(seg.text)
            if seg.words:
                words.extend({"word": w.word, "start": w.start, "end": w.end}
                             for w in seg.words)
        text = "".join(text_parts).strip()
        raw = {"text": text, "words": words, "clip_set": gt["set"], "meta": {
            "runtime": "faster-whisper", "runtime_version": faster_whisper.__version__,
            "ctranslate2_version": ctranslate2.__version__, "model_artifact": MODEL.name,
            "model_sha256": model_hash, "requested_device": "cpu", "actual_device": "cpu",
            "compute_type": "int8_float32", "threads": 12, "language": "en",
            "beam_size": 5, "vad_filter": False, "word_timestamps": True,
            "wall_seconds": elapsed, "peak_working_set_bytes": proc.memory_info().peak_wset,
            "pid": os.getpid(), "peak_vram_bytes": None,
            "masked_corpus": True, "gate_no_speech": gate[clip_id]["gate_no_speech"]}}
        (OUT / f"{clip_id}.json").write_text(
            json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")
        duration = len(arr) / rate
        rows.append({"schema_version": 1, "candidate": "faster-whisper-small-en",
            "clip_id": clip_id, "clip_set": gt["set"], "category": gt["category"],
            "run": {"kind": "single", "index": 0, "process_id": os.getpid()},
            "hardware": {"cpu": "AMD Ryzen 9 9900X", "gpu": "AMD Radeon RX 7900 XT",
                "ram_bytes": 31600000000, "os": "Windows 11 Pro build 26300",
                "driver": "32.0.32029.2010"},
            "device": {"requested": "cpu", "actual": "cpu"},
            "runtime": {"name": "faster-whisper", "version": faster_whisper.__version__,
                "package_version": ctranslate2.__version__, "installed_bytes": runtime_bytes},
            "model": {"artifact_id": MODEL.name, "sha256": model_hash,
                "bytes": model_bytes, "cache_bytes": 0},
            "settings": {"language": "en", "sample_rate_hz": rate, "channels": channels,
                "threads": 12, "decoding": {"beam_size": 5, "compute_type": "int8_float32",
                "vad_filter": False, "word_timestamps": True}},
            "input": {"sample_rate_hz": rate, "channels": channels, "dtype": "float32",
                "clip_sha256": clip_hash},
            "measurements": {"audio_duration_s": duration, "runtime_s": elapsed,
                "rtf": elapsed / duration, "peak_ram_bytes": raw["meta"]["peak_working_set_bytes"],
                "peak_vram_bytes": None, "peak_vram_method": "unavailable; CPU inference",
                "model_footprint_bytes": model_bytes},
            "hypothesis": {"text": text, "words": [{"text": w["word"],
                "start_s": w["start"], "end_s": w["end"]} for w in words]},
            "metrics": {}})
    with (OUT.parent / "results.jsonl").open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(json.dumps({"clips": len(rows), "gate_no_speech": sum(
        bool(v["gate_no_speech"]) for v in gate.values()), "out": str(OUT)}))

if __name__ == "__main__":
    main()
