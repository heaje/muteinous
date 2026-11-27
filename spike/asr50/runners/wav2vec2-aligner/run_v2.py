"""Corpus-v2 oracle and ASR-pipeline functional evaluation."""
from __future__ import annotations

import json
import math
import os
import platform
import sys
import time
import unicodedata
from collections import defaultdict
from pathlib import Path

import numpy as np
import soundfile as sf

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[1] / "benchmark"))
from aligner import Aligner
from score import matched_word_pairs, percentile_nearest_rank, timing_metrics, tokenize

CORPUS = Path(r"C:\scratch\asr50\corpus_v2_frozen")
RESULTS = Path(r"C:\scratch\asr50\results_v2")
OUT = RESULTS / "wav2vec2-aligner"
GT = json.loads((CORPUS / "ground_truth_v2.json").read_text(encoding="utf-8"))["clips"]
CLIPS = {c["clip_id"]: c for c in GT}
MODEL = Path(r"C:\scratch\asr50\models\wav2vec2-base-960h-onnx")


def audio_for(clip):
    audio, sr = sf.read(CORPUS / clip["wav"], dtype="float32")
    if sr != 16000 or audio.ndim != 1:
        raise ValueError(f"Expected 16 kHz mono float32: {clip['clip_id']}")
    return audio


def ref_words(clip):
    return [{"text": w["text"], "start_s": w["start_sample"] / 16000,
             "end_s": w["end_sample"] / 16000} for w in clip.get("words", [])]


def error_summary(values):
    if not values:
        return {"count": 0, "mean_ms": None, "median_ms": None, "p95_ms": None,
                "within_ms": {str(x): None for x in (50, 100, 200)}}
    absolute = [abs(x) for x in values]
    return {"count": len(values), "mean_ms": float(np.mean(absolute)),
            "median_ms": float(np.median(absolute)),
            "p95_ms": percentile_nearest_rank(absolute, .95),
            "signed_bias_ms": float(np.mean(values)),
            "signed_median_ms": float(np.median(values)),
            "within_ms": {str(x): sum(v <= x for v in absolute) / len(absolute)
                          for x in (50, 100, 200)}}


def summarize_rows(rows, group_fields):
    groups = defaultdict(list)
    for row in rows:
        groups[tuple(row.get(field) for field in group_fields)].append(row)
    result = {}
    for group, records in sorted(groups.items(), key=lambda x: str(x[0])):
        starts = [w["start_signed_ms"] for r in records for w in r["word_errors"]]
        ends = [w["end_signed_ms"] for r in records for w in r["word_errors"]]
        result[" / ".join(str(x) if x is not None else "unspecified" for x in group)] = {
            "clips": len(records), "matched_words": len(starts),
            "start": error_summary(starts), "end": error_summary(ends),
        }
    return result


def oracle(aligner):
    records = []
    for clip in GT:
        if clip["set"] != "timing":
            continue
        result = aligner.align(audio_for(clip), clip["transcript"])
        references = ref_words(clip)
        pairs = matched_word_pairs(references, result["words"])
        errors = []
        for ri, hi in pairs:
            ref, hyp = references[ri], result["words"][hi]
            if hyp["start"] is None or hyp["end"] is None:
                continue
            errors.append({
                "word": ref["text"], "alignment_score": hyp["alignment_score"],
                "start_signed_ms": (hyp["start"] - ref["start_s"]) * 1000,
                "end_signed_ms": (hyp["end"] - ref["end_s"]) * 1000,
                "hyp_start_s": hyp["start"], "hyp_end_s": hyp["end"],
                "ref_start_s": ref["start_s"], "ref_end_s": ref["end_s"],
            })
        records.append({
            "clip_id": clip["clip_id"], "category": clip["category"], "voice": clip["voice"],
            "text": clip["transcript"], "duration_s": len(audio_for(clip)) / 16000,
            "words": result["words"], "word_errors": errors,
            "missing_alignment_words": result["missing_alignment_words"],
            "mean_log_probability": result["mean_log_probability"],
        })
    timings = [r for r in records if r["word_errors"]]
    starts = [w["start_signed_ms"] for r in timings for w in r["word_errors"]]
    ends = [w["end_signed_ms"] for r in timings for w in r["word_errors"]]
    report = {
        "clip_count": len(records), "matched_word_count": len(starts),
        "missing_alignment_words": sum(r["missing_alignment_words"] for r in records),
        "overall": {"start": error_summary(starts), "end": error_summary(ends)},
        "by_category": summarize_rows(records, ["category"]),
        "by_voice": summarize_rows(records, ["voice"]),
        "by_category_and_voice": summarize_rows(records, ["category", "voice"]),
        "records": records,
    }
    (OUT / "oracle_v2.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    write_raw(records, "oracle")
    return report


def natural(aligner):
    records = []
    for clip in GT:
        if clip["set"] != "natural":
            continue
        audio = audio_for(clip)
        text = clip.get("transcript", "")
        result = aligner.align(audio, text)
        words = result["words"]
        scores = [w["alignment_score"] for w in words if w["alignment_score"] is not None]
        record = {
            "clip_id": clip["clip_id"], "category": clip["category"], "voice": clip.get("voice"),
            "duration_s": len(audio) / 16000,
            "used_chunking_path": len(audio) > 20 * 16000 and bool(text.strip()),
            "text": text, "word_count": len(words),
            "aligned_word_count": sum(w["start"] is not None for w in words),
            "missing_alignment_words": result["missing_alignment_words"],
            "mean_word_log_probability": float(np.mean(scores)) if scores else None,
            "word_scores": scores, "mean_log_probability": result["mean_log_probability"],
        }
        records.append(record)
        write_raw([{"clip_id": clip["clip_id"], "text": text, "words": words,
                    "category": clip["category"], "voice": clip.get("voice")}], "natural")
    report = {"clip_count": len(records), "chunked_transcript_clip_count": sum(
                  r["used_chunking_path"] for r in records),
              "by_category": summarize_natural(records), "records": records}
    (OUT / "natural_v2.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def write_raw(records, config):
    for row in records:
        clip_id = row["clip_id"]
        if "words" not in row:
            continue
        path = OUT / config / f"{clip_id}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        words = row["words"]
        path.write_text(json.dumps({
            "text": row.get("text", ""),
            "words": [{"word": w["text"], "start": w.get("start"), "end": w.get("end"),
                       "alignment_score": w.get("alignment_score")} for w in words],
            "meta": {"runtime": "onnxruntime", "runtime_version": "1.32.0",
                     "model_artifact": "wav2vec2-base-960h-onnx",
                     "requested_device": "cpu", "actual_device": "CPUExecutionProvider",
                     "sample_rate_hz": 16000, "method": "ctc_viterbi"},
        }, indent=2), encoding="utf-8")


def get_clip_id(stem):
    exact = CLIPS.get(stem)
    if exact:
        return stem, ""
    options = [cid for cid in CLIPS if stem.startswith(cid + "_")]
    if not options:
        return None, ""
    cid = max(options, key=len)
    return cid, stem[len(cid) + 1:]


def normalize_native_words(raw):
    result = []
    for word in raw or []:
        if not isinstance(word, dict):
            continue
        text = word.get("word", word.get("text", ""))
        if not isinstance(text, str):
            continue
        result.append({"text": text.strip(),
                       "start_s": word.get("start_s", word.get("start")),
                       "end_s": word.get("end_s", word.get("end"))})
    return result


def auc(scores):
    # Mann-Whitney AUC; ties get half credit.
    positive = [score for score, label in scores if label]
    negative = [score for score, label in scores if not label]
    if not positive or not negative:
        return None
    wins = sum((p > n) + 0.5 * (p == n) for p in positive for n in negative)
    return float(wins / (len(positive) * len(negative)))


def summarize_natural(records):
    result = {}
    for category in sorted({r["category"] for r in records}):
        rows = [r for r in records if r["category"] == category]
        scores = [score for r in rows for score in r["word_scores"]]
        result[category] = {
            "clips": len(rows), "transcript_words": sum(r["word_count"] for r in rows),
            "aligned_words": sum(r["aligned_word_count"] for r in rows),
            "missing_words": sum(r["missing_alignment_words"] for r in rows),
            "mean_word_logp": float(np.mean(scores)) if scores else None,
            "median_word_logp": float(np.median(scores)) if scores else None,
            "p05_word_logp": float(np.percentile(scores, 5)) if scores else None,
            "p95_word_logp": float(np.percentile(scores, 95)) if scores else None,
            "chunked_transcript_clips": sum(r["used_chunking_path"] for r in rows),
        }
    return result


def pipeline(aligner):
    records = []
    for path in sorted(RESULTS.rglob("*.json")):
        relative = path.relative_to(RESULTS).parts
        if len(relative) < 3 or relative[0] == "wav2vec2-aligner":
            continue
        clip_id, suffix = get_clip_id(path.stem)
        clip = CLIPS.get(clip_id) if clip_id else None
        if not clip or clip["set"] != "timing":
            continue
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(raw, dict) or not isinstance(raw.get("text"), str):
            continue
        audio = audio_for(clip)
        aligned = aligner.align(audio, raw["text"])
        ref = ref_words(clip)
        pairs = matched_word_pairs(ref, aligned["words"])
        aligned_for_score = [{"text": w["text"], "start_s": w.get("start"),
                              "end_s": w.get("end")} for w in aligned["words"]]
        timing = timing_metrics(ref, aligned_for_score, pairs)
        native_words = normalize_native_words(raw.get("words"))
        native_pairs = matched_word_pairs(ref, native_words)
        native_timing = timing_metrics(ref, native_words, native_pairs) if native_words else None
        matched_hyp = {hi for _, hi in pairs}
        scored_words = [(w["alignment_score"], i in matched_hyp)
                        for i, w in enumerate(aligned["words"])
                        if w.get("alignment_score") is not None]
        aligner_signed, native_signed = {"start": [], "end": []}, {"start": [], "end": []}
        for ri, hi in pairs:
            reference, hypothesis = ref[ri], aligned_for_score[hi]
            for boundary in ("start", "end"):
                hval = hypothesis[f"{boundary}_s"]
                rval = reference[f"{boundary}_s"]
                if isinstance(hval, (int, float)) and isinstance(rval, (int, float)):
                    aligner_signed[boundary].append((hval - rval) * 1000)
        for ri, hi in native_pairs:
            reference, hypothesis = ref[ri], native_words[hi]
            for boundary in ("start", "end"):
                hval = hypothesis[f"{boundary}_s"]
                rval = reference[f"{boundary}_s"]
                if isinstance(hval, (int, float)) and isinstance(rval, (int, float)):
                    native_signed[boundary].append((hval - rval) * 1000)
        entry = {
            "runner": relative[0], "config": "/".join(relative[1:-1]),
            "clip_id": clip_id, "run_suffix": suffix, "category": clip["category"],
            "voice": clip["voice"], "source": str(path), "text": raw["text"],
            "words": aligned["words"], "matched_pairs": pairs,
            "timing_metrics": timing, "native_timing_metrics": native_timing,
            "aligner_signed_errors_ms": aligner_signed, "native_signed_errors_ms": native_signed,
            "native_words": native_words, "missing_alignment_words": aligned["missing_alignment_words"],
            "mean_log_probability": aligned["mean_log_probability"],
            "scored_words": [{"score": s, "lexically_correct": ok} for s, ok in scored_words],
        }
        records.append(entry)
        output_config = f"{relative[0]}--{'--'.join(relative[1:-1])}"
        output_name = clip_id + (f"--{suffix}" if suffix else "") + ".json"
        output_path = OUT / "pipeline" / output_config / output_name
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps({
            "text": raw["text"],
            "words": [{"word": w["text"], "start": w.get("start"), "end": w.get("end"),
                       "alignment_score": w.get("alignment_score")} for w in aligned["words"]],
            "meta": {"runtime": "onnxruntime", "runtime_version": "1.32.0",
                     "model_artifact": "wav2vec2-base-960h-onnx",
                     "requested_device": "cpu", "actual_device": "CPUExecutionProvider",
                     "aligner": "ctc_viterbi", "source_runner": relative[0],
                     "source_config": "/".join(relative[1:-1]), "source_file": str(path),
                     "missing_alignment_words": aligned["missing_alignment_words"]},
        }, indent=2), encoding="utf-8")
    all_scored = [(w["score"], w["lexically_correct"]) for r in records for w in r["scored_words"]]
    correct = [s for s, label in all_scored if label]
    incorrect = [s for s, label in all_scored if not label]
    native = [r for r in records if r["native_timing_metrics"] is not None]
    report = {
        "observation_count": len(records),
        "unique_timing_clips": len({r["clip_id"] for r in records}),
        "runner_config_counts": dict(sorted((f"{r['runner']}/{r['config']}", sum(
            x["runner"] == r["runner"] and x["config"] == r["config"] for x in records))
                                            for r in records)),
        "aligner_timing_macro": macro(records, "timing_metrics"),
        "native_timing_observation_count": len(native),
        "aligner_boundary_errors_ms": aggregate_pipeline_errors(records, "aligner_signed_errors_ms"),
        "native_boundary_errors_ms": aggregate_pipeline_errors(native, "native_signed_errors_ms"),
        "aligner_boundary_errors_on_native_observations_ms": aggregate_pipeline_errors(
            native, "aligner_signed_errors_ms"),
        "aligner_on_native_observations": macro(native, "timing_metrics"),
        "native_timing_macro": macro(native, "native_timing_metrics"),
        "lexical_score_separation": {
            "correct_word_count": len(correct), "incorrect_inserted_or_substituted_word_count": len(incorrect),
            "correct_mean_logp": float(np.mean(correct)) if correct else None,
            "incorrect_mean_logp": float(np.mean(incorrect)) if incorrect else None,
            "auroc_higher_is_correct": auc(all_scored),
            "interpretation": "Uncalibrated word emission log-probability; low scores can flag forced insertions/substitutions but do not establish recognition correctness."
        },
        "records": records,
    }
    (OUT / "pipeline_v2.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    lines = []
    for i, row in enumerate(records):
        clip = CLIPS[row["clip_id"]]
        wav_hash = clip.get("wav_sha256", "")
        lines.append(json.dumps({
            "schema_version": 1, "candidate": "wav2vec2-aligner", "clip_id": row["clip_id"],
            "category": row["category"], "run": {"kind": "pipeline", "index": i},
            "hardware": {"cpu": platform.processor(), "gpu": None, "ram_bytes": None,
                         "os": platform.platform(), "driver": None},
            "device": {"requested": "cpu", "actual": "CPUExecutionProvider"},
            "runtime": {"name": "onnxruntime", "version": "1.32.0",
                        "package_version": "1.32.0", "installed_bytes": None},
            "model": {"artifact_id": "wav2vec2-base-960h-onnx",
                      "sha256": "00b7cc69516c1ab63c429e63a2b543e4d42bb77441ec5b98ee935de175b00de1",
                      "bytes": 377912249, "cache_bytes": 0},
            "settings": {"language": "en", "sample_rate_hz": 16000, "channels": 1,
                         "threads": 4, "decoding": {"mode": "ctc_viterbi", "asr_source": row["runner"],
                                                        "config": row["config"]}},
            "input": {"sample_rate_hz": 16000, "channels": 1, "dtype": "float32",
                      "clip_sha256": wav_hash},
            "measurements": {"audio_duration_s": len(audio_for(clip)) / 16000, "runtime_s": None,
                             "rtf": None, "peak_ram_bytes": None, "peak_vram_bytes": None,
                             "peak_vram_method": "not measured; CPU functional run",
                             "model_footprint_bytes": 377912249},
            "hypothesis": {"text": row["text"], "words": [
                {"text": w["text"], "start_s": w.get("start"), "end_s": w.get("end")}
                for w in row["words"]]},
            "metrics": {"aligner": row["timing_metrics"], "native": row["native_timing_metrics"]},
        }, ensure_ascii=False))
    (OUT / "pipeline_v2.jsonl").write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
    (OUT / "summary_v2.json").write_text(json.dumps({
        "pipeline_observation_count": len(records), "oracle_clip_count": 30,
        "native_timestamp_observations": len(native),
        "lexical_score_separation": report["lexical_score_separation"],
        "aligner_timing_macro": report["aligner_timing_macro"],
        "aligner_on_native_observations": report["aligner_on_native_observations"],
        "native_timing_macro": report["native_timing_macro"],
    }, indent=2), encoding="utf-8")
    return report


def macro(records, field):
    valid = [r[field] for r in records if r.get(field)]
    if not valid:
        return {"observations": 0}
    starts = [m["start_error"]["mean_ms"] for m in valid if m["start_error"]["mean_ms"] is not None]
    ends = [m["end_error"]["mean_ms"] for m in valid if m["end_error"]["mean_ms"] is not None]
    return {"observations": len(valid),
            "start_mean_ms_macro": float(np.mean(starts)) if starts else None,
            "end_mean_ms_macro": float(np.mean(ends)) if ends else None,
            "missing_alignment_words": sum(m["missing_alignment_words"] for m in valid)}


def aggregate_pipeline_errors(records, field):
    return {boundary: error_summary([v for r in records for v in r[field][boundary]])
            for boundary in ("start", "end")}


def main():
    os.environ.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", HF_HUB_DISABLE_TELEMETRY="1")
    OUT.mkdir(parents=True, exist_ok=True)
    aligner = Aligner(MODEL / "model.onnx", MODEL / "vocab.json", 4)
    timing = oracle(aligner)
    natural_report = natural(aligner)
    pipe = pipeline(aligner)
    (OUT / "summary_v2.json").write_text(json.dumps({
        "oracle": {k: v for k, v in timing.items() if k != "records"},
        "natural": natural_report,
        "pipeline": {k: v for k, v in pipe.items() if k != "records"},
    }, indent=2), encoding="utf-8")
    print(json.dumps({"oracle_clips": timing["clip_count"],
                      "natural_clips": natural_report["clip_count"],
                      "chunked_natural_clips": natural_report["chunked_transcript_clip_count"],
                      "pipeline_observations": pipe["observation_count"],
                      "native_observations": pipe["native_timing_observation_count"]}))


if __name__ == "__main__":
    main()
