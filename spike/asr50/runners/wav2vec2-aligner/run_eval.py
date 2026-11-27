from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import platform
import sys
import time
from pathlib import Path

import numpy as np
import soundfile as sf

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[1] / "benchmark"))
from score import matched_word_pairs, timing_metrics
from aligner import Aligner, normalize_text


BASE = Path(r"C:\scratch\asr50")
MODEL_DIR = BASE / "models" / "wav2vec2-base-960h-onnx"
AUDIO = BASE / "WP6" / "audio16k"
GT = json.loads((AUDIO / "ground_truth.json").read_text(encoding="utf-8"))["clips"]
CLIPS = {c["clip_id"]: c for c in GT}


def read_audio(clip_id: str) -> np.ndarray:
    audio, rate = sf.read(AUDIO / f"{clip_id}.wav", dtype="float32")
    if rate != 16000 or audio.ndim != 1:
        raise ValueError(f"unexpected WAV format: {clip_id}, rate={rate}, shape={audio.shape}")
    return audio


def ref_words(clip: dict) -> list[dict]:
    return [{"text": w["text"], "start_s": w["start_s"], "end_s": w["end_s"]}
            for w in clip["words"]]


def summarize(records: list[dict]) -> dict:
    all_ref, all_hyp, matches = [], [], []
    for rec in records:
        offset = len(all_ref)
        all_ref.extend(rec["reference_words"])
        all_hyp.extend(rec["words"])
        pairs = matched_word_pairs(rec["reference_words"], rec["words"])
        matches.extend((r + offset, h + sum(len(x["words"]) for x in records[:records.index(rec)]))
                       for r, h in pairs)
    return timing_metrics(all_ref, all_hyp, matches)


def run_oracle(aligner: Aligner, outdir: Path) -> list[dict]:
    output = []
    for clip_id, clip in CLIPS.items():
        audio = read_audio(clip_id)
        result = aligner.align(audio, clip["transcript"])
        words = result["words"]
        for w, source in zip(words, clip["words"]):
            w.update({"start_s": w.pop("start"), "end_s": w.pop("end")})
        record = {"clip_id": clip_id, "category": clip["category"], "transcript": clip["transcript"],
                  "duration_s": len(audio) / 16000, "reference_words": ref_words(clip),
                  "words": words, "missing_alignment_words": result["missing_alignment_words"],
                  "mean_log_probability": result["mean_log_probability"]}
        output.append(record)
        write_raw(outdir.parent, "oracle", clip_id, clip, clip["transcript"], words,
                  len(audio) / 16000, result["mean_log_probability"], result["missing_alignment_words"])
    (outdir / "oracle.json").write_text(json.dumps(output, indent=2), encoding="utf-8")
    return output


def run_pipeline(aligner: Aligner, outdir: Path) -> list[dict]:
    input_root = BASE / "results"
    output = []
    for path in sorted(input_root.rglob("*.json")):
        relative = path.relative_to(input_root).parts
        if len(relative) < 2 or relative[0] == "wav2vec2-aligner":
            continue
        if path.name in ("results.jsonl", "score-summary.json"):
            continue
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        clip_id = path.stem
        run_suffix = ""
        if clip_id not in CLIPS:
            candidates = [key for key in CLIPS if clip_id.startswith(key + "_")]
            if not candidates:
                continue
            clip_id = max(candidates, key=len)
            run_suffix = path.stem[len(clip_id) + 1:]
        if clip_id not in CLIPS or not isinstance(raw, dict) or not isinstance(raw.get("text"), str):
            continue
        clip, audio = CLIPS[clip_id], read_audio(clip_id)
        result = aligner.align(audio, raw["text"])
        words = result["words"]
        for word in words:
            word["start_s"] = word.pop("start")
            word["end_s"] = word.pop("end")
        rec = {"runner": relative[0], "config": "/".join(relative[1:-1]) or "default",
               "run_suffix": run_suffix,
               "clip_id": clip_id,
               "category": clip["category"], "text": raw["text"], "words": words,
               "native_words": raw.get("words", []), "duration_s": len(audio) / 16000,
               "reference_words": ref_words(clip), "missing_alignment_words": result["missing_alignment_words"],
               "mean_log_probability": result["mean_log_probability"], "source": str(path)}
        pairs = matched_word_pairs(rec["reference_words"], words)
        rec["aligner_timing_metrics"] = timing_metrics(rec["reference_words"], words, pairs)
        native = [{"text": w.get("word", w.get("text", "")).strip(),
                   "start_s": w.get("start"), "end_s": w.get("end")} for w in rec["native_words"]]
        rec["native_timing_metrics"] = timing_metrics(
            rec["reference_words"], native, matched_word_pairs(rec["reference_words"], native)) if native else None
        output.append(rec)
        output_config = f"{rec['runner']}--{rec['config']}" + (f"--{run_suffix}" if run_suffix else "")
        write_raw(outdir.parent, output_config, clip_id, clip,
                  raw["text"], words, len(audio) / 16000, result["mean_log_probability"],
                  result["missing_alignment_words"])
    (outdir / "pipeline.json").write_text(json.dumps(output, indent=2), encoding="utf-8")
    return output


def write_raw(root: Path, config: str, clip_id: str, clip: dict, text: str, words: list[dict],
              duration: float, mean_logp: float | None, missing: int) -> None:
    target = root / config / f"{clip_id}.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    raw_words = [{"word": w["text"], "start": w.get("start_s"), "end": w.get("end_s"),
                  "alignment_score": w.get("alignment_score")} for w in words]
    payload = {"text": text, "words": raw_words,
               "meta": {"runtime": "onnxruntime", "runtime_version": "1.32.0",
                        "model_artifact": "wav2vec2-base-960h-onnx",
                        "model_sha256": "00b7cc69516c1ab63c429e63a2b543e4d42bb77441ec5b98ee935de175b00de1",
                        "requested_device": "cpu", "actual_device": "CPUExecutionProvider",
                        "actual_device_verified_by": "InferenceSession.get_providers and successful CPU inference",
                        "settings": {"sample_rate_hz": 16000, "channels": 1},
                        "mean_log_probability": mean_logp, "missing_alignment_words": missing}}
    target.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--threads", type=int, default=4)
    p.add_argument("--mode", choices=("oracle", "pipeline", "both"), default="both")
    p.add_argument("--out", type=Path, default=BASE / "results" / "wav2vec2-aligner" / "cpu")
    args = p.parse_args()
    os.environ.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", HF_HUB_DISABLE_TELEMETRY="1")
    args.out.mkdir(parents=True, exist_ok=True)
    aligner = Aligner(MODEL_DIR / "model.onnx", MODEL_DIR / "vocab.json", args.threads)
    oracle = run_oracle(aligner, args.out) if args.mode in ("oracle", "both") else []
    pipeline = run_pipeline(aligner, args.out) if args.mode in ("pipeline", "both") else []
    (args.out / "summary.json").write_text(json.dumps({
        "threads": args.threads, "oracle_clip_count": len(oracle), "pipeline_observation_count": len(pipeline),
        "oracle_timing": summarize(oracle) if oracle else None,
        "pipeline_aligner_timing": _pipeline_summary(pipeline, "aligner_timing_metrics"),
        "pipeline_native_timing": _pipeline_summary(pipeline, "native_timing_metrics"),
    }, indent=2), encoding="utf-8")
    _write_benchmark(args.out, oracle, pipeline, args.threads)


def _pipeline_summary(records, field):
    metrics = [r[field] for r in records if r[field] is not None]
    if not metrics:
        return None
    return {"observations": len(metrics),
            "start_mean_ms_macro": float(np.mean([m["start_error"]["mean_ms"] for m in metrics
                                                   if m["start_error"]["mean_ms"] is not None])),
            "end_mean_ms_macro": float(np.mean([m["end_error"]["mean_ms"] for m in metrics
                                                 if m["end_error"]["mean_ms"] is not None])),
            "missing_alignment_words": sum(m["missing_alignment_words"] for m in metrics)}


def _write_benchmark(outdir, oracle, pipeline, threads):
    import hashlib
    import onnxruntime
    records = []
    sources = [("oracle", r) for r in oracle]
    sources += [(f"{r['runner']}--{r['config']}" + (f"--{r['run_suffix']}" if r.get("run_suffix") else ""), r)
                for r in pipeline]
    for config, row in sources:
        clip = CLIPS[row["clip_id"]]
        audio_path = AUDIO / f"{row['clip_id']}.wav"
        digest = hashlib.sha256(audio_path.read_bytes()).hexdigest()
        words = [{"text": w["text"], "start_s": w.get("start_s"), "end_s": w.get("end_s")}
                 for w in row["words"]]
        pairs = matched_word_pairs(row["reference_words"], words)
        metrics = timing_metrics(row["reference_words"], words, pairs)
        records.append({
            "schema_version": 1, "candidate": "wav2vec2-aligner", "clip_id": row["clip_id"],
            "category": clip["category"], "run": {"kind": "functional", "index": 0, "process_id": os.getpid()},
            "hardware": {"cpu": platform.processor(), "gpu": None, "ram_bytes": None,
                         "os": platform.platform(), "driver": None},
            "device": {"requested": "cpu", "actual": "CPUExecutionProvider"},
            "runtime": {"name": "onnxruntime", "version": onnxruntime.__version__,
                        "package_version": onnxruntime.__version__, "installed_bytes": None},
            "model": {"artifact_id": "onnx-community/wav2vec2-base-960h-ONNX@729c1a6730fb549c20a1c73a3d3f96f11020225e",
                      "sha256": "00b7cc69516c1ab63c429e63a2b543e4d42bb77441ec5b98ee935de175b00de1",
                      "bytes": 377911891, "cache_bytes": 0},
            "settings": {"language": "en", "sample_rate_hz": 16000, "channels": 1,
                         "threads": threads, "decoding": {"mode": "forced_ctc_viterbi", "source": config}},
            "input": {"sample_rate_hz": 16000, "channels": 1, "dtype": "float32", "clip_sha256": digest},
            "measurements": {"audio_duration_s": row["duration_s"], "runtime_s": None, "rtf": None,
                             "peak_ram_bytes": None, "peak_vram_bytes": None,
                             "peak_vram_method": "unavailable; CPU inference",
                             "model_footprint_bytes": 377912249},
            "hypothesis": {"text": row.get("text", row.get("transcript", "")), "words": words},
            "metrics": metrics,
        })
    jsonl_path = outdir.parent / "results.jsonl"
    jsonl_path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records), encoding="utf-8")
    (outdir.parent / "score-summary.json").write_text(json.dumps({
        "records": len(records), "oracle": summarize(oracle) if oracle else None,
        "pipeline_aligner_macro": _pipeline_summary(pipeline, "aligner_timing_metrics"),
        "pipeline_native_macro": _pipeline_summary(pipeline, "native_timing_metrics"),
        "pipeline_aligner_on_native_timing_observations": _pipeline_summary(
            [r for r in pipeline if r["native_timing_metrics"] is not None],
            "aligner_timing_metrics")
    }, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
