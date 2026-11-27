"""Offline Whisper small.en ONNX runner; NumPy frontend, greedy no-timestamp decode."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import pathlib
import struct
import sys
import time

import numpy as np
import onnxruntime as ort
import psutil
from tokenizers import Tokenizer

MODEL = pathlib.Path(r"C:\scratch\asr50\models\whisper-small-en-onnx-fp16")
AUDIO = pathlib.Path(r"C:\scratch\asr50\corpus_v2_frozen")
MODEL_ID = MODEL.name


def read_wav(path: pathlib.Path) -> np.ndarray:
    data = path.read_bytes()
    off, fmt, raw = 12, None, None
    while off + 8 <= len(data):
        name, size = data[off:off+4], struct.unpack_from("<I", data, off+4)[0]
        body = off + 8
        if name == b"fmt ":
            fmt = struct.unpack_from("<HHIIHH", data, body)
        elif name == b"data":
            raw = data[body:body+size]
        off = body + size + (size & 1)
    if not fmt or raw is None or fmt != (3, 1, 16000, 64000, 4, 32):
        raise ValueError(f"expected mono 16k float32 WAV: {path}, {fmt}")
    return np.frombuffer(raw, dtype="<f4").copy()


def mel_filter() -> np.ndarray:
    """Slaney mel bank (80 x 201), built directly with NumPy."""
    sr, n_fft, n_mels = 16000, 400, 80
    def hz_to_mel(hz):
        f_sp = 200.0 / 3
        m = hz / f_sp
        logstep = np.log(6.4) / 27.0
        return np.where(hz >= 1000.0, 15 + np.log(np.maximum(hz, 1000)/1000.0) / logstep, m)
    def mel_to_hz(m):
        f_sp = 200.0 / 3
        return np.where(m >= 15, 1000*np.exp(np.log(6.4)/27*(m-15)), f_sp*m)
    mel_points = np.linspace(hz_to_mel(np.array(0.0)), hz_to_mel(np.array(sr/2)), n_mels+2)
    hz_points = mel_to_hz(mel_points)
    fft_freqs = np.linspace(0, sr/2, n_fft//2+1)
    ramps = hz_points[:, None] - fft_freqs[None, :]
    lower = -ramps[:-2] / (hz_points[1:-1]-hz_points[:-2])[:, None]
    upper = ramps[2:] / (hz_points[2:]-hz_points[1:-1])[:, None]
    weights = np.maximum(0, np.minimum(lower, upper))
    # Slaney area normalization.
    weights *= (2.0 / (hz_points[2:n_mels+2]-hz_points[:n_mels]))[:, None]
    return weights.astype(np.float32)


MEL = mel_filter()
WINDOW = np.hanning(400).astype(np.float32)


def features(audio: np.ndarray) -> np.ndarray:
    if len(audio) > 480000:
        raise ValueError("features() accepts one <=30-second chunk; caller must chunk explicitly")
    audio = np.pad(audio, (0, max(0, 480000-len(audio))))
    # Whisper STFT center padding, periodic reflect; omit final frame.
    padded = np.pad(audio, (200, 200), mode="reflect")
    frames = np.lib.stride_tricks.sliding_window_view(padded, 400)[::160][:3001]
    spec = np.fft.rfft(frames * WINDOW, n=400, axis=-1)
    power = (spec.real**2 + spec.imag**2).T[:, :3000].astype(np.float32)
    mel = MEL @ power
    log_spec = np.log10(np.maximum(mel, 1e-10))
    log_spec = np.maximum(log_spec, log_spec.max() - 8.0)
    return ((log_spec + 4.0) / 4.0)[None].astype(np.float32)


def create(path, provider, device_id, threads, profile=False, disable_cpu_fallback=False):
    opts = ort.SessionOptions()
    opts.enable_mem_pattern = False
    opts.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
    opts.intra_op_num_threads = threads
    opts.inter_op_num_threads = 1
    opts.enable_profiling = profile
    if disable_cpu_fallback:
        opts.add_session_config_entry("session.disable_cpu_ep_fallback", "1")
    providers = ([("DmlExecutionProvider", {"device_id": device_id})]
                 if provider == "dml" and disable_cpu_fallback else
                 [("DmlExecutionProvider", {"device_id": device_id}), "CPUExecutionProvider"]
                 if provider == "dml" else ["CPUExecutionProvider"])
    return ort.InferenceSession(str(path), sess_options=opts, providers=providers)


def transcribe_chunk(audio, enc, dec, past_sess, tokenizer, gen, max_tokens, loop_detection):
    feat = features(audio)
    hidden = enc.run(None, {"input_features": feat})[0]
    # This is the English-only checkpoint; forced_decoder_ids contains
    # [position 1, <|notimestamps|>] for the transcribe task.
    ids = [int(gen["decoder_start_token_id"]),
           int(gen["forced_decoder_ids"][0][1])]
    def inputs(session, token_ids, encoder_state=None, past=None):
        result = {}
        for inp in session.get_inputs():
            name = inp.name
            if name == "input_ids":
                result[name] = np.asarray([token_ids], dtype=np.int64)
            elif name == "encoder_hidden_states":
                result[name] = encoder_state
            elif name == "use_cache_branch":
                result[name] = np.asarray([past is not None], dtype=np.bool_)
            elif name.startswith("past_key_values."):
                if past and name in past:
                    result[name] = past[name]
                else:
                    result[name] = np.zeros((1, 12, 0, 64), dtype=np.float32)
        return result
    names = [o.name for o in dec.get_outputs()]
    out = dec.run(names, inputs(dec, ids, hidden))
    logits = out[names.index("logits")]
    cache = {o.name.replace("present.", "past_key_values.", 1): out[i]
             for i, o in enumerate(dec.get_outputs()) if o.name.startswith("present.")}
    if not cache:
        cache = {o.name: out[names.index(o.name)] for o in dec.get_outputs()
                 if o.name.startswith("past_key_values.")}
    eos = int(gen["eos_token_id"])
    generated, last = [], None
    repetition = 0
    stop_reason = "token_cap"
    for step in range(max_tokens):
        row = logits[0, -1].astype(np.float32, copy=True)
        row[list(gen.get("suppress_tokens", []))] = -np.inf
        if step == 0:
            row[list(gen.get("begin_suppress_tokens", []))] = -np.inf
        last = int(np.argmax(row))
        if last == eos:
            stop_reason = "eos"
            break
        generated.append(last)
        if loop_detection and len(generated) >= 8 and generated[-8:] == generated[-4:]*2:
            repetition += 1
            if repetition >= 2:
                stop_reason = "loop"
                break
        else:
            repetition = 0
        feed = {"input_ids": np.asarray([[last]], dtype=np.int64), **cache}
        outs = past_sess.run(None, feed)
        outnames = [o.name for o in past_sess.get_outputs()]
        logits = outs[outnames.index("logits")]
        newcache = {}
        for i, o in enumerate(past_sess.get_outputs()):
            if o.name.startswith("present."):
                newcache[o.name.replace("present.", "past_key_values.", 1)] = outs[i]
        newcache.update({name: value for name, value in cache.items()
                         if ".encoder." in name})
        cache = newcache
    return tokenizer.decode(generated, skip_special_tokens=True).strip(), feat, len(generated), stop_reason


def transcribe(audio, enc, dec, past_sess, tokenizer, gen, policy):
    chunk_size = 480000
    texts, ranges = [], []
    loop_detection = policy == "on"
    for start in range(0, len(audio), chunk_size):
        chunk = audio[start:start+chunk_size]
        duration_s = len(chunk) / 16000
        cap = min(444, 10 + int(np.ceil(duration_s * 10))) if policy == "on" else 444
        text, _, token_count, stop_reason = transcribe_chunk(
            chunk, enc, dec, past_sess, tokenizer, gen, cap, loop_detection)
        texts.append(text)
        ranges.append({"start_s": start / 16000,
                       "end_s": (start + len(chunk)) / 16000,
                       "token_cap": cap, "generated_tokens": token_count,
                       "stop_reason": stop_reason})
    return " ".join(t for t in texts if t).strip(), ranges


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--device", choices=["dml", "cpu"], required=True)
    p.add_argument("--audio-root", default=str(AUDIO))
    p.add_argument("--device-id", type=int, default=0)
    p.add_argument("--threads", type=int, default=12)
    p.add_argument("--limit", type=int, default=0)
    p.add_argument("--profile", action="store_true")
    p.add_argument("--max-tokens", type=int, default=160)
    p.add_argument("--passes", type=int, default=1)
    p.add_argument("--kind", default="warm")
    p.add_argument("--out", default=r"C:\scratch\asr50\results\ort-whisper-small-en")
    p.add_argument("--disable-cpu-ep-fallback", action="store_true")
    p.add_argument("--policy", choices=["on", "off"], default="on")
    p.add_argument("--long-and-nonspeech-only", action="store_true")
    p.add_argument("--clip-id", action="append")
    p.add_argument("--skip-gated", action="store_true")
    a = p.parse_args()
    audio_root = pathlib.Path(a.audio_root)
    files = sorted(audio_root.glob("*.wav"))
    gen = json.loads((MODEL/"generation_config.json").read_text(encoding="utf-8"))
    tok = Tokenizer.from_file(str(MODEL/"tokenizer.json"))
    gt_path = next((audio_root / name for name in
                    ("ground_truth_v2.json", "ground_truth_v3.json", "ground_truth.json")
                    if (audio_root / name).exists()), None)
    if gt_path is None:
        raise FileNotFoundError(f"no ground-truth JSON in {audio_root}")
    truth_data = json.loads(gt_path.read_text(encoding="utf-8"))
    truth = {c.get("clip_id", c.get("id")): c for c in truth_data["clips"]}
    manifest_path = audio_root / "manifest.json"
    manifest = {}
    if manifest_path.exists():
        for item in json.loads(manifest_path.read_text(encoding="utf-8"))["clips"]:
            key = item.get("clip_id") or item.get("input") or item.get("file") or item.get("output")
            if key:
                manifest[pathlib.Path(key).stem] = item
    if a.clip_id:
        wanted = set(a.clip_id)
        files = [f for f in files if f.stem in wanted]
    if a.long_and_nonspeech_only:
        files = [f for f in files if
                 truth[f.stem].get("category") in ("natural_long", "silence", "non_speech")
                 or truth[f.stem].get("duration_s", 0) > 30]
    if a.limit:
        files = files[:a.limit]
    outroot = pathlib.Path(a.out)
    rawdir = (outroot if a.policy == "on" else outroot/"policy-off")/a.device
    rawdir.mkdir(parents=True, exist_ok=True)
    model_bytes = sum(f.stat().st_size for f in MODEL.rglob("*") if f.is_file())
    model_sha = hashlib.sha256()
    for f in sorted(MODEL.rglob("*")):
        if f.is_file():
            model_sha.update(f.relative_to(MODEL).as_posix().encode())
            model_sha.update(bytes.fromhex(hashlib.sha256(f.read_bytes()).hexdigest()))
    model_hash = model_sha.hexdigest()
    t0 = time.perf_counter()
    sessions = [create(MODEL/"onnx"/name, a.device, a.device_id, a.threads,
                       a.profile, a.disable_cpu_ep_fallback)
                for name in ("encoder_model_fp16.onnx", "decoder_model_fp16.onnx",
                             "decoder_with_past_model_fp16.onnx")]
    load_s = time.perf_counter()-t0
    print(json.dumps({"process_id": os.getpid(), "sessions_created_s": load_s,
                      "providers": [s.get_providers() for s in sessions]}), flush=True)
    proc = psutil.Process()
    records = []
    for pass_i in range(a.passes):
        for wav in files:
            audio = read_wav(wav)
            t = time.perf_counter()
            gate_no_speech = bool(manifest.get(wav.stem, {}).get("gate_no_speech", False))
            if getattr(a, "skip_gated", False) and gate_no_speech:
                text, chunks = "", []
            else:
                text, chunks = transcribe(audio, *sessions, tok, gen, a.policy)
            elapsed = time.perf_counter()-t
            duration = len(audio)/16000
            clip_hash = hashlib.sha256(audio.astype("<f4", copy=False).tobytes()).hexdigest()
            cid = wav.stem
            kind = a.kind if pass_i == 0 else "warm"
            record = {
                "schema_version": 1, "candidate": "ort-whisper-small-en",
                "clip_id": cid, "category": truth[cid]["category"],
                "clip_set": truth[cid].get("set"),
                "condition": truth[cid].get("condition"),
                "gate_no_speech": gate_no_speech,
                "run": {"kind": kind, "index": pass_i, "process_id": os.getpid()},
                "hardware": {"cpu": "AMD Ryzen 9 9900X",
                    "gpu": "AMD Radeon RX 7900 XT" if a.device == "dml" else None,
                    "ram_bytes": 31600000000, "os": "Windows 11 Pro build 26300",
                    "driver": "32.0.32029.2010" if a.device == "dml" else None},
                "device": {"requested": a.device,
                    "actual": "DmlExecutionProvider+CPUExecutionProvider (partitioning unverified)"
                    if a.device == "dml" else "CPUExecutionProvider"},
                "runtime": {"name": "ONNX Runtime", "version": ort.__version__,
                    "package_version": ort.__version__, "installed_bytes": None},
                "model": {"artifact_id": MODEL_ID, "sha256": model_hash,
                    "bytes": model_bytes, "cache_bytes": 0},
                "settings": {"language": "en", "sample_rate_hz": 16000, "channels": 1,
                    "threads": a.threads, "decoding": {"greedy": True,
                    "policy": a.policy, "timestamps": False,
                    "chunking": "fixed non-overlapping 30-second chunks",
                    "chunks": chunks,
                    "token_caps": [x["token_cap"] for x in chunks],
                    "loop_detection": "repeated 4-token sequence twice" if a.policy == "on" else "disabled"}},
                "input": {"sample_rate_hz": 16000, "channels": 1, "dtype": "float32",
                    "clip_sha256": clip_hash},
                "measurements": {"audio_duration_s": duration, "runtime_s": elapsed,
                    "rtf": elapsed/duration, "peak_ram_bytes": proc.memory_info().peak_wset,
                    "peak_vram_bytes": None, "peak_vram_method": "not sampled",
                    "model_footprint_bytes": model_bytes, "session_creation_s": load_s},
                "hypothesis": {"text": text, "words": []}, "metrics": {},
            }
            records.append(record)
            raw = {"text": text, "words": [], "clip_set": truth[cid].get("set"),
                   "condition": truth[cid].get("condition"),
                   "gate_no_speech": gate_no_speech, "meta": {
                "runtime": "onnxruntime", "runtime_version": ort.__version__,
                "model_artifact": MODEL_ID, "model_sha256": model_hash,
                "requested_device": a.device, "actual_device": record["device"]["actual"],
                "clip_set": truth[cid].get("set"),
                "condition": truth[cid].get("condition"),
                "gate_no_speech": gate_no_speech,
                "settings": record["settings"], "thread_count": a.threads,
                "wall_seconds": elapsed, "peak_working_set_bytes": proc.memory_info().peak_wset,
                "peak_dedicated_gpu_bytes": None, "run_kind": kind,
                "run_index": pass_i, "pid": os.getpid()}}
            (rawdir/f"{cid}_{kind}_{pass_i}.json").write_text(
                json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")
            if a.policy == "on" and kind in ("v2", "vadmasked", "v3"):
                (rawdir/f"{cid}.json").write_text(
                    json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")
            print(json.dumps({"clip": cid, "seconds": elapsed, "audio_seconds": duration,
                              "text": text, "chunks": len(chunks)}), flush=True)
    with (outroot/"results.jsonl").open("a", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec, ensure_ascii=False)+"\n")
    if a.profile:
        for label, sess in zip(("encoder", "decoder", "decoder_past"), sessions):
            print(json.dumps({"profile": label, "path": sess.end_profiling()}), flush=True)


if __name__ == "__main__":
    main()
