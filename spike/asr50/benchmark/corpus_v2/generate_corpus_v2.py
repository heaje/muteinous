#!/usr/bin/env python
"""Generate deterministic constructed-timing and natural-transcript SAPI corpus v2."""
from __future__ import annotations

import hashlib
import json
import argparse
import struct
import subprocess
import tempfile
import wave
from pathlib import Path

import numpy as np
from scipy.signal import resample_poly
import soundfile as sf

RATE = 22050
OUT_RATE = 16000
VOICES = ("Microsoft Zira Desktop", "Microsoft David Desktop")
WORDS = ("banana", "cobalt", "harbor", "cobol", "arbor", "bandana")
SENTENCES = [
    "The small boat moved slowly toward the harbor before sunrise.",
    "A ripe banana sat beside a blue cup on the kitchen table.",
    "Cobalt paint covered the old wooden door near the garden.",
    "The traveler carried a map and a bottle of water.",
    "Several birds rested quietly along the river bank.",
    "A bright lantern guided the hikers through the narrow path.",
    "The baker placed warm bread inside a paper bag.",
    "Rain tapped gently against the window throughout the evening.",
    "The train arrived early at the station outside town.",
    "A careful gardener trimmed the roses after lunch.",
    "The museum displayed a small collection of ancient coins.",
    "Fresh coffee filled the room with a pleasant aroma.",
    "The children watched clouds drift across the open sky.",
    "A silver bicycle leaned against the brick wall.",
    "The quiet library closed its doors at six.",
    "A yellow umbrella rested beside the front entrance.",
    "The mechanic checked each wheel before the long drive.",
    "Blue flowers grew along the path behind the house.",
    "The pianist practiced a gentle melody in the afternoon.",
    "A wooden sign pointed toward the northern trail.",
    "The cook added pepper and herbs to the soup.",
    "A distant lighthouse flashed above the dark water.",
    "The package contained a notebook and two pencils.",
    "Soft music played while the guests waited.",
    "The farmer gathered apples from the oldest tree.",
    "A paper airplane crossed the classroom.",
    "The morning breeze moved the curtains.",
    "The old harbor looked peaceful after the storm.",
    "She placed a banana in the basket for later.",
    "They studied cobalt samples in the science room.",
]

PS = r"""
param([string]$Text, [string]$WavPath, [string]$VoiceName)
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Speech
$s = New-Object System.Speech.Synthesis.SpeechSynthesizer
$s.SelectVoice($VoiceName)
$s.SetOutputToWaveFile($WavPath)
$s.Speak($Text)
$s.SetOutputToNull()
$s.Dispose()
"""


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def cache_key(text: str, voice: str) -> str:
    return hashlib.sha256((voice + "\0" + text).encode("utf-8")).hexdigest()


def synth(text: str, voice: str, folder: Path, helper: Path, name: str,
          cache: Path, cache_manifest: dict, diagnostics: dict) -> tuple[np.ndarray, int]:
    key = cache_key(text, voice)
    if key not in cache_manifest["items"]:
        temp_wav = folder / f"{name}.wav"
        subprocess.run(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
                        "-File", str(helper), "-Text", text, "-WavPath", str(temp_wav),
                        "-VoiceName", voice], check=True, capture_output=True, text=True)
        digest = sha(temp_wav)
        target = cache / f"{digest}.wav"
        if not target.exists():
            target.write_bytes(temp_wav.read_bytes())
        cache_manifest["items"][key] = {"voice": voice, "text": text, "wav": target.name,
                                        "sha256": digest}
        (cache / "manifest.json").write_text(
            json.dumps(cache_manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        temp_wav.unlink()
    entry = cache_manifest["items"][key]
    p = cache / entry["wav"]
    if sha(p) != entry["sha256"]:
        raise ValueError(f"SAPI cache hash mismatch: {p}")
    diagnostics[key] = {"cache_wav_sha256": entry["sha256"],
                        "raw_wav_sha256": sha(p),
                        "riff_chunks": riff_chunks(p)}
    # Read the cache artifact directly; do not synthesize or rewrite its header.
    p = cache / entry["wav"]
    with wave.open(str(p), "rb") as w:
        channels, width, rate = w.getnchannels(), w.getsampwidth(), w.getframerate()
        if width != 2:
            raise ValueError(f"unexpected PCM width {width}")
        pcm16 = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2")
        diagnostics[key].update({"channels": channels, "sample_width": width,
                                 "sample_rate_hz": rate, "frames": len(pcm16),
                                 "pcm16_sha256": hashlib.sha256(pcm16.tobytes()).hexdigest()})
        a = pcm16.astype(np.float32) / 32768
    if channels > 1:
        a = a.reshape(-1, channels).mean(axis=1)
    return a, rate


def riff_chunks(path: Path) -> list[dict]:
    data = path.read_bytes()
    chunks, offset = [], 12
    while offset + 8 <= len(data):
        name = data[offset:offset+4].decode("ascii", "replace")
        size = int.from_bytes(data[offset+4:offset+8], "little")
        chunks.append({"id": name, "size": size, "header_offset": offset})
        offset += 8 + size + (size & 1)
    return chunks


def array_sha(a: np.ndarray) -> str:
    return hashlib.sha256(np.ascontiguousarray(a).tobytes()).hexdigest()


def trim(a: np.ndarray) -> np.ndarray:
    active = np.flatnonzero(np.abs(a) >= 1e-4)
    if not len(active):
        raise ValueError("SAPI output silent at trim threshold")
    return a[active[0]:active[-1] + 1].copy()


def noise(n: int, kind: str, seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    x = rng.normal(size=n).astype(np.float32)
    if kind == "pink":
        # Deterministic 1/f-like filter with normalized output.
        x = np.convolve(x, np.array([1, .5, .25, .125], np.float32), mode="same")
    x /= max(float(np.sqrt(np.mean(x*x))), 1e-12)
    return x


def effects(n: int, seed: int) -> np.ndarray:
    t = np.arange(n) / RATE
    fx = .035*np.sin(2*np.pi*220*t) + .025*np.sin(2*np.pi*277.18*t) + .018*np.sin(2*np.pi*329.63*t)
    rng = np.random.default_rng(seed)
    for at, dur, gain in ((.15, .22, .18), (.65, .18, .12)):
        start, count = int(at*RATE), min(int(dur*RATE), n-int(at*RATE))
        if count > 0:
            fx[start:start+count] += gain*np.exp(-np.linspace(0, 6, count))*rng.normal(size=count)
    return fx.astype(np.float32)


def word_at_16k(raw: np.ndarray, sr: int) -> np.ndarray:
    audio = raw.astype(np.float64)
    if sr != OUT_RATE:
        audio = resample_poly(audio, OUT_RATE, sr)
    return trim(audio.astype(np.float32))


def make_word_clip(word: str, category: str, seed: int, speech: np.ndarray,
                   cursor: int, gap_ms: int) -> tuple[np.ndarray, dict, dict]:
    start, end = cursor, cursor + len(speech)
    gap = int(gap_ms * OUT_RATE / 1000)
    word_info = {"text": word, "start_s": start/OUT_RATE, "end_s": end/OUT_RATE,
                 "start_sample": start, "end_sample": end,
                 "is_target": word in {"banana", "cobalt", "harbor"}}
    params = {"gap_ms_after": gap_ms, "gap_samples_after": gap,
              "trim_threshold_abs": 1e-4, "trimmed_samples_16k": len(speech)}
    return speech, word_info, params


def write_clip(path: Path, audio: np.ndarray, rate: int = RATE, subtype: str = "PCM_16") -> str:
    sf.write(str(path), audio.astype(np.float32), rate, subtype=subtype)
    # libsndfile's optional PEAK chunk includes a wall-clock timestamp. Zero
    # that metadata field; it is not audio content and otherwise poisons hashes.
    data = bytearray(path.read_bytes())
    offset = 12
    while offset + 8 <= len(data):
        chunk_id = data[offset:offset+4]
        chunk_size = struct.unpack_from("<I", data, offset+4)[0]
        if chunk_id == b"PEAK" and chunk_size >= 8:
            struct.pack_into("<I", data, offset+12, 0)
        offset += 8 + chunk_size + (chunk_size & 1)
    path.write_bytes(data)
    return sha(path)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-root", type=Path, default=Path(r"C:\scratch\asr50\WP15"))
    parser.add_argument("--sapi-cache", type=Path, default=Path(r"C:\scratch\asr50\WP15\sapi_cache"))
    args = parser.parse_args()
    root = args.output_root.resolve()
    cache = args.sapi_cache.resolve()
    cache.mkdir(parents=True, exist_ok=True)
    cache_manifest_path = cache / "manifest.json"
    cache_manifest = json.loads(cache_manifest_path.read_text(encoding="utf-8")) if cache_manifest_path.exists() else {
        "schema_version": 1, "description": "Content-addressed original System.Speech SAPI WAV inputs",
        "items": {}}
    sapi_diagnostics = {}
    diagnostics = {"schema_version": 1, "layers": {}, "sapi_inputs": {}}
    out = root / "audio_v2"
    out16 = root / "audio16k_v2"
    speech_out = root / "speech_only16k"
    out.mkdir(parents=True, exist_ok=True)
    out16.mkdir(parents=True, exist_ok=True)
    speech_out.mkdir(parents=True, exist_ok=True)
    seed0 = 15015
    clips = []
    categories = ["clean", "noise_white_10", "noise_white_0", "noise_white_-5",
                  "noise_pink_10", "noise_pink_0", "noise_pink_-5", "effects",
                  "quiet_-30", "quiet_-40", "rapid", "repeated", "similar",
                  "edge_start", "edge_end"]
    with tempfile.TemporaryDirectory(prefix="wp15-") as td:
        folder = Path(td)
        helper = folder / "sapi.ps1"
        helper.write_text(PS, encoding="utf-8")
        for vi, voice in enumerate(VOICES):
            for ci, cat in enumerate(categories):
                words = ["banana", "cobalt", "harbor"] if cat not in ("repeated", "similar") else (
                    ["banana", "banana", "cobalt", "cobalt", "harbor", "harbor"] if cat == "repeated"
                    else ["cobalt", "cobol", "harbor", "arbor", "banana", "bandana"])
                if cat in ("edge_start", "edge_end"):
                    words = ["banana" if cat == "edge_start" else "harbor"]
                chunks, spans, params = [], [], []
                cursor = 0
                for wi, word in enumerate(words):
                    seed = seed0 + vi*10000 + ci*100 + wi
                    raw, sr = synth(word, voice, folder, helper, f"w{vi}_{ci}_{wi}",
                                    cache, cache_manifest, sapi_diagnostics)
                    speech = word_at_16k(raw, sr)
                    diagnostics["layers"][f"{cat}_{vi}:{wi}:trimmed_16k"] = {
                        "sha256": array_sha(speech), "samples": len(speech)}
                    gap_ms = 35 if cat == "rapid" else int(40 + seed % 261)
                    audio, span, par = make_word_clip(word, cat, seed, speech, cursor, gap_ms)
                    chunks.append(audio)
                    spans.append(span); params.append(par)
                    cursor += len(audio)
                    if wi + 1 < len(words):
                        gap = np.zeros(par["gap_samples_after"], np.float32)
                        assert np.all(gap == 0), "constructed gap is not digital zero"
                        chunks.append(gap)
                        cursor += len(gap)
                speech_only = np.concatenate(chunks)
                for left, right in zip(spans, spans[1:]):
                    assert np.all(speech_only[left["end_sample"]:right["start_sample"]] == 0), \
                    f"nonzero constructed gap {cat}"
                additive = np.zeros_like(speech_only)
                for span, par in zip(spans, params):
                    lo, hi = span["start_sample"], span["end_sample"]
                    if cat.startswith("noise_"):
                        _, color, snr = cat.split("_")
                        sig = speech_only[lo:hi]
                        additive[lo:hi] += noise(len(sig), color, seed0 + vi*10000 + ci*100 + spans.index(span)) * float(np.sqrt(np.mean(sig**2))) / (10 ** (int(snr)/20))
                    elif cat == "effects":
                        additive[lo:hi] += effects(hi-lo, seed0 + vi*10000 + ci*100 + spans.index(span))
                if cat.startswith("quiet_"):
                    desired = 10 ** (int(cat.split("_")[1]) / 20)
                    speech_rms = float(np.sqrt(np.mean(speech_only**2)))
                    speech_only *= desired / max(speech_rms, 1e-12)
                mixed = speech_only + additive
                diagnostics["layers"][f"{cat}_{vi}:speech_only"] = {
                    "sha256": array_sha(speech_only), "samples": len(speech_only)}
                diagnostics["layers"][f"{cat}_{vi}:additive"] = {
                    "sha256": array_sha(additive), "samples": len(additive)}
                diagnostics["layers"][f"{cat}_{vi}:mix"] = {
                    "sha256": array_sha(mixed), "samples": len(mixed)}
                assert len(mixed) == len(speech_only)
                assert np.array_equal(mixed, speech_only + additive), "mix shifted relative to speech-only"
                # First/last target boundary cases have no added lead/tail silence.
                cid = f"timing_{cat}_{vi:02d}"
                src = out / f"{cid}.wav"
                src_hash = write_clip(src, mixed, OUT_RATE, "FLOAT")
                speech_path = speech_out / f"{cid}.wav"
                write_clip(speech_path, speech_only, OUT_RATE, "FLOAT")
                dest = out16 / f"{cid}.wav"
                write_clip(dest, mixed, OUT_RATE, "FLOAT")
                info = sf.info(str(dest))
                diagnostics["layers"][f"{cat}_{vi}:float_wav"] = {
                    "sha256": sha(dest), "samplerate": info.samplerate, "channels": info.channels,
                    "frames": info.frames, "format": info.format, "subtype": info.subtype,
                    "riff_chunks": riff_chunks(dest)}
                clips.append({"clip_id": cid, "set": "timing", "category": cat,
                    "transcript": " ".join(words), "words": spans, "duration_s": len(mixed)/OUT_RATE,
                    "sample_rate_hz": 16000, "channels": 1, "voice": voice, "seed": seed0+vi*10000+ci*100,
                    "boundary_source": "constructed", "wav": dest.name, "wav_sha256": sha(dest),
                    "speech_only_wav": speech_path.name, "speech_only_sha256": sha(speech_path),
                    "source_wav_sha256": src_hash, "mix_parameters": params,
                    "mix_alignment": "mixed = speech_only + additive, sample-aligned"})
                if vi == 0 and cat == "clean":
                    print("3-word construction debug:", json.dumps(
                        [{"text": w["text"], "start_sample": w["start_sample"], "end_sample": w["end_sample"]}
                         for w in spans]))
            # Thirty sentences, one SAPI call per voice; transcript-only timing.
            natural_text = " ".join(SENTENCES)
            natural, sr = synth(natural_text, voice, folder, helper, f"natural{vi}",
                                cache, cache_manifest, sapi_diagnostics)
            if sr != RATE: raise ValueError(f"SAPI rate {sr} != {RATE}")
            cid = f"natural_sentences_{vi:02d}"
            src = out / f"{cid}.wav"; source_hash = write_clip(src, natural)
            y = resample_poly(natural.astype(np.float64), OUT_RATE, RATE).astype(np.float32)
            dest = out16 / f"{cid}.wav"; write_clip(dest, y, 16000, "FLOAT")
            diagnostics["layers"][f"{cid}:resampled_float32"] = {
                "sha256": array_sha(y), "samples": len(y)}
            clips.append({"clip_id": cid, "set": "natural", "category": "natural_sentences",
                "transcript": natural_text, "words": [], "duration_s": len(y)/16000, "sample_rate_hz": 16000,
                "channels": 1, "voice": voice, "seed": seed0+vi*10000+9000,
                 "boundary_source": "none", "wav": dest.name, "wav_sha256": sha(dest),
                 "source_wav_sha256": source_hash, "sentence_count": len(SENTENCES)})
            for target_seconds, sentence_count in ((18, 5), (25, 7), (35, 10), (42, 12)):
                text = " ".join(SENTENCES[(i*7) % len(SENTENCES)] for i in range(sentence_count))
                speech, sr = synth(text, voice, folder, helper, f"long{vi}_{target_seconds}",
                                   cache, cache_manifest, sapi_diagnostics)
                long_y = resample_poly(speech.astype(np.float64), OUT_RATE, sr).astype(np.float32)
                long_id = f"natural_{target_seconds}s_{vi:02d}"
                long_path = out16 / f"{long_id}.wav"
                write_clip(long_path, long_y, OUT_RATE, "FLOAT")
                diagnostics["layers"][f"{long_id}:resampled_float32"] = {
                    "sha256": array_sha(long_y), "samples": len(long_y)}
                clips.append({"clip_id": long_id, "set": "natural", "category": "natural_long",
                    "transcript": text, "words": [], "duration_s": len(long_y)/OUT_RATE,
                    "sample_rate_hz": OUT_RATE, "channels": 1, "voice": voice,
                    "seed": seed0+vi*10000+target_seconds, "boundary_source": "none",
                    "wav": long_path.name, "wav_sha256": sha(long_path),
                    "sentence_count": sentence_count, "requested_duration_s": target_seconds})
        for i, seconds in enumerate((2, 5, 10, 20, 30)):
            n = seconds*OUT_RATE
            arrays = [np.zeros(n, np.float32), noise(n,"white",seed0+i), noise(n,"pink",seed0+i+50), effects(n,seed0+i+100)]
            for kind, audio in zip(("silence","white_noise","pink_noise","effects"), arrays):
                cid = f"nonspeech_{kind}_{seconds:02d}s"
                dest = out16 / f"{cid}.wav"; write_clip(dest, audio, OUT_RATE, "FLOAT")
                clips.append({"clip_id":cid,"set":"natural","category":"silence" if kind=="silence" else "non_speech",
                    "transcript":"","words":[],"duration_s":seconds,"sample_rate_hz":16000,"channels":1,
                    "voice":None,"seed":seed0+i,"boundary_source":"none","wav":dest.name,"wav_sha256":sha(dest),
                    "mix_parameters":{"kind":kind}})
    manifest = {"schema_version": 2, "seed": seed0, "target_words": ["banana","cobalt","harbor"],
                "voices": list(VOICES), "sample_rate_hz":16000,"channels":1,"dtype":"float32","clips":clips}
    (out16/"ground_truth_v2.json").write_text(json.dumps(manifest,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    diagnostics["sapi_inputs"] = sapi_diagnostics
    (root/"diagnostics_v2.json").write_text(json.dumps(diagnostics,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    print(json.dumps({"count":len(clips),"duration_s":sum(c["duration_s"] for c in clips),
                     "manifest":str(out16/"ground_truth_v2.json"),
                     "sha256":{c["wav"]:c["wav_sha256"] for c in clips}},indent=2))

if __name__ == "__main__":
    main()
