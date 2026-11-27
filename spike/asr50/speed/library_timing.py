"""In-process timing for approved ASR/VAD/alignment libraries (WP22)."""
from __future__ import annotations

import argparse
import importlib.util
import importlib.metadata
import json
import os
import re
import statistics
import sys
import time
from pathlib import Path

import numpy as np
import psutil

BASE = Path(r"C:\scratch\asr50")
REPO = Path(r"C:\code\muteinous-spike50\spike\asr50")
V3 = BASE / "corpus_v3_frozen"
V2 = BASE / "corpus_v2_frozen"
MODEL = BASE / "models"
OUT = BASE / "WP22"
SHORT = [f"v3_clean_{i:03d}_0" for i in range(1, 9)]
MEDIUM = ["natural_18s_00", "natural_25s_00", "natural_18s_01", "natural_25s_01"]
LONG = ["natural_sentences_00", "natural_sentences_01"]

os.environ.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1",
                  HF_HUB_DISABLE_TELEMETRY="1")


def module_from(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def read_f32_wav(path: Path) -> np.ndarray:
    import struct
    data = path.read_bytes()
    if data[:4] != b"RIFF" or data[8:12] != b"WAVE":
        raise ValueError(f"not RIFF/WAVE: {path}")
    off, fmt, raw = 12, None, None
    while off + 8 <= len(data):
        tag = data[off:off + 4]
        size = struct.unpack_from("<I", data, off + 4)[0]
        body = off + 8
        if tag == b"fmt ":
            fmt = struct.unpack_from("<HHIIHH", data, body)
        elif tag == b"data":
            raw = data[body:body + size]
        off = body + size + (size & 1)
    if fmt != (3, 1, 16000, 64000, 4, 32) or raw is None:
        raise ValueError(f"expected mono float32 16-kHz WAV: {path}, fmt={fmt}")
    samples = np.frombuffer(raw, dtype="<f4").copy()
    if not np.isfinite(samples).all():
        raise ValueError(f"non-finite WAV samples: {path}")
    return samples


def selected():
    v3 = json.loads((V3 / "ground_truth_v3.json").read_text(encoding="utf-8"))
    v2 = json.loads((V2 / "ground_truth_v2.json").read_text(encoding="utf-8"))
    truth = {c["clip_id"]: c for c in v3["clips"] + v2["clips"]}
    result = []
    for group, ids in (("short", SHORT), ("medium", MEDIUM), ("long", LONG)):
        for cid in ids:
            c = truth[cid]
            root = V3 if cid.startswith("v3_") else V2
            result.append({"class": group, "clip_id": cid, "path": root / f"{cid}.wav",
                           "duration_s": float(c["duration_s"]),
                           "transcript": c["transcript"]})
    return result


def tokens(text):
    return re.findall(r"[a-z0-9]+(?:'[a-z0-9]+)*", text.casefold())


def accuracy_baseline(kind, device, beam, clip_id):
    version = "v3" if clip_id.startswith("v3_") else "v2"
    roots = {
        "ort-turbo": (BASE / "results_v3" / "ort-whisper-turbo" / "raw" / device,
                      BASE / "results_v2" / "ort-whisper-turbo" / device),
        "ort-small": (BASE / "results_v3" / "ort-whisper-small-en" / "raw" / device,
                      BASE / "results_v2" / "ort-whisper-small-en" / device),
        "parakeet": (BASE / "results_v3" / "sherpa-parakeet" / "raw" / "cpu",
                     BASE / "results_v2" / "sherpa-parakeet" / "cpu"),
        "moonshine": (BASE / "results_v3" / "moonshine-onnx" / "raw" / "cpu",
                      BASE / "results_v2" / "moonshine-onnx" / "cpu"),
    }
    if kind == "faster":
        roots = {
            "faster": (BASE / "results_v3" / "faster-whisper" / f"beam{beam}-vad0-raw",
                       BASE / "results_v2" / "faster-whisper" / f"beam{beam}-vad-off")
        }
    if kind not in roots:
        return None
    path = roots[kind][0 if version == "v3" else 1] / f"{clip_id}.json"
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        return data.get("text") or (data.get("hypothesis") or {}).get("text")
    except (OSError, json.JSONDecodeError):
        return None


class Backend:
    def __init__(self, kind, threads, beam, device):
        self.kind, self.threads, self.beam, self.device = kind, threads, beam, device
        start = time.perf_counter()
        if kind == "faster":
            from faster_whisper import WhisperModel
            model = MODEL / "whisper-small-en-faster-whisper-ct2"
            self.model = WhisperModel(str(model), device="cpu", compute_type="int8_float32",
                                      cpu_threads=threads)
        elif kind == "parakeet":
            import sherpa_onnx
            root = MODEL / "parakeet-tdt-0-6b-v2-sherpa-onnx-int8"
            self.model = sherpa_onnx.OfflineRecognizer.from_transducer(
                str(root / "encoder.int8.onnx"), str(root / "decoder.int8.onnx"),
                str(root / "joiner.int8.onnx"), str(root / "tokens.txt"),
                num_threads=threads, sample_rate=16000, feature_dim=80, dither=0.0,
                decoding_method="greedy_search", provider="cpu",
                model_type="nemo_transducer", debug=False)
        elif kind == "moonshine":
            import onnxruntime as ort
            from tokenizers import Tokenizer
            root = MODEL / "moonshine-base-onnx-int8"
            opts = ort.SessionOptions()
            opts.intra_op_num_threads, opts.inter_op_num_threads = threads, 1
            opts.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
            self.sessions = [ort.InferenceSession(str(root / "onnx" / name),
                                                  sess_options=opts,
                                                  providers=["CPUExecutionProvider"])
                             for name in ("encoder_model_int8.onnx",
                                          "decoder_model_merged_int8.onnx",
                                          "decoder_with_past_model_int8.onnx")]
            self.tokenizer = Tokenizer.from_file(str(root / "tokenizer.json"))
            self.moon_root = root
            self.moon_config = json.loads((root / "config.json").read_text(encoding="utf-8"))
            self.moon_gen = json.loads((root / "generation_config.json").read_text(encoding="utf-8"))
        elif kind == "ort-small":
            script = REPO / "runners" / "ort-whisper-small-en" / "run.py"
            self.small = module_from(script, "wp22_ort_small")
            root = MODEL / "whisper-small-en-onnx-fp16"
            self.gen = json.loads((root / "generation_config.json").read_text(encoding="utf-8"))
            from tokenizers import Tokenizer
            self.tokenizer = Tokenizer.from_file(str(root / "tokenizer.json"))
            names = ("encoder_model_fp16.onnx", "decoder_model_fp16.onnx",
                     "decoder_with_past_model_fp16.onnx")
            self.sessions = [self.small.create(root / "onnx" / name, device, 0, threads)
                             for name in names]
        elif kind == "ort-turbo":
            import onnxruntime as ort
            from tokenizers import Tokenizer
            from transformers import WhisperFeatureExtractor
            root = MODEL / "whisper-large-v3-turbo-onnx-merged-q4"
            self.extractor = WhisperFeatureExtractor.from_pretrained(str(root), local_files_only=True)
            self.tokenizer = Tokenizer.from_file(str(root / "tokenizer.json"))
            self.gen = json.loads((root / "generation_config.json").read_text(encoding="utf-8"))
            opts = ort.SessionOptions()
            opts.intra_op_num_threads, opts.inter_op_num_threads = threads, 1
            opts.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
            providers = (["CPUExecutionProvider"] if device == "cpu" else
                         [("DmlExecutionProvider", {"device_id": 0}), "CPUExecutionProvider"])
            self.sessions = [ort.InferenceSession(str(root / "onnx" / name),
                                                  sess_options=opts, providers=providers)
                             for name in ("encoder_model_q4.onnx",
                                          "decoder_model_merged_q4.onnx",
                                          "decoder_with_past_model_q4.onnx")]
            self.turbo = module_from(REPO / "runners" / "ort-whisper-turbo" / "runner_v3.py",
                                     "wp22_ort_turbo")
        elif kind == "vad":
            import onnxruntime as ort
            self.vad_module = module_from(REPO / "vad_gate" / "apply_gate.py", "wp22_vad")
            self.vad = object.__new__(self.vad_module.SileroRunner)
            opts = ort.SessionOptions()
            opts.inter_op_num_threads = 1
            opts.intra_op_num_threads = threads
            opts.enable_cpu_mem_arena = False
            opts.log_severity_level = 4
            self.vad.session = ort.InferenceSession(
                str(BASE / "WP18" / "silero" / "silero_vad_v6.onnx"),
                sess_options=opts, providers=["CPUExecutionProvider"])
        elif kind == "aligner":
            self.align_module = module_from(REPO / "runners" / "wav2vec2-aligner" / "aligner.py",
                                            "wp22_aligner")
            root = MODEL / "wav2vec2-base-960h-onnx"
            self.aligner = self.align_module.Aligner(root / "model.onnx", root / "vocab.json", threads)
        else:
            raise ValueError(f"unknown backend {kind}")
        self.model_load_s = time.perf_counter() - start

    def infer(self, audio, transcript):
        if self.kind == "faster":
            segments, _ = self.model.transcribe(audio, language="en", beam_size=self.beam,
                                                word_timestamps=True, vad_filter=False)
            return "".join(segment.text for segment in segments).strip()
        if self.kind == "parakeet":
            stream = self.model.create_stream()
            stream.accept_waveform(16000, audio)
            self.model.decode_stream(stream)
            return stream.result.text.strip()
        if self.kind == "moonshine":
            if len(audio) > 30 * 16000:
                chunks = [audio[i:i + 20 * 16000] for i in range(0, len(audio), 20 * 16000)]
            else:
                chunks = [audio]
            return " ".join(self.moonshine_window(chunk) for chunk in chunks).strip()
        if self.kind == "ort-small":
            text, _ = self.small.transcribe(audio, *self.sessions, self.tokenizer, self.gen, "on")
            return text
        if self.kind == "ort-turbo":
            chunks = [audio[i:i + 30 * 16000] for i in range(0, len(audio), 30 * 16000)] or [audio]
            return " ".join(self.turbo.decode_window(chunk, self.extractor,
                              self.sessions[0], self.sessions[1], self.sessions[2],
                              self.tokenizer, self.gen) for chunk in chunks).strip()
        if self.kind == "vad":
            segs = self.vad.segments(audio, threshold=.5, min_silence_duration_ms=200,
                                     speech_pad_ms=100)
            self.vad_module.mask(audio, segs)
            return json.dumps(segs)
        if self.kind == "aligner":
            return json.dumps(self.aligner.align(audio, transcript))
        raise AssertionError(self.kind)

    def moonshine_window(self, audio):
        root = self.moon_root
        cfg = self.moon_config
        gen = self.moon_gen
        heads = cfg["decoder_num_attention_heads"]
        dim = cfg["hidden_size"] // heads
        dec = self.sessions[1]
        past = {}
        for inp in dec.get_inputs():
            if inp.name.startswith("past_key_values."):
                past[inp.name] = np.zeros((1, heads, 0, dim), dtype=np.float32)
        hidden = self.sessions[0].run(None, {"input_values": audio[None, :]})[0]
        ids = [gen["decoder_start_token_id"]]
        usepast = False
        limit = min(512, max(1, int(len(audio) / 16000 * 6 + 8)))
        eos = gen["eos_token_id"]
        generated = []
        for _ in range(limit):
            feeds = {"input_ids": np.array([[ids[-1]]] if usepast else [ids], dtype=np.int64),
                     "encoder_hidden_states": hidden,
                     "use_cache_branch": np.array([usepast], dtype=np.bool_), **past}
            expected = {x.name for x in dec.get_inputs()}
            outputs = dec.run(None, {k: v for k, v in feeds.items() if k in expected})
            names = [o.name for o in dec.get_outputs()]
            vals = dict(zip(names, outputs))
            token = int(np.argmax(vals["logits"][0, -1]))
            if token == eos:
                break
            ids.append(token)
            generated.append(token)
            for name, value in vals.items():
                if name.startswith("present.") and ".decoder." in name:
                    past[name.replace("present.", "past_key_values.")] = value
                elif not usepast and name.startswith("present.") and ".encoder." in name:
                    past[name.replace("present.", "past_key_values.")] = value
            usepast = True
        return self.tokenizer.decode(generated).strip()


def runtime_versions(kind):
    names = {
        "faster": ("faster-whisper", "ctranslate2", "av"),
        "parakeet": ("sherpa-onnx",),
        "moonshine": ("onnxruntime", "tokenizers"),
        "ort-small": ("onnxruntime", "tokenizers"),
        "ort-turbo": ("onnxruntime", "tokenizers", "transformers"),
        "vad": ("onnxruntime", "soundfile"),
        "aligner": ("onnxruntime",),
    }[kind]
    result = {}
    for name in names:
        try:
            result[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            result[name] = "not installed"
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--kind", required=True,
                        choices=("faster", "parakeet", "moonshine", "ort-small",
                                 "ort-turbo", "vad", "aligner"))
    parser.add_argument("--threads", type=int, default=12)
    parser.add_argument("--beam", type=int, choices=(1, 5), default=5)
    parser.add_argument("--device", choices=("cpu", "dml"), default="cpu")
    parser.add_argument("--clips", required=True, choices=("all", "short", "medium", "long"))
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--clip-id", action="append")
    args = parser.parse_args()
    items = selected()
    if args.clip_id:
        wanted = set(args.clip_id)
        items = [x for x in items if x["clip_id"] in wanted]
    if args.clips != "all":
        items = [x for x in items if x["class"] == args.clips]
    backend = Backend(args.kind, args.threads, args.beam, args.device)
    process = psutil.Process()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("a", encoding="utf-8") as output:
        print(json.dumps({"event": "model_loaded", "kind": args.kind,
                          "threads": args.threads, "device": args.device,
                          "model_load_s": backend.model_load_s,
                          "runtime_versions": runtime_versions(args.kind),
                          "pid": os.getpid()}), file=output, flush=True)
        for item in items:
            try:
                audio = read_f32_wav(item["path"])
                t0 = time.perf_counter()
                warm_text = backend.infer(audio, item["transcript"])
                warm_s = time.perf_counter() - t0
                timed = []
                texts = []
                class_start = time.perf_counter()
                for repeat in range(args.repeats):
                    cpu_before = sum(process.cpu_times()[:2])
                    t0 = time.perf_counter()
                    text = backend.infer(audio, item["transcript"])
                    elapsed = time.perf_counter() - t0
                    cpu_after = sum(process.cpu_times()[:2])
                    timed.append(elapsed)
                    texts.append(text)
                    row = {"event": "observation", "kind": args.kind,
                           "config": f"{args.kind}-{args.device}-t{args.threads}-b{args.beam}",
                           "class": item["class"], "clip_id": item["clip_id"],
                           "repeat": repeat + 1, "status": "ok" if text.strip() else "empty_output",
                           "wall_seconds": elapsed, "audio_seconds": item["duration_s"],
                           "rtf": elapsed / item["duration_s"],
                           "speed_multiple": item["duration_s"] / elapsed,
                           "text": text, "transcript": item["transcript"],
                           "text_matches_reference": (
                               None if args.kind in ("vad", "aligner") else
                               tokens(text) == tokens(item["transcript"])),
                           "accuracy_baseline_text": accuracy_baseline(
                               args.kind, args.device, args.beam, item["clip_id"]),
                           "matches_accuracy_baseline_words": None,
                           "warmup_seconds": warm_s, "warmup_text": warm_text,
                           "model_load_s": backend.model_load_s,
                           "process_cpu_seconds": cpu_after - cpu_before,
                           "cores_used": (cpu_after - cpu_before) / elapsed if elapsed else None,
                           "peak_working_set_bytes": getattr(process.memory_info(), "peak_wset", None),
                           "pid": os.getpid(), "counter_sampling_during_timing": False,
                           "timer": "time.perf_counter"}
                    baseline = row["accuracy_baseline_text"]
                    row["matches_accuracy_baseline_words"] = (
                        tokens(text) == tokens(baseline) if baseline is not None else None)
                    output.write(json.dumps(row, ensure_ascii=False) + "\n")
                    output.flush()
                if time.perf_counter() - class_start > 600:
                    print(json.dumps({"event": "class_timeout_10m", "kind": args.kind,
                                      "class": item["class"], "clip_id": item["clip_id"]}),
                          file=output, flush=True)
            except Exception as exc:
                output.write(json.dumps({"event": "error", "kind": args.kind,
                                         "clip_id": item["clip_id"], "error": repr(exc)}) + "\n")
                output.flush()
                continue
            print(json.dumps({"clip_id": item["clip_id"], "warmup_s": warm_s,
                              "steady_median_s": statistics.median(timed)}), flush=True)


if __name__ == "__main__":
    main()
