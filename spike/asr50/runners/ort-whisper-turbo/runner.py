"""Minimal Whisper q4 ONNX runner for the WP12 benchmark."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import pathlib
import struct
import threading
import time
import wave

import numpy as np
import onnxruntime as ort
import psutil
from tokenizers import Tokenizer
from transformers import WhisperFeatureExtractor


MODEL = pathlib.Path(r"C:\scratch\asr50\models\whisper-large-v3-turbo-onnx-merged-q4")
CLIPS = pathlib.Path(r"C:\scratch\asr50\WP6\audio16k")
OUT = pathlib.Path(r"C:\scratch\asr50\results\ort-whisper-turbo")
MODEL_ID = "whisper-large-v3-turbo-onnx-merged-q4"


def read_wav(path: pathlib.Path) -> np.ndarray:
    data = path.read_bytes()
    if data[:4] != b"RIFF" or data[8:12] != b"WAVE":
        raise ValueError(f"Expected RIFF/WAVE: {path}")
    offset = 12
    fmt = None
    raw = None
    while offset + 8 <= len(data):
        chunk = data[offset:offset + 4]
        size = struct.unpack_from("<I", data, offset + 4)[0]
        body = offset + 8
        if chunk == b"fmt ":
            fmt = struct.unpack_from("<HHIIHH", data, body)
        elif chunk == b"data":
            raw = data[body:body + size]
        offset = body + size + (size & 1)
    if fmt is None or raw is None:
        raise ValueError(f"Missing WAV fmt/data chunk: {path}")
    tag, channels, rate, _, block_align, bits = fmt
    if (tag, channels, rate, block_align, bits) != (3, 1, 16000, 4, 32):
        raise ValueError(f"Expected mono 16kHz 32-bit float WAV: {path} (fmt={fmt})")
    samples = np.frombuffer(raw, dtype="<f4").copy()
    if not np.isfinite(samples).all():
        raise ValueError(f"Non-finite audio samples: {path}")
    return samples


def sha(path: pathlib.Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def ort_footprint() -> int:
    site_packages = pathlib.Path(ort.__file__).resolve().parent.parent
    roots = [site_packages / "onnxruntime", *site_packages.glob("onnxruntime*.dist-info")]
    return sum(p.stat().st_size for root in roots if root.exists()
               for p in ([root] if root.is_file() else root.rglob("*")) if p.is_file())


def make_session(path: pathlib.Path, provider: str, threads: int, profile: bool, device_id: int):
    opts = ort.SessionOptions()
    opts.intra_op_num_threads = threads
    opts.inter_op_num_threads = 1
    opts.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
    opts.enable_profiling = profile
    opts.log_severity_level = 0 if profile else 3
    if profile:
        profile_dir = pathlib.Path(r"C:\scratch\asr50\WP12\profiles")
        profile_dir.mkdir(parents=True, exist_ok=True)
        opts.profile_file_prefix = str(profile_dir / f"{provider}_{path.stem}")
    providers = ([(provider, {"device_id": device_id}), "CPUExecutionProvider"]
                 if provider == "DmlExecutionProvider" else ["CPUExecutionProvider"])
    return ort.InferenceSession(str(path), sess_options=opts, providers=providers)


def transcribe(samples: np.ndarray, encoder, decoder, decoder_past, tokenizer, generation):
    features = WhisperFeatureExtractor.from_pretrained(
        str(MODEL), local_files_only=True
    )(samples, sampling_rate=16000, padding="max_length", max_length=480000,
      truncation=True, return_tensors="np").input_features.astype(np.float32)
    if features.shape != (1, 128, 3000) or not np.isfinite(features).all():
        raise ValueError(f"Bad Whisper feature tensor: {features.shape}")
    hidden = encoder.run(["last_hidden_state"], {"input_features": features})[0]
    ids = [int(generation["decoder_start_token_id"]),
           int(generation["lang_to_id"]["<|en|>"]),
           int(generation["task_to_id"]["transcribe"]),
           int(generation["no_timestamps_token_id"])]
    dec_inputs = {x.name: None for x in decoder.get_inputs()}
    dec_inputs["input_ids"] = np.asarray([ids], dtype=np.int64)
    dec_inputs["encoder_hidden_states"] = hidden
    dec_inputs["use_cache_branch"] = np.asarray([False], dtype=np.bool_)
    for name in dec_inputs:
        if name.startswith("past_key_values."):
            dec_inputs[name] = np.zeros((1, 20, 0, 64), dtype=np.float32)
    output_names = [x.name for x in decoder.get_outputs()]
    outputs = decoder.run(output_names, dec_inputs)
    logits = outputs[output_names.index("logits")]
    past = {}
    for i, name in enumerate(output_names):
        if name.startswith("present."):
            past[name.replace("present.", "past_key_values.", 1)] = outputs[i]
    suppress = set(generation.get("suppress_tokens", []))
    begin_suppress = set(generation.get("begin_suppress_tokens", []))
    eos = int(generation["eos_token_id"])
    max_new = min(444, int(generation.get("max_length", 448)) - len(ids))
    generated = []
    token = None
    for step in range(max_new):
        row = logits[0, -1].astype(np.float32, copy=True)
        row[list(suppress)] = -np.inf
        if step == 0:
            row[list(begin_suppress)] = -np.inf
        token = int(np.argmax(row))
        if token == eos:
            break
        generated.append(token)
        feeds = {"input_ids": np.asarray([[token]], dtype=np.int64), **past}
        out_names = [x.name for x in decoder_past.get_outputs()]
        step_out = decoder_past.run(out_names, feeds)
        logits = step_out[out_names.index("logits")]
        next_past = {name.replace("present.", "past_key_values.", 1): step_out[i]
                     for i, name in enumerate(out_names) if name.startswith("present.")}
        next_past.update({name: value for name, value in past.items()
                          if ".encoder." in name})
        past = next_past
    return tokenizer.decode(generated, skip_special_tokens=True).strip(), features


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--device", choices=["cpu", "dml"], required=True)
    ap.add_argument("--threads", type=int, default=12)
    ap.add_argument("--device-id", type=int, default=0)
    ap.add_argument("--profile", action="store_true")
    ap.add_argument("--run-kind", default="warm")
    ap.add_argument("--run-index", type=int, default=1)
    ap.add_argument("--repeat", type=int, default=1)
    args = ap.parse_args()
    provider = "DmlExecutionProvider" if args.device == "dml" else "CPUExecutionProvider"
    proc = psutil.Process()
    peak = [proc.memory_info().rss]
    stopping = threading.Event()

    def sample_ram():
        while not stopping.wait(.2):
            try:
                peak[0] = max(peak[0], proc.memory_info().rss)
            except psutil.Error:
                pass

    monitor = threading.Thread(target=sample_ram, daemon=True)
    monitor.start()
    t0 = time.perf_counter()
    encoder = make_session(MODEL / "onnx" / "encoder_model_q4.onnx", provider,
                           args.threads, args.profile, args.device_id)
    t_encoder = time.perf_counter()
    decoder = make_session(MODEL / "onnx" / "decoder_model_merged_q4.onnx", provider,
                           args.threads, args.profile, args.device_id)
    t_decoder = time.perf_counter()
    decoder_past = make_session(MODEL / "onnx" / "decoder_with_past_model_q4.onnx", provider,
                                args.threads, args.profile, args.device_id)
    t_loaded = time.perf_counter()
    tokenizer = Tokenizer.from_file(str(MODEL / "tokenizer.json"))
    generation = json.loads((MODEL / "generation_config.json").read_text(encoding="utf-8"))
    truth = {c["clip_id"]: c for c in json.loads((CLIPS / "ground_truth.json").read_text(encoding="utf-8"))["clips"]}
    wavs = sorted(CLIPS.glob("*.wav"))
    records = []
    total_audio = total_runtime = 0.0
    for repeat in range(args.repeat):
        for wav in wavs:
            samples = read_wav(wav)
            started = time.perf_counter()
            text, features = transcribe(samples, encoder, decoder, decoder_past, tokenizer, generation)
            elapsed = time.perf_counter() - started
            clip_id = wav.stem
            seconds = len(samples) / 16000
            item = {"schema_version": 1, "candidate": "ort-whisper-turbo",
                    "clip_id": clip_id, "category": truth[clip_id]["category"],
                    "run": {"kind": args.run_kind, "index": args.run_index + repeat,
                            "process_id": os.getpid()},
                    "hardware": {"cpu": "AMD Ryzen 9 9900X", "gpu": "AMD Radeon RX 7900 XT" if args.device == "dml" else None,
                                 "ram_bytes": 31_600_000_000, "os": "Windows 11 Pro build 26300",
                                 "driver": "32.0.32029.2010" if args.device == "dml" else None},
                    "device": {"requested": args.device, "actual": "CPUExecutionProvider" if args.device == "cpu" else "DmlExecutionProvider+CPUExecutionProvider (profile-verified mixed; device_id=0)"},
                    "runtime": {"name": "ONNX Runtime", "version": ort.__version__, "package_version": ort.__version__,
                                "installed_bytes": ort_footprint()},
                    "model": {"artifact_id": MODEL_ID, "sha256": "8b933ac24074a24a1635084d06a4ed37e387ef22d980f184a5fc27418e9ceeb8",
                              "bytes": sum(p.stat().st_size for p in (MODEL / "onnx").glob("*.onnx")),
                              "cache_bytes": 0},
                    "settings": {"language": "en", "sample_rate_hz": 16000, "channels": 1, "threads": args.threads,
                                 "decoding": {"greedy": True, "max_new_tokens": 444, "timestamps": False}},
                    "input": {"sample_rate_hz": 16000, "channels": 1, "dtype": "float32", "clip_sha256": sha(wav)},
                    "measurements": {"audio_duration_s": seconds, "runtime_s": elapsed,
                                     "rtf": elapsed / seconds, "peak_ram_bytes": None,
                                     "peak_vram_bytes": None, "peak_vram_method": "not measured",
                                     "model_footprint_bytes": sum(p.stat().st_size for p in (MODEL / "onnx").glob("*.onnx"))},
                    "hypothesis": {"text": text, "words": []},
                    "metrics": {"feature_min": float(features.min()), "feature_max": float(features.max()),
                                "feature_mean": float(features.mean())}}
            records.append(item)
            total_audio += seconds
            total_runtime += elapsed
            print(json.dumps({"clip": clip_id, "text": text, "seconds": elapsed,
                              "audio_s": seconds, "feature_range": [float(features.min()), float(features.max())]}), flush=True)
    stopping.set()
    monitor.join()
    for rec in records:
        rec["measurements"]["peak_ram_bytes"] = peak[0]
        rec["measurements"]["cold_session_load_s"] = t_loaded - t0
        rec["measurements"]["encoder_session_load_s"] = t_encoder - t0
        rec["measurements"]["merged_decoder_session_load_s"] = t_decoder - t_encoder
        rec["measurements"]["with_past_decoder_session_load_s"] = t_loaded - t_decoder
    OUT.mkdir(parents=True, exist_ok=True)
    outdir = OUT / args.device
    outdir.mkdir(parents=True, exist_ok=True)
    for rec in records:
        raw = {"text": rec["hypothesis"]["text"], "words": [],
               "meta": {"runtime": "onnxruntime", "runtime_version": ort.__version__,
                        "model_artifact": MODEL_ID, "model_sha256": rec["model"]["sha256"],
                        "requested_device": args.device, "actual_device": rec["device"]["actual"],
                        "settings": rec["settings"], "thread_count": args.threads,
                        "wall_seconds": rec["measurements"]["runtime_s"],
                        "peak_working_set_bytes": rec["measurements"]["peak_ram_bytes"],
                        "peak_dedicated_gpu_bytes": rec["measurements"]["peak_vram_bytes"],
                        "run_kind": rec["run"]["kind"], "run_index": rec["run"]["index"]}}
        (outdir / f"{rec['clip_id']}_{args.run_kind}_{rec['run']['index']}.json").write_text(
            json.dumps(raw, indent=2), encoding="utf-8")
        (outdir / f"{rec['clip_id']}.json").write_text(json.dumps(raw, indent=2), encoding="utf-8")
    with (OUT / "results.jsonl").open("a", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    if args.profile:
        for label, session in (("encoder", encoder), ("decoder", decoder), ("decoder_past", decoder_past)):
            print(f"PROFILE {label} {session.end_profiling()}", flush=True)
    print(json.dumps({"load_s": t_loaded - t0, "inference_s": total_runtime,
                      "audio_s": total_audio, "rtf": total_runtime / total_audio,
                      "peak_ram_bytes": peak[0], "providers": {
                          "encoder": encoder.get_providers(), "decoder": decoder.get_providers(),
                          "decoder_past": decoder_past.get_providers()}}), flush=True)


if __name__ == "__main__":
    main()
