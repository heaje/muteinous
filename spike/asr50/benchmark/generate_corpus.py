#!/usr/bin/env python
"""Generate deterministic SAPI speech/noise benchmark audio and ground truth."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import tempfile
import wave

import numpy as np

RATE = 22050
TARGETS = {"banana", "cobalt", "harbor"}
UTTERANCES = [
    ("clean_001", "clean_speech", "The banana rests beside cobalt near the harbor."),
    ("noise_10db", "speech_noise", "Banana cobalt harbor.", {"snr_db": 10}),
    ("noise_0db", "speech_noise", "Banana cobalt harbor.", {"snr_db": 0}),
    ("noise_m5db", "speech_noise", "Banana cobalt harbor.", {"snr_db": -5}),
    ("effects_001", "speech_music_effects", "The harbor has cobalt and banana.", {}),
    ("quiet_m30", "quiet_speech", "A banana by the harbor.", {"level_dbfs": -30}),
    ("quiet_m40", "quiet_speech", "Cobalt is near the banana.", {"level_dbfs": -40}),
    ("silence_001", "silence", "", {}),
    ("nonspeech_001", "non_speech", "", {}),
    ("rapid_001", "rapid_speech", "Banana cobalt harbor banana cobalt harbor.", {}),
    ("repeated_001", "repeated_targets", "Banana banana cobalt cobalt harbor harbor.", {}),
    ("similar_001", "similar_sounding", "Cobalt cobol harbor arbor.", {}),
    ("edge_start", "target_near_start", "Banana starts this utterance."),
    ("edge_end", "target_near_end", "This utterance ends with harbor."),
]

POWERSHELL_HELPER = r"""
param([string]$Text, [string]$WavPath, [string]$VoiceName, [string]$EventsPath)
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Speech
$s = New-Object System.Speech.Synthesis.SpeechSynthesizer
if ($VoiceName) { $s.SelectVoice($VoiceName) }
$events = New-Object 'System.Collections.Generic.List[object]'
$handler = [System.EventHandler[System.Speech.Synthesis.SpeakProgressEventArgs]]{
  param($sender, $e)
  $events.Add([pscustomobject]@{
    character_position = [int]$e.CharacterPosition
    character_count = [int]$e.CharacterCount
    audio_position_ticks = [long]$e.AudioPosition.Ticks
    audio_position_s = [double]$e.AudioPosition.TotalSeconds
  })
}
$s.add_SpeakProgress($handler)
$s.SetOutputToWaveFile($WavPath)
if ($Text.Length -gt 0) { $s.Speak($Text) }
$s.SetOutputToNull()
$s.remove_SpeakProgress($handler)
$events | ConvertTo-Json -Depth 4 | Set-Content -Encoding UTF8 $EventsPath
$s.Dispose()
"""


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def word_spans(text: str) -> list[tuple[str, int, int]]:
    import re
    return [(m.group(), m.start(), m.end()) for m in re.finditer(r"[A-Za-z0-9']+", text)]


def synthesize(text: str, out: Path, voice: str, helper: Path) -> list[dict]:
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
        events_path = Path(f.name)
    try:
        subprocess.run(
            ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
             str(helper), "-Text", text, "-WavPath", str(out), "-VoiceName", voice,
             "-EventsPath", str(events_path)],
            check=True, capture_output=True, text=True,
        )
        raw = events_path.read_text(encoding="utf-8-sig").strip()
        value = json.loads(raw) if raw else []
        return value if isinstance(value, list) else [value]
    finally:
        events_path.unlink(missing_ok=True)


def read_wav(path: Path) -> tuple[np.ndarray, int]:
    with wave.open(str(path), "rb") as w:
        channels, width, rate, nframes = w.getnchannels(), w.getsampwidth(), w.getframerate(), w.getnframes()
        if width != 2:
            raise ValueError(f"Expected SAPI 16-bit PCM; got sample width {width}")
        audio = np.frombuffer(w.readframes(nframes), dtype="<i2").astype(np.float32) / 32768
    if channels > 1:
        audio = audio.reshape(-1, channels).mean(axis=1)
    return audio, rate


def write_wav(path: Path, audio: np.ndarray, rate: int = RATE) -> None:
    pcm = np.clip(audio, -1, 1)
    data = np.rint(pcm * 32767).astype("<i2").tobytes()
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(data)


def rms_envelope(audio: np.ndarray, rate: int, frame_ms: float = 20) -> tuple[np.ndarray, np.ndarray]:
    size = max(1, int(rate * frame_ms / 1000))
    count = int(math.ceil(len(audio) / size))
    padded = np.pad(audio, (0, count * size - len(audio)))
    rms = np.sqrt(np.mean(padded.reshape(count, size) ** 2, axis=1))
    centers = (np.arange(count) * size + size / 2) / rate
    return centers, rms


def synth_effects(n: int, rate: int, seed: int, music: bool = False) -> np.ndarray:
    rng = np.random.default_rng(seed)
    t = np.arange(n, dtype=np.float64) / rate
    if music:
        return (0.035 * np.sin(2 * np.pi * 220 * t) +
                0.025 * np.sin(2 * np.pi * 277.18 * t) +
                0.018 * np.sin(2 * np.pi * 329.63 * t)).astype(np.float32)
    out = np.zeros(n, dtype=np.float32)
    # Short deterministic broadband bursts with a decaying, low-frequency body.
    for start_s, duration, amplitude in ((0.25, .42, .38), (1.1, .2, .22), (2.0, .5, .32)):
        start, length = int(start_s * rate), min(int(duration * rate), max(0, n - int(start_s * rate)))
        if length <= 0:
            continue
        env = np.exp(-np.linspace(0, 6, length)).astype(np.float32)
        noise = rng.normal(0, 1, length).astype(np.float32)
        out[start:start + length] += amplitude * env * noise
    return out


def mix_for(category: str, params: dict, speech: np.ndarray, rate: int, seed: int) -> tuple[np.ndarray, dict]:
    rng = np.random.default_rng(seed)
    metadata = dict(params)
    audio = speech.astype(np.float32, copy=True)
    if category == "silence":
        return np.zeros(max(rate, len(audio)), dtype=np.float32), metadata
    if category == "non_speech":
        n = int(3.0 * rate)
        return synth_effects(n, rate, seed), {"effect": "deterministic_noise_bursts", "seed": seed}
    if category == "speech_noise":
        noise = rng.normal(0, 1, len(audio)).astype(np.float32)
        speech_rms = float(np.sqrt(np.mean(audio ** 2))) if len(audio) else 0
        noise_rms = speech_rms / (10 ** (params["snr_db"] / 20))
        audio += noise * noise_rms
        metadata.update({"noise": "white_gaussian", "seed": seed})
    elif category == "speech_music_effects":
        music = synth_effects(len(audio), rate, seed, music=True)
        fx = synth_effects(len(audio), rate, seed + 1)
        audio += music + fx
        metadata.update({"music": "three_sine_tones", "effects": "decaying_noise_bursts",
                         "seed": seed, "music_gain": 1.0, "effects_gain": 1.0})
    elif category == "quiet_speech":
        gain = 10 ** (params["level_dbfs"] / 20)
        measured = float(np.sqrt(np.mean(audio ** 2))) if len(audio) else 0
        audio *= gain / measured if measured else 0
        metadata.update({"requested_rms_dbfs": params["level_dbfs"], "applied_gain": gain / measured if measured else 0})
    peak = float(np.max(np.abs(audio))) if len(audio) else 0
    if peak > .98:
        audio *= .98 / peak
        metadata["peak_limited"] = True
    return audio, metadata


def make_words(text: str, events: list[dict], duration: float) -> list[dict]:
    spans = word_spans(text)
    ordered = sorted(events, key=lambda e: (e["character_position"], e["audio_position_s"]))
    words = []
    for word, cstart, cend in spans:
        matching = [e for e in ordered if cstart <= e["character_position"] < cend]
        if not matching:
            matching = [e for e in ordered if e["character_position"] <= cstart]
        start = matching[-1]["audio_position_s"] if matching else None
        next_events = [e["audio_position_s"] for e in ordered if e["character_position"] >= cend]
        end = next_events[0] if next_events else duration
        if start is not None:
            end = max(start, min(duration, end))
        words.append({"text": word, "start_s": start, "end_s": end,
                      "is_target": word.casefold() in TARGETS})
    return words


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--seed", type=int, default=5017)
    ap.add_argument("--voice", default="Microsoft Zira Desktop")
    args = ap.parse_args()
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="wp6-") as td:
        helper = Path(td) / "sapi_helper.ps1"
        helper.write_text(POWERSHELL_HELPER, encoding="utf-8")
        manifest = []
        for index, item in enumerate(UTTERANCES):
            clip_id, category, text, *extra = item
            params = extra[0] if extra else {}
            seed = args.seed + index * 101
            raw_path = Path(td) / f"{clip_id}_raw.wav"
            events = synthesize(text, raw_path, args.voice, helper) if text else []
            if text:
                speech, rate = read_wav(raw_path)
                if rate != RATE:
                    raise ValueError(f"SAPI sample rate {rate}, expected {RATE}")
            else:
                rate, speech = RATE, np.zeros(0, dtype=np.float32)
            audio, mix = mix_for(category, params, speech, rate, seed)
            time_offset = 0.0
            if category == "target_near_start" and len(audio):
                time_offset = .06
                audio = np.concatenate((np.zeros(int(time_offset * rate), np.float32), audio))
            if category == "target_near_end" and len(audio):
                audio = np.concatenate((audio, np.zeros(int(.06 * rate), np.float32)))
            path = out / f"{clip_id}.wav"
            write_wav(path, audio, rate)
            centers, rms = rms_envelope(speech, rate) if len(speech) else (np.array([]), np.array([]))
            centers = centers + time_offset
            words = make_words(text, events, len(speech) / rate if rate else 0)
            for word in words:
                if word["start_s"] is not None:
                    word["start_s"] += time_offset
                    word["end_s"] += time_offset
            # Character-to-audio event boundaries are separately checked against
            # a coarse RMS activity envelope; speech can begin before voiced energy.
            active = np.where(rms > max(1e-5, float(rms.max()) * .015))[0] if len(rms) else np.array([], dtype=int)
            active_start = float(centers[active[0]]) if len(active) else None
            active_end = float(centers[active[-1]]) if len(active) else None
            valid_starts = [w["start_s"] for w in words if w["start_s"] is not None]
            crosscheck = {
                "method": "20ms RMS on speech-only SAPI waveform before mixing; active threshold=max(1e-5, 1.5% of speech max RMS)",
                "active_start_s": active_start, "active_end_s": active_end,
                "first_event_word_start_s": min(valid_starts) if valid_starts else None,
                "first_start_delta_s": (abs(min(valid_starts) - active_start)
                                         if valid_starts and active_start is not None else None),
                "note": "Coarse envelope sanity check, not an alignment oracle."
            }
            manifest.append({
                "clip_id": clip_id, "category": category, "transcript": text,
                "words": words, "duration_s": len(audio) / rate, "sample_rate_hz": rate,
                "channels": 1, "voice": args.voice if text else None,
                "sapi_speak_progress_events": events, "mix_parameters": mix,
                "seed": seed, "wav": path.name, "wav_sha256": sha256_file(path),
                "rms_crosscheck": crosscheck,
            })
        (out / "ground_truth.json").write_text(
            json.dumps({"schema_version": 1, "seed": args.seed, "voice": args.voice,
                        "target_words": sorted(TARGETS), "clips": manifest},
                       indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(out), "clip_count": len(manifest),
                      "duration_s": round(sum(c["duration_s"] for c in manifest), 6),
                      "sha256": {c["wav"]: c["wav_sha256"] for c in manifest}}, indent=2))


if __name__ == "__main__":
    main()
