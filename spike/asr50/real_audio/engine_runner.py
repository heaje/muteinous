"""Checkpointed, serial ASR runners for the approved WP24 real-audio sample."""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
import soundfile as sf

ROOT = Path(r"C:\scratch\asr50\WP24")
MODELS = Path(r"C:\scratch\asr50\models")
CLI_ROOT = Path(r"C:\scratch\asr50\WP2\artifacts")
OFFLINE = {
    "HF_HUB_OFFLINE": "1",
    "TRANSFORMERS_OFFLINE": "1",
    "HF_HUB_DISABLE_TELEMETRY": "1",
}


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def should_skip(output: Path) -> bool:
    if not output.exists():
        return False
    previous = json.loads(output.read_text(encoding="utf-8"))
    if not previous.get("error"):
        return True
    attempt_dir = output.parent / "failed_attempts"
    write_json(attempt_dir / output.name, previous)
    return False


def load_sample():
    doc = json.loads((ROOT / "sample_manifest.json").read_text(encoding="utf-8"))
    return doc["sampled"]


def read_audio(path: Path) -> np.ndarray:
    audio, sr = sf.read(path, dtype="float32", always_2d=True)
    if sr != 16000 or audio.shape[1] != 1:
        raise ValueError(f"expected 16 kHz mono float32 WAV: {path.name}")
    return np.ascontiguousarray(audio[:, 0], dtype=np.float32)


def run_library(engine: str, rows: list[dict]) -> None:
    if engine == "parakeet":
        import sherpa_onnx
        model = MODELS / "parakeet-tdt-0-6b-v2-sherpa-onnx-int8"
        recognizer = sherpa_onnx.OfflineRecognizer.from_transducer(
            str(model / "encoder.int8.onnx"), str(model / "decoder.int8.onnx"),
            str(model / "joiner.int8.onnx"), str(model / "tokens.txt"),
            num_threads=4, sample_rate=16000, feature_dim=80, dither=0.0,
            decoding_method="greedy_search", provider="cpu",
            model_type="nemo_transducer", debug=False,
        )
        for i, row in enumerate(rows, 1):
            path = Path(row["wav"])
            out = ROOT / "results" / engine / f"{row['clip_id']}.json"
            if should_skip(out):
                continue
            started = time.perf_counter()
            try:
                audio = read_audio(path)
                stream = recognizer.create_stream()
                stream.accept_waveform(16000, audio)
                recognizer.decode_stream(stream)
                result = stream.result
                words, groups = [], []
                for j, token in enumerate(result.tokens):
                    begins = token.startswith("▁") or token[:1].isspace()
                    piece = token[1:] if token.startswith("▁") else token.lstrip()
                    if begins or not groups:
                        groups.append({"text": piece, "indexes": [j]})
                    else:
                        groups[-1]["text"] += piece
                        groups[-1]["indexes"].append(j)
                times, durations = list(result.timestamps), list(result.durations)
                for k, group in enumerate(groups):
                    first, last = group["indexes"][0], group["indexes"][-1]
                    start = float(times[first]) if first < len(times) else None
                    end = (float(times[groups[k + 1]["indexes"][0]])
                           if k + 1 < len(groups) and groups[k + 1]["indexes"][0] < len(times)
                           else float(times[last] + durations[last])
                           if last < len(times) and last < len(durations) else None)
                    tokens = re.findall(r"[^\W_]+(?:['’][^\W_]+)*", group["text"], re.UNICODE)
                    if tokens:
                        words.append({"text": " ".join(tokens), "start": start, "end": end})
                text = " ".join(w["text"] for w in words)
                record = {"clip_id": row["clip_id"], "text": text, "words": words,
                          "error": None, "meta": {"runtime": f"sherpa-onnx {sherpa_onnx.__version__}",
                          "requested_device": "cpu", "actual_device": "cpu", "threads": 4,
                          "wall_seconds": time.perf_counter() - started}}
            except Exception as exc:
                record = {"clip_id": row["clip_id"], "text": "", "words": [],
                          "error": f"{type(exc).__name__}: {exc}",
                          "meta": {"requested_device": "cpu", "actual_device": "cpu",
                                   "wall_seconds": time.perf_counter() - started}}
            write_json(out, record)
            print(f"{engine} checkpoint {i}/{len(rows)} status={'error' if record['error'] else 'ok'}",
                  flush=True)
    elif engine == "faster-whisper":
        from faster_whisper import WhisperModel
        import ctranslate2
        import faster_whisper
        model_path = MODELS / "whisper-small-en-faster-whisper-ct2"
        model = WhisperModel(str(model_path), device="cpu", compute_type="int8",
                             cpu_threads=4)
        for i, row in enumerate(rows, 1):
            out = ROOT / "results" / engine / f"{row['clip_id']}.json"
            if should_skip(out):
                continue
            started = time.perf_counter()
            try:
                audio = read_audio(Path(row["wav"]))
                segments, _ = model.transcribe(audio, language="en", beam_size=5,
                                               word_timestamps=True, vad_filter=False)
                segments = list(segments)
                words = [{"text": word.word, "start": word.start, "end": word.end}
                         for seg in segments if seg.words for word in seg.words]
                text = "".join(seg.text for seg in segments).strip()
                record = {"clip_id": row["clip_id"], "text": text, "words": words,
                          "error": None, "meta": {"runtime": f"faster-whisper {faster_whisper.__version__}",
                          "ctranslate2": ctranslate2.__version__, "model": model_path.name,
                          "requested_device": "cpu", "actual_device": "cpu",
                          "compute_type": "int8", "beam_size": 5, "vad_filter": False,
                          "threads": 4, "wall_seconds": time.perf_counter() - started}}
            except Exception as exc:
                record = {"clip_id": row["clip_id"], "text": "", "words": [],
                          "error": f"{type(exc).__name__}: {exc}",
                          "meta": {"requested_device": "cpu", "actual_device": "cpu",
                                   "wall_seconds": time.perf_counter() - started}}
            write_json(out, record)
            print(f"{engine} checkpoint {i}/{len(rows)} status={'error' if record['error'] else 'ok'}",
                  flush=True)
    else:
        raise ValueError(engine)


def merge_whisper_tokens(doc: dict) -> tuple[str, list[dict]]:
    groups = []
    for segment in doc.get("transcription", []):
        for token in segment.get("tokens", []):
            raw = token.get("text", "")
            stripped = raw.strip()
            if not raw or raw.startswith("[_") or stripped.startswith("[_"):
                continue
            if not re.search(r"[\w]", stripped, re.UNICODE):
                continue
            start = token.get("offsets", {}).get("from")
            end = token.get("offsets", {}).get("to")
            start = start / 1000 if isinstance(start, (int, float)) else None
            end = end / 1000 if isinstance(end, (int, float)) else None
            if raw[:1].isspace() or not groups:
                groups.append({"text": stripped, "start": start, "end": end})
            else:
                groups[-1]["text"] += stripped
                groups[-1]["end"] = end
    words = []
    for group in groups:
        text = re.sub(r"^[^\w']+|[^\w']+$", "", group["text"], flags=re.UNICODE)
        if text and text.casefold() != "blank_audio":
            words.append({"text": text, "start": group["start"], "end": group["end"]})
    return " ".join(w["text"] for w in words), words


def run_whispercpp(model_key: str, device: str, rows: list[dict]) -> None:
    if model_key == "turbo":
        model = MODELS / "whisper-large-v3-turbo-whisper-cpp-q5-0" / "ggml-large-v3-turbo-q5_0.bin"
        label = "whispercpp-turbo"
    else:
        model = MODELS / "whisper-small-en-whisper-cpp-q5-1" / "ggml-small.en-q5_1.bin"
        label = "whispercpp-small-en"
    build = "whisper-vulkan-dl-windows-x64" if device == "vulkan" else "whisper-cpu-dl-windows-x64"
    binary = CLI_ROOT / build / "whisper-cli.exe"
    engine = f"{label}-{device}"
    output_dir = ROOT / "results" / engine
    log_dir = ROOT / "logs" / engine
    output_dir.mkdir(parents=True, exist_ok=True)
    log_dir.mkdir(parents=True, exist_ok=True)
    for i, row in enumerate(rows, 1):
        output = output_dir / f"{row['clip_id']}.json"
        if should_skip(output):
            continue
        outbase = log_dir / row["clip_id"]
        dtw = "large.v3.turbo" if model_key == "turbo" else "small.en"
        cmd = [str(binary), "-m", str(model), "-f", row["wav"], "-l", "en",
               "-t", "4", "-ojf", "-of", str(outbase), "-nfa", "-dtw", dtw]
        cmd += ["-dev", "0"] if device == "vulkan" else ["-ng"]
        started = time.perf_counter()
        try:
            candidate = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                         text=True, errors="replace", env=os.environ | OFFLINE)
            pid = candidate.pid
            log, _ = candidate.communicate(timeout=180)
            (log_dir / f"{row['clip_id']}.log").write_text(log, encoding="utf-8")
            json_path = Path(str(outbase) + ".json")
            if candidate.returncode != 0 or not json_path.is_file():
                raise RuntimeError(f"exit={candidate.returncode}; output missing={not json_path.is_file()}")
            doc = json.loads(json_path.read_text(encoding="utf-8"))
            text, words = merge_whisper_tokens(doc)
            vulkan_line = "using Vulkan0 backend" in log
            if device == "vulkan" and not vulkan_line:
                raise RuntimeError("Vulkan0 backend log line missing")
            record = {"clip_id": row["clip_id"], "text": text, "words": words,
                      "error": None, "meta": {"runtime": "whisper.cpp",
                      "model": model.parent.name, "requested_device": device,
                      "actual_device": "Vulkan0" if vulkan_line else "CPU",
                      "backend_log_verified": vulkan_line,
                      "threads": 4, "wall_seconds": time.perf_counter() - started,
                      "pid": pid, "exit_code": candidate.returncode}}
        except Exception as exc:
            if "candidate" in locals() and candidate.poll() is None:
                candidate.kill()
                candidate.wait()
            record = {"clip_id": row["clip_id"], "text": "", "words": [],
                      "error": f"{type(exc).__name__}: {exc}",
                      "meta": {"requested_device": device,
                               "wall_seconds": time.perf_counter() - started}}
        write_json(output, record)
        print(f"{engine} checkpoint {i}/{len(rows)} status={'error' if record['error'] else 'ok'}",
              flush=True)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--engine", required=True,
                   choices=["parakeet", "faster-whisper", "whispercpp-turbo",
                            "whispercpp-small-en"])
    p.add_argument("--device", choices=["cpu", "vulkan"], default="cpu")
    a = p.parse_args()
    os.environ.update(OFFLINE)
    rows = load_sample()
    if a.engine.startswith("whispercpp-"):
        if a.device not in ("cpu", "vulkan"):
            raise ValueError(a.device)
        run_whispercpp(a.engine.removeprefix("whispercpp-"), a.device, rows)
    else:
        if a.device != "cpu":
            raise ValueError("requested libraries are CPU-only")
        run_library(a.engine, rows)


if __name__ == "__main__":
    main()
