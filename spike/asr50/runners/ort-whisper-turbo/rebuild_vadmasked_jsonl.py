"""Build benchmark-schema JSONL from the already-written v2 masked raw outputs."""
import json
import pathlib

root = pathlib.Path(r"C:\scratch\asr50\WP18\corpus_v2_vadmasked")
out = pathlib.Path(r"C:\scratch\asr50\results_v2_vadmasked\ort-whisper-turbo")
truth = {c["clip_id"]: c for c in json.loads(
    (root / "ground_truth_v2.json").read_text(encoding="utf-8"))["clips"]}
vad = {c["clip_id"]: c for c in json.loads(
    (root / "manifest.json").read_text(encoding="utf-8"))["clips"]}
venvs = pathlib.Path(r"C:\scratch\asr50\WP12\venv")
footprints = {}
for device in ("cpu", "dml"):
    site = venvs / device / "Lib" / "site-packages"
    roots = [site / "onnxruntime", *site.glob("onnxruntime*.dist-info")]
    footprints[device] = sum(item.stat().st_size for top in roots if top.exists()
                             for item in ([top] if top.is_file() else top.rglob("*"))
                             if item.is_file())
records = []
for device in ("cpu", "dml"):
    for clip_id, clip in truth.items():
        raw = json.loads((out / device / f"{clip_id}.json").read_text(encoding="utf-8"))
        meta = raw["meta"]
        records.append({
            "schema_version": 1, "candidate": "ort-whisper-turbo-vadmasked",
            "clip_id": clip_id, "clip_set": clip["set"], "category": clip["category"],
            "transcript": clip["transcript"], "gate_no_speech": vad[clip_id]["gate_no_speech"],
            "run": {"kind": "masked_default", "index": 0, "process_id": None},
            "hardware": {"cpu": "AMD Ryzen 9 9900X",
                         "gpu": "AMD Radeon RX 7900 XT" if device == "dml" else None,
                         "ram_bytes": 31600000000, "os": "Windows 11 Pro build 26300",
                         "driver": "32.0.32029.2010" if device == "dml" else None},
            "device": {"requested": device, "actual": meta["actual_device"]},
            "runtime": {"name": "ONNX Runtime", "version": meta["runtime_version"],
                        "package_version": meta["runtime_version"],
                        "installed_bytes": footprints[device]},
            "model": {"artifact_id": meta["model_artifact"], "sha256": meta["model_sha256"],
                      "bytes": 1084799335, "cache_bytes": 0},
            "settings": meta["settings"],
            "input": {"sample_rate_hz": 16000, "channels": 1, "dtype": "float32",
                      "clip_sha256": vad[clip_id]["sha256"]},
            "measurements": {"audio_duration_s": clip["duration_s"], "runtime_s": None, "rtf": None,
                             "peak_ram_bytes": None, "peak_vram_bytes": None,
                             "peak_vram_method": "not measured", "model_footprint_bytes": 1084799335},
            "hypothesis": {"text": raw["text"], "words": []},
            "guard": None, "guard_text": None, "chunk_count": meta["chunk_count"],
            "chunking": meta["chunking"],
        })
(out / "results.jsonl").write_text(
    "".join(json.dumps(x, ensure_ascii=False) + "\n" for x in records), encoding="utf-8")
