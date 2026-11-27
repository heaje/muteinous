"""Infer all corpus-v2 VAD-masked clips; records gate metadata, does not skip."""
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

CORPUS = pathlib.Path(r"C:\scratch\asr50\WP18\corpus_v2_vadmasked")
FROZEN = pathlib.Path(r"C:\scratch\asr50\corpus_v2_frozen")
OUT = pathlib.Path(r"C:\scratch\asr50\results_v2_vadmasked\sherpa-parakeet\cpu")
MODEL = pathlib.Path(r"C:\scratch\asr50\models\parakeet-tdt-0-6b-v2-sherpa-onnx-int8")
ARTIFACT = "parakeet-tdt-0-6b-v2-sherpa-onnx-int8"
os.environ.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1",
                  HF_HUB_DISABLE_TELEMETRY="1")


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def word_groups(result, duration_end=False):
    tokens, timestamps, durations = (list(result.tokens), list(result.timestamps),
                                      list(result.durations))
    groups = []
    for i, token in enumerate(tokens):
        begins = token.startswith("▁") or token[:1].isspace()
        piece = token[1:] if token.startswith("▁") else token.lstrip()
        if begins or not groups:
            groups.append({"text": piece, "indices": [i]})
        else:
            groups[-1]["text"] += piece
            groups[-1]["indices"].append(i)
    result_words = []
    for gi, group in enumerate(groups):
        first, last = group["indices"][0], group["indices"][-1]
        start = float(timestamps[first]) if first < len(timestamps) else None
        if duration_end and last < len(timestamps) and last < len(durations):
            end = float(timestamps[last]) + float(durations[last])
        elif gi + 1 < len(groups):
            next_i = groups[gi + 1]["indices"][0]
            end = float(timestamps[next_i]) if next_i < len(timestamps) else None
        else:
            end = (float(timestamps[last]) + float(durations[last])
                   if last < len(timestamps) and last < len(durations) else None)
        lexical = re.findall(r"[^\W_]+(?:'[^\W_]+)*", group["text"], flags=re.UNICODE)
        if lexical:
            result_words.append({"word": " ".join(lexical), "start": start, "end": end})
    return result_words


def installed_bytes():
    total = 0
    for package in ("sherpa-onnx", "sherpa-onnx-core"):
        for entry in importlib.metadata.distribution(package).files or ():
            try:
                total += entry.locate().stat().st_size
            except OSError:
                pass
    return total


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    gt_path = CORPUS / "ground_truth_v2.json"
    original_gt_path = FROZEN / "ground_truth_v2.json"
    if sha256(gt_path) != sha256(original_gt_path):
        raise ValueError("Masked-corpus ground_truth_v2.json is not byte-identical to frozen corpus")
    truth = json.loads(gt_path.read_text(encoding="utf-8"))
    frozen_truth = {c["clip_id"]: c for c in json.loads(
        original_gt_path.read_text(encoding="utf-8"))["clips"]}
    manifest = json.loads((CORPUS / "manifest.json").read_text(encoding="utf-8"))
    manifest_clips = {c["clip_id"]: c for c in manifest["clips"]}
    if len(truth["clips"]) != 60 or len(manifest_clips) != 60:
        raise ValueError("Expected exactly 60 corpus-v2 clips and mask manifest entries")
    if sum(c["gate_no_speech"] for c in manifest["clips"]) != 20:
        raise ValueError("Expected 20 gate_no_speech manifest entries")
    for clip in truth["clips"]:
        item = manifest_clips[clip["clip_id"]]
        if item["input_sha256"] != frozen_truth[clip["clip_id"]]["wav_sha256"]:
            raise ValueError(f"Input identity changed for {clip['clip_id']}")
        wav = CORPUS / item["file"]
        if sha256(wav) != item["sha256"]:
            raise ValueError(f"Masked WAV hash mismatch for {clip['clip_id']}")

    encoder, decoder, joiner, tokens = [
        MODEL / "encoder.int8.onnx", MODEL / "decoder.int8.onnx",
        MODEL / "joiner.int8.onnx", MODEL / "tokens.txt"
    ]
    model_files = [encoder, decoder, joiner, tokens]
    model_digest = hashlib.sha256(
        "".join(sha256(p) for p in model_files).encode("ascii")).hexdigest()
    model_bytes = sum(p.stat().st_size for p in model_files)
    recognizer = sherpa_onnx.OfflineRecognizer.from_transducer(
        str(encoder), str(decoder), str(joiner), str(tokens),
        num_threads=4, sample_rate=16000, feature_dim=80, dither=0.0,
        decoding_method="greedy_search", provider="cpu",
        model_type="nemo_transducer", debug=True,
    )
    proc = psutil.Process()
    rows = []
    for clip in truth["clips"]:
        vad = manifest_clips[clip["clip_id"]]
        wav = CORPUS / vad["file"]
        audio, sr = sf.read(wav, dtype="float32", always_2d=True)
        if sr != 16000 or audio.shape[1] != 1 or len(audio) != vad["samples"]:
            raise ValueError(f"Invalid canonical masked waveform for {clip['clip_id']}")
        audio = np.ascontiguousarray(audio[:, 0])
        stream = recognizer.create_stream()
        stream.accept_waveform(sr, audio)
        before = time.perf_counter()
        recognizer.decode_stream(stream)
        elapsed = time.perf_counter() - before
        result = stream.result
        main_words = word_groups(result)
        alt_words = word_groups(result, duration_end=True)
        duration = len(audio) / sr
        peak_ram = proc.memory_info().peak_wset
        raw = {
            "clip_set": clip["set"],
            "gate_no_speech": vad["gate_no_speech"],
            "text": result.text,
            "words": [{"word": w["word"], "start": w["start"], "end": w["end"]}
                      for w in main_words],
            "words_duration_end": [
                {"word": w["word"], "start": w["start"], "end": w["end"]}
                for w in alt_words
            ],
            "meta": {
                "runtime": "sherpa-onnx 2.0.3",
                "runtime_package": "sherpa-onnx-core 2.0.3",
                "model": ARTIFACT, "model_sha256": model_digest,
                "requested_device": "cpu", "actual_device": "cpu",
                "threads": 4, "sample_rate_hz": sr, "channels": 1,
                "decoding_method": "greedy_search", "model_type": "nemo_transducer",
                "model_bytes": model_bytes, "wall_seconds": elapsed,
                "peak_working_set_bytes": peak_ram,
                "token_timestamps": list(result.timestamps),
                "token_durations": list(result.durations), "tokens": list(result.tokens),
            },
        }
        (OUT / f"{clip['clip_id']}.json").write_text(
            json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")
        rows.append({
            "schema_version": 2, "candidate": "sherpa-parakeet",
            "clip_id": clip["clip_id"], "clip_set": clip["set"],
            "gate_no_speech": vad["gate_no_speech"], "category": clip["category"],
            "run": {"kind": "cold", "index": 0, "process_id": os.getpid()},
            "hardware": {"cpu": platform.processor(), "gpu": "AMD Radeon RX 7900 XT",
                         "ram_bytes": psutil.virtual_memory().total,
                         "os": platform.platform(),
                         "driver": "32.0.32029.2010 (Adrenalin 26.20.29.02)"},
            "device": {"requested": "cpu", "actual": "cpu"},
            "runtime": {"name": "sherpa-onnx", "version": "2.0.3",
                        "package_version": "sherpa-onnx==2.0.3",
                        "installed_bytes": installed_bytes()},
            "model": {"artifact_id": ARTIFACT, "sha256": model_digest,
                      "bytes": model_bytes, "cache_bytes": 0},
            "settings": {"language": "en", "sample_rate_hz": sr, "channels": 1,
                         "threads": 4, "decoding": {"method": "greedy_search",
                                                     "model_type": "nemo_transducer"}},
            "input": {"sample_rate_hz": sr, "channels": 1, "dtype": "float32",
                      "clip_sha256": vad["sha256"]},
            "measurements": {"audio_duration_s": duration, "runtime_s": elapsed,
                             "rtf": elapsed / duration if duration else None,
                             "peak_ram_bytes": peak_ram, "peak_vram_bytes": None,
                             "peak_vram_method": "Unavailable; CPU execution",
                             "model_footprint_bytes": model_bytes},
            "hypothesis": {"text": result.text, "words": [
                {"text": w["word"], "start_s": w["start"], "end_s": w["end"]}
                for w in main_words]},
            "metrics": {},
        })
        print(f"{clip['clip_id']} gate_no_speech={vad['gate_no_speech']} "
              f"chars={len(result.text)}", flush=True)
    with (OUT.parent / "results.jsonl").open("w", encoding="utf-8") as dst:
        for row in rows:
            dst.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(f"Completed {len(rows)} masked clips; peak_ram_bytes={proc.memory_info().peak_wset}")


if __name__ == "__main__":
    main()
