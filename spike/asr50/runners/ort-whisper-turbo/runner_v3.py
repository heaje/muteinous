"""Corpus-v2 runner: fixed 30-second chunking and optional prototype silence gate."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import pathlib
import struct

import numpy as np
import onnxruntime as ort
from tokenizers import Tokenizer
from transformers import WhisperFeatureExtractor

MODEL = pathlib.Path(r"C:\scratch\asr50\models\whisper-large-v3-turbo-onnx-merged-q4")
CORPUS = pathlib.Path(r"C:\scratch\asr50\corpus_v2_frozen")
OUT = pathlib.Path(r"C:\scratch\asr50\results_v2\ort-whisper-turbo")
SAMPLE_RATE = 16000
WINDOW = 30 * SAMPLE_RATE
ENERGY_RMS_THRESHOLD = 0.003


def sha(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def ort_footprint() -> int:
    site = pathlib.Path(ort.__file__).resolve().parent.parent
    roots = [site / "onnxruntime", *site.glob("onnxruntime*.dist-info")]
    return sum(item.stat().st_size for root in roots if root.exists()
               for item in ([root] if root.is_file() else root.rglob("*")) if item.is_file())


def read_float_wav(path: pathlib.Path) -> np.ndarray:
    data = path.read_bytes()
    if data[:4] != b"RIFF" or data[8:12] != b"WAVE":
        raise ValueError(f"Expected RIFF/WAVE: {path}")
    offset = 12
    fmt = raw = None
    while offset + 8 <= len(data):
        kind = data[offset:offset + 4]
        size = struct.unpack_from("<I", data, offset + 4)[0]
        body = offset + 8
        if kind == b"fmt ":
            fmt = struct.unpack_from("<HHIIHH", data, body)
        elif kind == b"data":
            raw = data[body:body + size]
        offset = body + size + (size & 1)
    if fmt is None or raw is None:
        raise ValueError(f"Missing WAV fmt/data: {path}")
    tag, channels, rate, _, align, bits = fmt
    if (tag, channels, rate, align, bits) != (3, 1, SAMPLE_RATE, 4, 32):
        raise ValueError(f"Expected mono 16-kHz float32 WAV: {path}; fmt={fmt}")
    samples = np.frombuffer(raw, dtype="<f4").copy()
    if not np.isfinite(samples).all():
        raise ValueError(f"Non-finite sample in {path}")
    return samples


def create_session(graph: pathlib.Path, provider: str):
    opts = ort.SessionOptions()
    opts.intra_op_num_threads = 12 if provider == "CPUExecutionProvider" else 4
    opts.inter_op_num_threads = 1
    opts.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
    providers = ([(provider, {"device_id": 0}), "CPUExecutionProvider"]
                 if provider == "DmlExecutionProvider" else ["CPUExecutionProvider"])
    return ort.InferenceSession(str(graph), sess_options=opts, providers=providers)


def decode_window(audio, extractor, encoder, decoder, decoder_past, tokenizer, gen):
    feature = extractor(audio, sampling_rate=SAMPLE_RATE, padding="max_length",
                        max_length=WINDOW, truncation=True, return_tensors="np"
                        ).input_features.astype(np.float32)
    if feature.shape != (1, 128, 3000) or not np.isfinite(feature).all():
        raise ValueError(f"Bad feature shape/values: {feature.shape}")
    hidden = encoder.run(["last_hidden_state"], {"input_features": feature})[0]
    ids = [int(gen["decoder_start_token_id"]), int(gen["lang_to_id"]["<|en|>"]),
           int(gen["task_to_id"]["transcribe"]), int(gen["no_timestamps_token_id"])]
    feeds = {"input_ids": np.asarray([ids], dtype=np.int64),
             "encoder_hidden_states": hidden, "use_cache_branch": np.asarray([False], dtype=np.bool_)}
    for item in decoder.get_inputs():
        if item.name.startswith("past_key_values."):
            feeds[item.name] = np.zeros((1, 20, 0, 64), dtype=np.float32)
    names = [x.name for x in decoder.get_outputs()]
    result = decoder.run(names, feeds)
    logits = result[names.index("logits")]
    past = {n.replace("present.", "past_key_values.", 1): result[i]
            for i, n in enumerate(names) if n.startswith("present.")}
    suppressed = set(gen.get("suppress_tokens", []))
    begin_suppressed = set(gen.get("begin_suppress_tokens", []))
    eos = int(gen["eos_token_id"])
    generated = []
    for step in range(min(444, int(gen.get("max_length", 448)) - len(ids))):
        scores = logits[0, -1].astype(np.float32, copy=True)
        scores[list(suppressed)] = -np.inf
        if step == 0:
            scores[list(begin_suppressed)] = -np.inf
        token = int(np.argmax(scores))
        if token == eos:
            break
        generated.append(token)
        feeds = {"input_ids": np.asarray([[token]], dtype=np.int64), **past}
        names = [x.name for x in decoder_past.get_outputs()]
        result = decoder_past.run(names, feeds)
        logits = result[names.index("logits")]
        next_past = {n.replace("present.", "past_key_values.", 1): result[i]
                     for i, n in enumerate(names) if n.startswith("present.")}
        next_past.update({n: value for n, value in past.items() if ".encoder." in n})
        past = next_past
    return tokenizer.decode(generated, skip_special_tokens=True).strip()


def rms_gate(samples):
    frame = SAMPLE_RATE // 100  # 10 ms
    if len(samples) == 0:
        return True, 0.0
    usable = samples[:len(samples) // frame * frame]
    if len(usable) == 0:
        peak = float(np.sqrt(np.mean(samples.astype(np.float64) ** 2)))
    else:
        frames = usable.reshape(-1, frame).astype(np.float64)
        peak = float(np.sqrt(np.mean(frames * frames, axis=1)).max())
    return peak <= ENERGY_RMS_THRESHOLD, peak


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--device", choices=("cpu", "dml"), required=True)
    ap.add_argument("--corpus-root", type=pathlib.Path, default=CORPUS)
    ap.add_argument("--output-root", type=pathlib.Path, default=OUT)
    ap.add_argument("--ground-truth", type=pathlib.Path)
    ap.add_argument("--vad-manifest", type=pathlib.Path)
    ap.add_argument("--masked-file-manifest", type=pathlib.Path)
    args = ap.parse_args()
    provider = "CPUExecutionProvider" if args.device == "cpu" else "DmlExecutionProvider"
    ground_truth_path = args.ground_truth or (args.corpus_root / "ground_truth_v2.json")
    manifest = json.loads(ground_truth_path.read_text(encoding="utf-8"))
    clips = manifest["clips"]
    vad_flags = {}
    masked_files = {}
    if args.vad_manifest:
        vad_data = json.loads(args.vad_manifest.read_text(encoding="utf-8"))
        vad_flags = {
            c.get("clip_id", pathlib.Path(c["input"]).stem): bool(c["gate_no_speech"])
            for c in vad_data["clips"]
        }
        if set(vad_flags) != {c["clip_id"] for c in clips}:
            raise ValueError("VAD manifest clip IDs do not match ground_truth_v2.json")
    if args.masked_file_manifest:
        vad_data = json.loads(args.masked_file_manifest.read_text(encoding="utf-8"))
        masked_files = {
            c.get("clip_id", pathlib.Path(c["input"]).stem): c["output"]
            for c in vad_data["clips"]
        }
        if set(masked_files) != {c["clip_id"] for c in clips}:
            raise ValueError("Masked manifest clip IDs do not match ground_truth_v2.json")
    extractor = WhisperFeatureExtractor.from_pretrained(str(MODEL), local_files_only=True)
    tokenizer = Tokenizer.from_file(str(MODEL / "tokenizer.json"))
    gen = json.loads((MODEL / "generation_config.json").read_text(encoding="utf-8"))
    encoder = create_session(MODEL / "onnx" / "encoder_model_q4.onnx", provider)
    decoder = create_session(MODEL / "onnx" / "decoder_model_merged_q4.onnx", provider)
    decoder_past = create_session(MODEL / "onnx" / "decoder_with_past_model_q4.onnx", provider)
    actual = ("CPUExecutionProvider" if args.device == "cpu" else
              "DmlExecutionProvider+CPUExecutionProvider (profile-verified mixed; device_id=0)")
    out_dir = args.output_root / args.device
    out_dir.mkdir(parents=True, exist_ok=True)
    records = []
    for clip in clips:
        filename = masked_files.get(clip["clip_id"], clip["wav"])
        path = args.corpus_root / filename
        audio = read_float_wav(path)
        chunks = [audio[start:start + WINDOW] for start in range(0, len(audio), WINDOW)] or [audio]
        text_parts = [decode_window(chunk, extractor, encoder, decoder, decoder_past, tokenizer, gen)
                      for chunk in chunks]
        default_text = " ".join(x for x in text_parts if x).strip()
        gate_value = None
        gate_text = None
        if clip["category"] in ("silence", "non_speech"):
            skipped, peak_rms = rms_gate(audio)
            gate_value = {"method": "max 10-ms frame RMS <= 0.003", "threshold_rms": ENERGY_RMS_THRESHOLD,
                          "peak_frame_rms": peak_rms, "skipped": skipped,
                          "no_speech_probability": None,
                          "no_speech_probability_note": "generation_config.json has no no_speech_token_id"}
            gate_text = "" if skipped else default_text
        rec = {
            "schema_version": 1, "candidate": "ort-whisper-turbo", "clip_id": clip["clip_id"],
            "clip_set": clip["set"], "category": clip["category"], "transcript": clip["transcript"],
            "gate_no_speech": vad_flags.get(clip["clip_id"], False),
            "run": {"kind": "default", "index": 0, "process_id": os.getpid()},
            "hardware": {"cpu": "AMD Ryzen 9 9900X",
                         "gpu": "AMD Radeon RX 7900 XT" if args.device == "dml" else None,
                         "ram_bytes": 31600000000, "os": "Windows 11 Pro build 26300",
                         "driver": "32.0.32029.2010" if args.device == "dml" else None},
            "device": {"requested": args.device, "actual": actual},
            "runtime": {"name": "ONNX Runtime", "version": ort.__version__,
                        "package_version": ort.__version__, "installed_bytes": ort_footprint()},
            "model": {"artifact_id": "whisper-large-v3-turbo-onnx-merged-q4",
                      "sha256": "8b933ac24074a24a1635084d06a4ed37e387ef22d980f184a5fc27418e9ceeb8",
                      "bytes": 1084799335, "cache_bytes": 0},
            "settings": {"language": "en", "sample_rate_hz": SAMPLE_RATE, "channels": 1,
                         "threads": 12 if args.device == "cpu" else 4,
                         "decoding": {"greedy": True, "fixed_chunk_s": 30,
                                      "chunking": "non-overlapping; whitespace concatenate"}},
            "input": {"sample_rate_hz": SAMPLE_RATE, "channels": 1, "dtype": "float32",
                      "clip_sha256": sha(path)},
            "measurements": {"audio_duration_s": len(audio) / SAMPLE_RATE,
                             "runtime_s": None, "rtf": None, "peak_ram_bytes": None,
                             "peak_vram_bytes": None, "peak_vram_method": "not measured",
                             "model_footprint_bytes": 1084799335},
            "hypothesis": {"text": default_text, "words": []},
            "guard": gate_value, "guard_text": gate_text,
            "chunk_count": len(chunks), "chunk_texts": text_parts,
        }
        records.append(rec)
        raw = {"text": default_text, "words": [], "clip_set": clip["set"],
               "gate_no_speech": vad_flags.get(clip["clip_id"], False),
               "meta": {"runtime": "onnxruntime", "runtime_version": ort.__version__,
                        "model_artifact": rec["model"]["artifact_id"], "model_sha256": rec["model"]["sha256"],
                        "requested_device": args.device, "actual_device": actual,
                        "settings": rec["settings"], "chunk_count": len(chunks),
                        "chunking": "30-second non-overlapping windows; whitespace text concatenation",
                        "gate": gate_value, "gate_text": gate_text}}
        (out_dir / f"{clip['clip_id']}.json").write_text(json.dumps(raw, indent=2), encoding="utf-8")
        print(json.dumps({"clip_id": clip["clip_id"], "set": clip["set"], "text": default_text,
                          "guard_text": gate_text, "chunks": len(chunks)}), flush=True)
    with (args.output_root / "results.jsonl").open("a", encoding="utf-8") as stream:
        for rec in records:
            stream.write(json.dumps(rec, ensure_ascii=False) + "\n")
    print(json.dumps({"device": args.device, "clips": len(records),
                      "provider_lists": {"encoder": encoder.get_providers(),
                                         "decoder": decoder.get_providers(),
                                         "decoder_past": decoder_past.get_providers()}}), flush=True)


if __name__ == "__main__":
    main()
