"""Runtime-neutral wrapper around the bundled Silero VAD ONNX model."""
import argparse
import json
from pathlib import Path
import hashlib

import numpy as np
import onnxruntime as ort
import soundfile as sf

SR = 16000


class SileroRunner:
    def __init__(self, model_path):
        opts = ort.SessionOptions()
        opts.inter_op_num_threads = opts.intra_op_num_threads = 1
        opts.enable_cpu_mem_arena = False
        opts.log_severity_level = 4
        self.session = ort.InferenceSession(str(model_path), sess_options=opts,
                                            providers=["CPUExecutionProvider"])

    def probabilities(self, audio):
        audio = np.asarray(audio, dtype=np.float32)
        # faster-whisper pads a full window when already aligned as well.
        pad = 512 - len(audio) % 512
        frames = np.pad(audio, (0, pad)).reshape(-1, 512)
        ctx = np.roll(frames[:, -64:].copy(), 1, axis=0)
        ctx[0] = 0
        inputs = np.concatenate((ctx, frames), axis=1)
        h = np.zeros((1, 1, 128), np.float32)
        c = np.zeros_like(h)
        result = []
        for i in range(0, len(inputs), 10000):
            out, h, c = self.session.run(None, {
                "input": inputs[i:i+10000], "h": h, "c": c
            })
            result.append(out)
        return np.concatenate(result).reshape(-1)

    def segments(self, audio, threshold=.5, neg_threshold=None,
                 min_speech_duration_ms=0, min_silence_duration_ms=2000,
                 speech_pad_ms=400):
        # Timestamp state machine mirrors the public faster-whisper algorithm,
        # implemented here without importing faster-whisper.
        n = len(audio); win = 512
        minsp = SR * min_speech_duration_ms / 1000
        pad = SR * speech_pad_ms / 1000
        maxsp = float("inf")
        minsil = SR * min_silence_duration_ms / 1000
        if neg_threshold is None: neg_threshold = max(threshold - .15, .01)
        probs = self.probabilities(audio)
        active = False; temp = 0; start = 0; out = []
        for i, p in enumerate(probs):
            pos = win * i
            if p >= threshold and temp:
                temp = 0
            if p >= threshold and not active:
                active = True; start = pos; continue
            if p < neg_threshold and active:
                if not temp: temp = pos
                if pos - temp < minsil: continue
                end = temp
                if end - start > minsp: out.append([start, end])
                active = False; temp = 0
        if active and n - start > minsp: out.append([start, n])
        for i, s in enumerate(out):
            if i == 0: s[0] = max(0, int(s[0] - pad))
            if i < len(out)-1:
                silence = out[i+1][0] - s[1]
                if silence < 2*pad:
                    s[1] += int(silence // 2)
                    out[i+1][0] = max(0, int(out[i+1][0] - silence // 2))
                else:
                    s[1] = min(n, int(s[1] + pad))
                    out[i+1][0] = max(0, int(out[i+1][0] - pad))
            else: s[1] = min(n, int(s[1] + pad))
        return [{"start": int(a), "end": int(b)} for a,b in out]


def mask(audio, segments):
    result = np.zeros_like(audio, dtype=np.float32)
    for s in segments: result[s["start"]:s["end"]] = audio[s["start"]:s["end"]]
    return result


def main():
    p = argparse.ArgumentParser()
    p.add_argument("input_dir", type=Path); p.add_argument("output_dir", type=Path)
    p.add_argument("--model", required=True, type=Path)
    p.add_argument("--threshold", type=float, default=.5)
    p.add_argument("--min-silence-duration-ms", type=int, default=200)
    p.add_argument("--speech-pad-ms", type=int, default=100)
    a = p.parse_args()
    a.output_dir.mkdir(parents=True, exist_ok=True)
    vad = SileroRunner(a.model); manifest = []
    for path in sorted(a.input_dir.glob("*.wav")):
        audio, sr = sf.read(path, dtype="float32", always_2d=False)
        if sr != SR or audio.ndim != 1: raise ValueError(f"{path}: expected 16kHz mono")
        segs = vad.segments(audio, threshold=a.threshold,
                            min_silence_duration_ms=a.min_silence_duration_ms,
                            speech_pad_ms=a.speech_pad_ms)
        masked = mask(audio, segs)
        dest = a.output_dir / path.name
        sf.write(dest, masked, SR, subtype="FLOAT")
        manifest.append({"input": path.name, "output": dest.name,
                         "gate_no_speech": not bool(segs), "segments": segs,
                         "samples": len(audio),
                         "sha256": hashlib.sha256(dest.read_bytes()).hexdigest()})
    (a.output_dir / "manifest.json").write_text(json.dumps(
        {"settings": vars(a) | {"input_dir": str(a.input_dir), "output_dir": str(a.output_dir),
                                "model": str(a.model)}, "clips": manifest},
        default=str, indent=2), encoding="utf-8")

if __name__ == "__main__": main()
