"""Functional-only whisper.cpp run over the frozen ASR corpus v2."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import os
import re
import subprocess
from pathlib import Path

ROOT = Path(r"C:\scratch\asr50")
CORPUS = ROOT / "corpus_v2_frozen"
OUT = ROOT / "results_v2" / "whispercpp"
LOG = ROOT / "WP8" / "logs" / "v2"
MODELS = {
    "turbo": {
        "path": ROOT / "models" / "whisper-large-v3-turbo-whisper-cpp-q5-0" / "ggml-large-v3-turbo-q5_0.bin",
        "sha256": "394221709cd5ad1f40c46e6031ca61bce88931e6e088c188294c6d5a55ffa7e2",
        "slug": "whisper-large-v3-turbo-whisper-cpp-q5-0",
    },
    "small.en": {
        "path": ROOT / "models" / "whisper-small-en-whisper-cpp-q5-1" / "ggml-small.en-q5_1.bin",
        "sha256": "bfdff4894dcb76bbf647d56263ea2a96645423f1669176f4844a1bf8e478ad30",
        "slug": "whisper-small-en-whisper-cpp-q5-1",
    },
}
BIN = {
    "vulkan": ROOT / "WP8" / "bin" / "vulkan" / "whisper-cli.exe",
    "cpu": ROOT / "WP8" / "bin" / "cpu" / "whisper-cli.exe",
}
DEVICES = ("vulkan", "cpu")
SCORE_PATH = Path(r"C:\code\muteinous-spike50\spike\asr50\benchmark\score.py")


def wav_duration(path: Path) -> float:
    # The approved files are IEEE float32 RIFF WAV (format tag 3); wave.open
    # in Python rejects that tag, so use the block alignment/sample-rate fields.
    import struct
    with path.open("rb") as f:
        if f.read(4) != b"RIFF":
            raise ValueError(f"not RIFF: {path}")
        f.read(4)
        if f.read(4) != b"WAVE":
            raise ValueError(f"not WAVE: {path}")
        rate = align = data_size = None
        while chunk := f.read(8):
            if len(chunk) != 8:
                break
            tag, size = struct.unpack("<4sI", chunk)
            body = f.read(size)
            if size & 1:
                f.read(1)
            if tag == b"fmt " and len(body) >= 16:
                _, _, rate, _, align, _ = struct.unpack("<HHIIHH", body[:16])
            elif tag == b"data":
                data_size = size
        if not rate or not align or data_size is None:
            raise ValueError(f"missing WAV fmt/data chunk: {path}")
        return data_size / align / rate


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def timestamp_seconds(tok: dict, key: str):
    # whisper.cpp CLI full JSON offsets are milliseconds.
    value = tok.get("offsets", {}).get(key)
    return value / 1000 if isinstance(value, (int, float)) else None


def merge_tokens(doc: dict) -> tuple[str, list[dict]]:
    """Whitespace starts a word; non-space subwords extend the previous word."""
    groups = []
    for segment in doc.get("transcription", []):
        for tok in segment.get("tokens", []):
            raw = tok.get("text", "")
            stripped = raw.strip()
            if not raw or raw.startswith("[_") or stripped.startswith("[_"):
                continue
            starts_word = raw[:1].isspace()
            if not re.search(r"[\w]", stripped, flags=re.UNICODE):
                continue
            if starts_word or not groups:
                groups.append({"parts": [stripped],
                               "start_s": timestamp_seconds(tok, "from"),
                               "end_s": timestamp_seconds(tok, "to")})
            else:
                groups[-1]["parts"].append(stripped)
                end = timestamp_seconds(tok, "to")
                if end is not None:
                    groups[-1]["end_s"] = end
    words = []
    for group in groups:
        text = "".join(group["parts"])
        text = re.sub(r"^[^\w']+|[^\w']+$", "", text, flags=re.UNICODE)
        # Special token may be fragmented into ordinary-looking pieces.
        if text and text.casefold() != "blank_audio":
            words.append({"text": text, "start_s": group["start_s"], "end_s": group["end_s"]})
    return " ".join(w["text"] for w in words), words


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    LOG.mkdir(parents=True, exist_ok=True)
    gt_doc = json.loads((CORPUS / "ground_truth_v2.json").read_text(encoding="utf-8"))
    clips = gt_doc["clips"]
    if len(clips) != 60:
        raise SystemExit(f"expected 60 frozen clips; got {len(clips)}")
    for clip in clips:
        path = CORPUS / clip.get("wav", f"{clip['clip_id']}.wav")
        if not path.is_file():
            raise SystemExit(f"missing frozen WAV: {path}")
        if sha256(path) != clip["wav_sha256"]:
            raise SystemExit(f"frozen WAV hash mismatch: {path}")
    for model in MODELS.values():
        if sha256(model["path"]) != model["sha256"]:
            raise SystemExit(f"approved model hash mismatch: {model['path']}")

    spec = importlib.util.spec_from_file_location("score", SCORE_PATH)
    score = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(score)

    jobs = []
    for model_key in MODELS:
        for device in DEVICES:
            for clip in clips:
                jobs.append((model_key, device, "full", clip))
                if clip["set"] == "timing":
                    jobs.extend(((model_key, device, "ml1", clip),
                                 (model_key, device, "dtw", clip)))

    jsonl = []
    for index, (model_key, device, mode, clip) in enumerate(jobs, 1):
        model = MODELS[model_key]
        wav = CORPUS / clip.get("wav", f"{clip['clip_id']}.wav")
        config = f"{model_key}-{device}-{mode}"
        tag = f"{config}-{clip['clip_id']}"
        outbase = LOG / tag
        log_path = LOG / f"{tag}.log"
        command = [str(BIN[device]), "-m", str(model["path"]), "-f", str(wav),
                   "-l", "en", "-t", "12", "-ojf", "-of", str(outbase)]
        if device == "vulkan":
            command += ["-dev", "0"]
        else:
            command += ["-ng"]
        if mode == "ml1":
            command += ["-ml", "1"]
        elif mode == "dtw":
            command += ["-nfa", "-dtw", "large.v3.turbo" if model_key == "turbo" else "small.en"]
        env = os.environ.copy()
        env.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", HF_HUB_DISABLE_TELEMETRY="1")
        proc = subprocess.Popen(command, env=env, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, text=True, errors="replace")
        process_id = proc.pid
        log, _ = proc.communicate()
        log_path.write_text(log, encoding="utf-8")
        json_path = Path(str(outbase) + ".json")
        if proc.returncode != 0 or not json_path.exists():
            raise RuntimeError(f"whisper-cli failed ({proc.returncode}) for {tag}; see {log_path}")
        doc = json.loads(json_path.read_text(encoding="utf-8"))
        text, words = merge_tokens(doc)
        actual = "vulkan0" if "using Vulkan0 backend" in log else "cpu"
        if device == "vulkan" and actual != "vulkan0":
            raise RuntimeError(f"Vulkan requested but backend was not confirmed for {tag}; see {log_path}")

        refs = clip.get("words", [])
        lexical = score.edit_counts(score.tokenize(clip.get("transcript", "")),
                                    score.tokenize(text))
        target = score.target_metrics(clip.get("transcript", ""), text, gt_doc.get("target_words", []))
        if mode in {"ml1", "dtw"} and clip["set"] == "timing":
            matches = score.matched_word_pairs(refs, words)
            timing = score.timing_metrics(refs, words, matches)
        else:
            matches, timing = [], None
        duration = float(clip.get("duration_s") or wav_duration(wav))
        silence_non = clip.get("category") in {"silence", "non_speech"}
        hyp_tokens = score.tokenize(text)
        per_clip_hallucination = ({"word_count": len(hyp_tokens),
                                   "has_output": bool(hyp_tokens),
                                   "duration_s": duration} if silence_non else None)

        normalized = {
            "text": text,
            "words": [{"word": w["text"], "start": w["start_s"], "end": w["end_s"]}
                      for w in words],
            "meta": {
                "runtime": "whisper.cpp", "version": "1.9.6-dev",
                "model_artifact": model["slug"], "model_sha256": model["sha256"],
                "requested_device": device, "actual_device": actual,
                "actual_device_verified_by": ("`using Vulkan0 backend` log line"
                                              if actual == "vulkan0"
                                              else "CPU DLL and `CPU total size` log"),
                "settings": {"language": "en", "threads": 12, "mode": mode,
                             "decoding": {"full_json": True, "dtw_flash_attention": False
                                          if mode == "dtw" else None}},
                "process_id": process_id, "exit_code": proc.returncode,
                "process_peak_working_set_bytes": None,
                "peak_dedicated_gpu_bytes": None,
                "clip_set": clip["set"],
            },
            "clip_set": clip["set"],
        }
        raw_dir = OUT / config
        raw_dir.mkdir(parents=True, exist_ok=True)
        (raw_dir / f"{clip['clip_id']}.json").write_text(
            json.dumps(normalized, ensure_ascii=False, indent=2), encoding="utf-8")

        ref_speech = clip["category"] not in {"silence", "non_speech"}
        record = {
            "schema_version": 1,
            "candidate": f"whispercpp-v2-{model_key}-{mode}",
            "clip_id": clip["clip_id"],
            "category": clip["category"],
            "clip_set": clip["set"],
            "run": {"kind": "functional", "index": 0, "process_id": process_id},
            "hardware": {"cpu": "AMD Ryzen 9 9900X", "gpu": "AMD Radeon RX 7900 XT",
                         "ram_bytes": 31600000000, "os": "Windows 11 Pro",
                         "driver": "32.0.32029.2010"},
            "device": {"requested": device, "actual": actual},
            "runtime": {"name": "whisper.cpp", "version": "1.9.6-dev",
                        "package_version": "CI binary 96ec4d98",
                        "installed_bytes": sum(f.stat().st_size for f in BIN[device].parent.iterdir()
                                               if f.is_file())},
            "model": {"artifact_id": model["slug"], "sha256": model["sha256"],
                      "bytes": model["path"].stat().st_size, "cache_bytes": 0},
            "settings": {"language": "en", "sample_rate_hz": 16000, "channels": 1,
                         "threads": 12, "decoding": {"mode": mode}},
            "input": {"sample_rate_hz": 16000, "channels": 1, "dtype": "float32",
                      "clip_sha256": clip["wav_sha256"]},
            "measurements": {"audio_duration_s": duration, "runtime_s": None, "rtf": None,
                             "peak_ram_bytes": None, "peak_vram_bytes": None,
                             "peak_vram_method": "not sampled for per-clip functional run",
                             "model_footprint_bytes": model["path"].stat().st_size},
            "hypothesis": {"text": text,
                           "words": [{"text": w["text"], "start_s": w["start_s"],
                                      "end_s": w["end_s"]} for w in words]},
            "metrics": {
                "wer": lexical["wer"] if ref_speech else None,
                "substitutions": lexical["substitutions"] if ref_speech else None,
                "deletions": lexical["deletions"] if ref_speech else None,
                "insertions": lexical["insertions"] if ref_speech else None,
                "targets": target,
                "timing": timing,
                "timing_matched_word_pairs": matches if timing is not None else None,
                "silence_non_speech": per_clip_hallucination,
                "exit_code": proc.returncode,
                "log": str(log_path),
            },
        }
        jsonl.append(record)
        if index % 30 == 0:
            print(f"completed {index}/{len(jobs)} functional runs", flush=True)

    (OUT / "results.jsonl").write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in jsonl), encoding="utf-8")

    # Aggregate lexical scores over speech clips (WER), target metrics over all
    # clips, silence/non-speech hallucinations per minute, and timing only over
    # the constructed 30-clip set using the scorer's matched-word edit path.
    summary = {}
    for model_key in MODELS:
        for device in DEVICES:
            full = [r for r in jsonl if r["candidate"] == f"whispercpp-v2-{model_key}-full"
                    and r["device"]["requested"] == device]
            speech = [r for r in full if r["category"] not in {"silence", "non_speech"}]
            s = sum(r["metrics"]["substitutions"] for r in speech)
            d = sum(r["metrics"]["deletions"] for r in speech)
            i = sum(r["metrics"]["insertions"] for r in speech)
            ref_count = sum(len(score.tokenize(c["transcript"])) for c in clips
                            if c["category"] not in {"silence", "non_speech"})
            tps = sum(r["metrics"]["targets"]["true_positives"] for r in full)
            fps = sum(r["metrics"]["targets"]["false_positives"] for r in full)
            fns = sum(r["metrics"]["targets"]["false_negatives"] for r in full)
            precision = tps / (tps + fps) if tps + fps else (1.0 if not fns else 0.0)
            recall = tps / (tps + fns) if tps + fns else (1.0 if not fps else 0.0)
            non = [{"duration_s": r["measurements"]["audio_duration_s"],
                    "hypothesis": r["hypothesis"]["text"]}
                   for r in full if r["category"] in {"silence", "non_speech"}]
            summary[f"{model_key}/{device}/full"] = {
                "clips": len(full), "speech_clips": len(speech),
                "wer": (s + d + i) / ref_count if ref_count else None,
                "substitutions": s, "deletions": d, "insertions": i,
                "target_precision": precision, "target_recall": recall,
                "silence_non_speech_hallucination": score.hallucination_metrics(non),
            }
            for mode in ("ml1", "dtw"):
                rows = [r for r in jsonl if r["candidate"] == f"whispercpp-v2-{model_key}-{mode}"
                        and r["device"]["requested"] == device]
                starts, ends = [], []
                missing = 0
                for r in rows:
                    if r["clip_set"] != "timing" or r["metrics"]["timing"] is None:
                        continue
                    met = r["metrics"]["timing"]
                    missing += met["missing_alignment_words"]
                    pairs = r["metrics"]["timing_matched_word_pairs"] or []
                    refs = next(c["words"] for c in clips if c["clip_id"] == r["clip_id"])
                    hyps = r["hypothesis"]["words"]
                    for ri, hi in pairs:
                        ref_word, hyp_word = refs[ri], hyps[hi]
                        if all(isinstance(x, (int, float)) and math.isfinite(x)
                               for x in (ref_word.get("start_s"), ref_word.get("end_s"),
                                         hyp_word.get("start_s"), hyp_word.get("end_s"))):
                            starts.append(abs(ref_word["start_s"] - hyp_word["start_s"]) * 1000)
                            ends.append(abs(ref_word["end_s"] - hyp_word["end_s"]) * 1000)

                def boundary(values):
                    ordered = sorted(values)
                    return {
                        "mean_ms": sum(values) / len(values) if values else None,
                        "median_ms": ((ordered[(len(ordered)-1)//2] + ordered[len(ordered)//2]) / 2
                                      if values else None),
                        "p95_ms": score.percentile_nearest_rank(values, .95),
                        "within_ms": {str(t): sum(v <= t for v in values) / len(values)
                                      for t in (50, 100, 200)} if values else
                                      {str(t): None for t in (50, 100, 200)},
                    }
                summary[f"{model_key}/{device}/{mode}"] = {
                    "timing_clips": len(rows), "word_boundaries": len(starts),
                    "start_error": boundary(starts), "end_error": boundary(ends),
                    "missing_alignment_words": missing,
                }
    (OUT / "score-summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"Wrote {len(jsonl)} rows and score summary under {OUT}")


if __name__ == "__main__":
    main()
