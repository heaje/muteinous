"""Run Parakeet int8 on raw or WP18 VAD-masked corpus v3."""
import argparse
import hashlib
import importlib.metadata
import json
import os
import pathlib
import platform
import re
import time

import numpy as np
import psutil
import sherpa_onnx
import soundfile as sf

FROZEN = pathlib.Path(r"C:\scratch\asr50\corpus_v3_frozen")
MASKED = pathlib.Path(r"C:\scratch\asr50\WP18\corpus_v3_vadmasked")
ROOT = pathlib.Path(r"C:\scratch\asr50\results_v3\sherpa-parakeet")
MODEL = pathlib.Path(r"C:\scratch\asr50\models\parakeet-tdt-0-6b-v2-sherpa-onnx-int8")
ARTIFACT = "parakeet-tdt-0-6b-v2-sherpa-onnx-int8"
os.environ.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1",
                  HF_HUB_DISABLE_TELEMETRY="1")


def sha256(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def installed_bytes():
    total = 0
    for package in ("sherpa-onnx", "sherpa-onnx-core"):
        for entry in importlib.metadata.distribution(package).files or ():
            try:
                total += entry.locate().stat().st_size
            except OSError:
                pass
    return total


def word_groups(result):
    tokens = list(result.tokens)
    times = list(result.timestamps)
    durations = list(result.durations)
    groups = []
    for i, token in enumerate(tokens):
        begins = token.startswith("▁") or token[:1].isspace()
        piece = token[1:] if token.startswith("▁") else token.lstrip()
        if begins or not groups:
            groups.append({"text": piece, "indices": [i]})
        else:
            groups[-1]["text"] += piece
            groups[-1]["indices"].append(i)
    words, duration_words = [], []
    for gi, group in enumerate(groups):
        first, last = group["indices"][0], group["indices"][-1]
        start = float(times[first]) if first < len(times) else None
        if gi + 1 < len(groups):
            next_idx = groups[gi + 1]["indices"][0]
            end = float(times[next_idx]) if next_idx < len(times) else None
        else:
            end = float(times[last]) + float(durations[last]) if last < len(times) and last < len(durations) else None
        end_duration = (float(times[last]) + float(durations[last])
                        if last < len(times) and last < len(durations) else None)
        lexical = re.findall(r"[^\W_]+(?:'[^\W_]+)*", group["text"], flags=re.UNICODE)
        if lexical:
            text = " ".join(lexical)
            words.append({"word": text, "start": start, "end": end})
            duration_words.append({"word": text, "start": start, "end": end_duration})
    return words, duration_words


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", choices=("raw", "masked"), required=True)
    args = parser.parse_args()
    corpus_dir = FROZEN if args.source == "raw" else MASKED
    out = ROOT / args.source / "cpu"
    out.mkdir(parents=True, exist_ok=True)
    truth_path = FROZEN / "ground_truth_v3.json"
    truth = json.loads(truth_path.read_text(encoding="utf-8"))
    clips = truth["clips"]
    if len(clips) != 380:
        raise ValueError(f"Expected 380 v3 clips, found {len(clips)}")
    manifest_map = {}
    manifest = None
    if args.source == "masked":
        manifest = json.loads((MASKED / "manifest.json").read_text(encoding="utf-8"))
        manifest_map = {row["input"]: row for row in manifest["clips"]}
        if len(manifest_map) != 380:
            raise ValueError(f"Expected 380 VAD manifest rows, found {len(manifest_map)}")
    else:
        manifest = json.loads((MASKED / "manifest.json").read_text(encoding="utf-8"))
        manifest_map = {row["input"]: row for row in manifest["clips"]}

    for clip in clips:
        raw_name = clip["wav"]
        entry = manifest_map.get(raw_name)
        source_name = raw_name if args.source == "raw" else entry["output"]
        source_path = corpus_dir / source_name
        expected_hash = clip["sha256"] if args.source == "raw" else entry["sha256"]
        if args.source == "masked" and entry["input"] != raw_name:
            raise ValueError(f"Manifest source mismatch: {clip['clip_id']}")
        if sha256(source_path) != expected_hash:
            raise ValueError(f"Input hash mismatch: {clip['clip_id']} ({args.source})")

    encoder, decoder, joiner, tokens = [
        MODEL / "encoder.int8.onnx", MODEL / "decoder.int8.onnx",
        MODEL / "joiner.int8.onnx", MODEL / "tokens.txt"
    ]
    model_files = [encoder, decoder, joiner, tokens]
    model_hash = hashlib.sha256(
        "".join(sha256(p) for p in model_files).encode("ascii")).hexdigest()
    model_bytes = sum(p.stat().st_size for p in model_files)
    recognizer = sherpa_onnx.OfflineRecognizer.from_transducer(
        str(encoder), str(decoder), str(joiner), str(tokens),
        num_threads=4, sample_rate=16000, feature_dim=80, dither=0.0,
        decoding_method="greedy_search", provider="cpu",
        model_type="nemo_transducer", debug=True,
    )
    process = psutil.Process()
    rows = []
    for clip in clips:
        raw_name = clip["wav"]
        entry = manifest_map[raw_name]
        source_name = raw_name if args.source == "raw" else entry["output"]
        source_path = corpus_dir / source_name
        audio, sr = sf.read(source_path, dtype="float32", always_2d=True)
        if sr != 16000 or audio.shape[1] != 1:
            raise ValueError(f"Expected 16 kHz mono float32 input: {source_name}")
        audio = np.ascontiguousarray(audio[:, 0])
        if args.source == "masked" and len(audio) != entry["samples"]:
            raise ValueError(f"Masked sample count mismatch: {clip['clip_id']}")
        stream = recognizer.create_stream()
        stream.accept_waveform(sr, audio)
        before = time.perf_counter()
        recognizer.decode_stream(stream)
        elapsed = time.perf_counter() - before
        result = stream.result
        words, duration_words = word_groups(result)
        gate = bool(entry["gate_no_speech"])
        digest = clip["sha256"] if args.source == "raw" else entry["sha256"]
        normalized = {
            "clip_set": clip.get("set", "natural_v3"),
            "gate_no_speech": gate,
            "text": result.text,
            "words": [{"word": w["word"], "start": w["start"], "end": w["end"]}
                      for w in words],
            "words_duration_end": [
                {"word": w["word"], "start": w["start"], "end": w["end"]}
                for w in duration_words
            ],
            "meta": {
                "runtime": "sherpa-onnx 2.0.3", "runtime_package": "sherpa-onnx-core 2.0.3",
                "model": ARTIFACT, "model_sha256": model_hash, "model_bytes": model_bytes,
                "requested_device": "cpu", "actual_device": "cpu",
                "threads": 4, "sample_rate_hz": sr, "channels": 1,
                "decoding_method": "greedy_search", "model_type": "nemo_transducer",
                "wall_seconds": elapsed, "peak_working_set_bytes": process.memory_info().peak_wset,
                "token_timestamps": list(result.timestamps),
                "token_durations": list(result.durations), "tokens": list(result.tokens),
            },
        }
        (out / f"{clip['clip_id']}.json").write_text(
            json.dumps(normalized, ensure_ascii=False, indent=2), encoding="utf-8")
        rows.append({
            "schema_version": 3, "candidate": "sherpa-parakeet",
            "clip_id": clip["clip_id"], "clip_set": clip.get("set", "natural_v3"),
            "gate_no_speech": gate, "category": clip["category"],
            "condition": clip["condition"], "voice": clip.get("voice"),
            "rate": clip.get("rate"), "volume": clip.get("volume"),
            "snr_db": clip.get("snr_db"),
            "run": {"kind": "cold", "index": 0, "process_id": os.getpid()},
            "hardware": {"cpu": platform.processor(), "gpu": "AMD Radeon RX 7900 XT",
                         "ram_bytes": psutil.virtual_memory().total, "os": platform.platform(),
                         "driver": "32.0.32029.2010 (Adrenalin 26.20.29.02)"},
            "device": {"requested": "cpu", "actual": "cpu"},
            "runtime": {"name": "sherpa-onnx", "version": "2.0.3",
                        "package_version": "sherpa-onnx==2.0.3",
                        "installed_bytes": installed_bytes()},
            "model": {"artifact_id": ARTIFACT, "sha256": model_hash,
                      "bytes": model_bytes, "cache_bytes": 0},
            "settings": {"language": "en", "sample_rate_hz": sr, "channels": 1,
                         "threads": 4, "decoding": {"method": "greedy_search",
                                                     "model_type": "nemo_transducer"}},
            "input": {"sample_rate_hz": sr, "channels": 1, "dtype": "float32",
                      "clip_sha256": digest},
            "measurements": {
                "audio_duration_s": len(audio) / sr, "runtime_s": elapsed,
                "rtf": elapsed / (len(audio) / sr) if len(audio) else None,
                "peak_ram_bytes": process.memory_info().peak_wset,
                "peak_vram_bytes": None, "peak_vram_method": "Unavailable; CPU execution",
                "model_footprint_bytes": model_bytes,
            },
            "hypothesis": {"text": result.text,
                           "words": [{"text": w["word"], "start_s": w["start"],
                                      "end_s": w["end"]} for w in words]},
            "metrics": {},
        })
        print(f"{args.source} {clip['clip_id']} [{clip['condition']}] "
              f"chars={len(result.text)} gate={gate}", flush=True)
    with (out.parent / "results.jsonl").open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(f"Completed {args.source}: {len(rows)} clips; peak RAM "
          f"{process.memory_info().peak_wset} bytes", flush=True)


if __name__ == "__main__":
    main()
