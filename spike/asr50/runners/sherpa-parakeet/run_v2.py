"""Run Parakeet TDT int8 over the frozen corpus-v2 inputs."""
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

CORPUS = pathlib.Path(r"C:\scratch\asr50\corpus_v2_frozen")
OUT = pathlib.Path(r"C:\scratch\asr50\results_v2\sherpa-parakeet\cpu")
MODEL = pathlib.Path(r"C:\scratch\asr50\models\parakeet-tdt-0-6b-v2-sherpa-onnx-int8")
ARTIFACT = "parakeet-tdt-0-6b-v2-sherpa-onnx-int8"
os.environ.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1",
                  HF_HUB_DISABLE_TELEMETRY="1")


def file_sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def installed_bytes():
    total = 0
    for package in ("sherpa-onnx", "sherpa-onnx-core"):
        for entry in importlib.metadata.distribution(package).files or ():
            try:
                total += entry.locate().stat().st_size
            except OSError:
                pass
    return total


def word_groups(result, duration_end=False):
    """SentencePiece leading whitespace/▁ starts words; attach token timings."""
    tokens = list(result.tokens)
    timestamps = list(result.timestamps)
    durations = list(result.durations)
    groups = []
    for i, token in enumerate(tokens):
        is_start = token.startswith("▁") or token[:1].isspace()
        piece = token[1:] if token.startswith("▁") else token.lstrip()
        if is_start or not groups:
            groups.append({"text": piece, "indices": [i]})
        else:
            groups[-1]["text"] += piece
            groups[-1]["indices"].append(i)
    words = []
    for gi, group in enumerate(groups):
        first, last = group["indices"][0], group["indices"][-1]
        start = float(timestamps[first]) if first < len(timestamps) else None
        if duration_end and last < len(timestamps) and last < len(durations):
            end = float(timestamps[last]) + float(durations[last])
        elif gi + 1 < len(groups):
            next_first = groups[gi + 1]["indices"][0]
            end = float(timestamps[next_first]) if next_first < len(timestamps) else None
        else:
            end = (float(timestamps[last]) + float(durations[last])
                   if last < len(timestamps) and last < len(durations) else None)
        lexical = re.findall(r"[^\W_]+(?:'[^\W_]+)*", group["text"], flags=re.UNICODE)
        if lexical:
            words.append({"word": " ".join(lexical), "start": start, "end": end})
    return words


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    truth = json.loads((CORPUS / "ground_truth_v2.json").read_text(encoding="utf-8"))
    clips = truth["clips"]
    if len(clips) != 60:
        raise ValueError(f"Expected frozen corpus-v2 size 60; got {len(clips)}")
    names = [clip.get("wav", f"{clip['clip_id']}.wav") for clip in clips]
    for clip, name in zip(clips, names):
        path = CORPUS / name
        if file_sha256(path) != clip["wav_sha256"]:
            raise ValueError(f"Corpus-v2 hash mismatch: {name}")

    encoder, decoder, joiner, tokens = [
        MODEL / "encoder.int8.onnx", MODEL / "decoder.int8.onnx",
        MODEL / "joiner.int8.onnx", MODEL / "tokens.txt"
    ]
    model_files = [encoder, decoder, joiner, tokens]
    artifact_hash = hashlib.sha256(
        "".join(file_sha256(f) for f in model_files).encode("ascii")).hexdigest()
    model_bytes = sum(f.stat().st_size for f in model_files)
    load_start = time.perf_counter()
    recognizer = sherpa_onnx.OfflineRecognizer.from_transducer(
        str(encoder), str(decoder), str(joiner), str(tokens),
        num_threads=4, sample_rate=16000, feature_dim=80, dither=0.0,
        decoding_method="greedy_search", provider="cpu",
        model_type="nemo_transducer", debug=True,
    )
    model_load_s = time.perf_counter() - load_start
    proc = psutil.Process()
    observations = []
    for clip, name in zip(clips, names):
        wav_path = CORPUS / name
        audio, sr = sf.read(wav_path, dtype="float32", always_2d=True)
        if sr != 16000 or audio.shape[1] != 1:
            raise ValueError(f"Expected 16 kHz mono float32 WAV: {name}; sr={sr}, shape={audio.shape}")
        audio = np.ascontiguousarray(audio[:, 0])
        stream = recognizer.create_stream()
        stream.accept_waveform(sr, audio)
        start = time.perf_counter()
        recognizer.decode_stream(stream)
        elapsed = time.perf_counter() - start
        result = stream.result
        normal_words = word_groups(result)
        duration_words = word_groups(result, duration_end=True)
        audio_duration = len(audio) / sr
        peak_ram = proc.memory_info().peak_wset
        normalized = {
            "clip_set": clip["set"],
            "text": result.text,
            "words": [{"word": w["word"], "start": w["start"], "end": w["end"]}
                      for w in normal_words],
            "words_duration_end": [
                {"word": w["word"], "start": w["start"], "end": w["end"]}
                for w in duration_words
            ],
            "meta": {
                "runtime": "sherpa-onnx 2.0.3", "runtime_package": "sherpa-onnx-core 2.0.3",
                "model": ARTIFACT, "model_sha256": artifact_hash, "model_bytes": model_bytes,
                "requested_device": "cpu", "actual_device": "cpu",
                "provider_verified_by": "CPU requested; successful offline decode, no fallback warning",
                "threads": 4, "sample_rate_hz": sr, "channels": 1,
                "decoding_method": "greedy_search", "model_type": "nemo_transducer",
                "model_load_s": model_load_s, "wall_seconds": elapsed,
                "peak_working_set_bytes": peak_ram,
                "token_timestamps": list(result.timestamps),
                "token_durations": list(result.durations),
                "tokens": list(result.tokens),
            },
        }
        raw_path = OUT / f"{clip['clip_id']}.json"
        raw_path.write_text(json.dumps(normalized, ensure_ascii=False, indent=2),
                            encoding="utf-8")
        observations.append({
            "schema_version": 2,
            "candidate": "sherpa-parakeet",
            "clip_id": clip["clip_id"],
            "clip_set": clip["set"],
            "category": clip["category"],
            "run": {"kind": "cold", "index": 0, "process_id": os.getpid()},
            "hardware": {
                "cpu": platform.processor(), "gpu": "AMD Radeon RX 7900 XT",
                "ram_bytes": psutil.virtual_memory().total, "os": platform.platform(),
                "driver": "32.0.32029.2010 (Adrenalin 26.20.29.02)",
            },
            "device": {"requested": "cpu", "actual": "cpu"},
            "runtime": {"name": "sherpa-onnx", "version": "2.0.3",
                        "package_version": "sherpa-onnx==2.0.3",
                        "installed_bytes": installed_bytes()},
            "model": {"artifact_id": ARTIFACT, "sha256": artifact_hash,
                      "bytes": model_bytes, "cache_bytes": 0},
            "settings": {"language": "en", "sample_rate_hz": sr, "channels": 1,
                         "threads": 4, "decoding": {"method": "greedy_search",
                                                     "model_type": "nemo_transducer"}},
            "input": {"sample_rate_hz": sr, "channels": 1, "dtype": "float32",
                      "clip_sha256": clip["wav_sha256"]},
            "measurements": {
                "audio_duration_s": audio_duration, "runtime_s": elapsed,
                "rtf": elapsed / audio_duration if audio_duration else None,
                "peak_ram_bytes": peak_ram, "peak_vram_bytes": None,
                "peak_vram_method": "Unavailable; CPU execution",
                "model_footprint_bytes": model_bytes, "model_load_s": model_load_s,
            },
            "hypothesis": {"text": result.text,
                           "words": [{"text": w["word"], "start_s": w["start"],
                                      "end_s": w["end"]} for w in normal_words]},
            "metrics": {},
        })
        print(f"{clip['clip_id']} ({clip['set']}/{clip['category']}): "
              f"{len(audio)/sr:.2f}s -> {len(result.text)} chars", flush=True)
    with (OUT.parent / "results.jsonl").open("w", encoding="utf-8") as dst:
        for row in observations:
            dst.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(f"Completed {len(observations)} clips; model_load_s={model_load_s:.3f}; "
          f"peak_ram_bytes={proc.memory_info().peak_wset}")


if __name__ == "__main__":
    main()
