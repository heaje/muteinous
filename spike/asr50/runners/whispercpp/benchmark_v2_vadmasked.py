"""Run whisper.cpp on the WP18 VAD-masked corpus and score both gate views."""
from __future__ import annotations

import importlib.util
import json
import math
import os
import subprocess
from pathlib import Path

import benchmark_v2 as base

CORPUS = base.ROOT / "WP18" / "corpus_v2_vadmasked"
OUT = base.ROOT / "results_v2_vadmasked" / "whispercpp"
LOG = base.ROOT / "WP8" / "logs" / "vadmasked"
BASELINE = base.ROOT / "results_v2" / "whispercpp" / "results.jsonl"


def timing_summary(rows: list[dict], clips_by_id: dict, mode: str, score) -> dict:
    starts, ends = [], []
    missing_hyp_time = 0
    missing_reference_alignment = 0
    matched_boundaries = 0
    for row in rows:
        if row["clip_set"] != "timing":
            continue
        ref = clips_by_id[row["clip_id"]]["words"]
        hyp = row["hypothesis"]["words"]
        pairs = score.matched_word_pairs(ref, hyp)
        details = score.timing_metrics(ref, hyp, pairs)
        missing_hyp_time += details["missing_alignment_words"]
        missing_reference_alignment += len(ref) - len({ri for ri, _ in pairs})
        for ri, hi in pairs:
            r, h = ref[ri], hyp[hi]
            if all(isinstance(x, (int, float)) and math.isfinite(x)
                   for x in (r.get("start_s"), r.get("end_s"),
                             h.get("start_s"), h.get("end_s"))):
                starts.append(abs(r["start_s"] - h["start_s"]) * 1000)
                ends.append(abs(r["end_s"] - h["end_s"]) * 1000)
                matched_boundaries += 1

    def boundary(values):
        ordered = sorted(values)
        n = len(ordered)
        return {
            "mean_ms": sum(ordered) / n if n else None,
            "median_ms": (ordered[(n - 1) // 2] + ordered[n // 2]) / 2 if n else None,
            "p95_ms": score.percentile_nearest_rank(ordered, .95),
            "within_ms": {str(t): sum(v <= t for v in ordered) / n if n else None
                          for t in (50, 100, 200)},
        }

    return {
        "mode": mode,
        "timing_clips": 30,
        "matched_word_boundaries": matched_boundaries,
        "start_error": boundary(starts),
        "end_error": boundary(ends),
        "missing_reference_words_no_exact_match": missing_reference_alignment,
        "hypothesis_words_missing_timestamps": missing_hyp_time,
    }


def metrics(rows: list[dict], clips: list[dict], gt: dict, score) -> dict:
    by_id = {c["clip_id"]: c for c in clips}
    speech = [r for r in rows if r["category"] not in {"silence", "non_speech"}]
    ref_count = sum(len(score.tokenize(by_id[r["clip_id"]]["transcript"])) for r in speech)
    substitutions = deletions = insertions = 0
    for r in speech:
        ref = score.tokenize(by_id[r["clip_id"]]["transcript"])
        hyp = score.tokenize(r["hypothesis"]["text"])
        edit = score.edit_counts(ref, hyp)
        substitutions += edit["substitutions"]
        deletions += edit["deletions"]
        insertions += edit["insertions"]

    target_counts = [score.target_metrics(by_id[r["clip_id"]]["transcript"],
                                          r["hypothesis"]["text"], gt.get("target_words", []))
                     for r in rows]
    tp = sum(x["true_positives"] for x in target_counts)
    fp = sum(x["false_positives"] for x in target_counts)
    fn = sum(x["false_negatives"] for x in target_counts)
    precision = tp / (tp + fp) if tp + fp else (1.0 if not fn else 0.0)
    recall = tp / (tp + fn) if tp + fn else (1.0 if not fp else 0.0)

    nonspeech = []
    for r in rows:
        if r["category"] in {"silence", "non_speech"}:
            nonspeech.append({
                "duration_s": r["measurements"]["audio_duration_s"],
                "hypothesis": r["hypothesis"]["text"],
            })
    return {
        "clips": len(rows),
        "speech_clips": len(speech),
        "wer": (substitutions + deletions + insertions) / ref_count if ref_count else None,
        "substitutions": substitutions, "deletions": deletions, "insertions": insertions,
        "target_precision": precision, "target_recall": recall,
        "silence_non_speech_hallucination": score.hallucination_metrics(nonspeech),
    }


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    LOG.mkdir(parents=True, exist_ok=True)
    gt = json.loads((CORPUS / "ground_truth_v2.json").read_text(encoding="utf-8"))
    frozen_gt = json.loads((base.CORPUS / "ground_truth_v2.json").read_text(encoding="utf-8"))
    if gt != frozen_gt:
        raise SystemExit("WP18 ground_truth_v2.json differs from frozen corpus-v2 ground truth")
    manifest = json.loads((CORPUS / "manifest.json").read_text(encoding="utf-8"))
    clips = gt["clips"]
    manifest_by_id = {c["clip_id"]: c for c in manifest["clips"]}
    if len(clips) != 60 or len(manifest_by_id) != 60 or set(manifest_by_id) != {
            c["clip_id"] for c in clips}:
        raise SystemExit("expected matching 60-clip ground truth and WP18 manifest")
    if sum(bool(c["gate_no_speech"]) for c in manifest["clips"]) != 20:
        raise SystemExit("expected exactly 20 gate_no_speech clips")

    wavs = {}
    for clip in clips:
        entry = manifest_by_id[clip["clip_id"]]
        wav = CORPUS / entry["file"]
        if not wav.is_file() or base.sha256(wav) != entry["sha256"]:
            raise SystemExit(f"masked WAV missing or hash mismatch: {wav}")
        if entry["input_sha256"] != clip["wav_sha256"]:
            raise SystemExit(f"WP18 source hash does not match frozen corpus-v2 clip: {wav}")
        actual = base.wav_duration(wav)
        if entry["samples"] / gt["sample_rate_hz"] != actual or not math.isclose(
                actual, float(clip["duration_s"]), abs_tol=1 / gt["sample_rate_hz"]):
            raise SystemExit(f"masked WAV duration/sample count mismatch: {wav}")
        wavs[clip["clip_id"]] = wav

    spec = importlib.util.spec_from_file_location("score_vadmasked", base.SCORE_PATH)
    score = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(score)
    baseline_rows = list(map(json.loads, BASELINE.read_text(encoding="utf-8").splitlines()))
    baseline_index = {(r["candidate"].replace("whispercpp-v2-", ""),
                       r["device"]["requested"], r["clip_id"]): r
                      for r in baseline_rows}

    observations = []
    for model_key, model in base.MODELS.items():
        for device in base.DEVICES:
            for clip in clips:
                entry = manifest_by_id[clip["clip_id"]]
                modes = ["full"] + (["ml1", "dtw"] if clip["set"] == "timing" else [])
                for mode in modes:
                    config = f"{model_key}-{device}-{mode}"
                    tag = f"{config}-{clip['clip_id']}"
                    outbase = LOG / tag
                    log_path = LOG / f"{tag}.log"
                    cmd = [str(base.BIN[device]), "-m", str(model["path"]),
                           "-f", str(wavs[clip["clip_id"]]), "-l", "en", "-t", "12",
                           "-ojf", "-of", str(outbase)]
                    cmd += ["-dev", "0"] if device == "vulkan" else ["-ng"]
                    if mode == "ml1":
                        cmd += ["-ml", "1"]
                    elif mode == "dtw":
                        cmd += ["-nfa", "-dtw",
                                "large.v3.turbo" if model_key == "turbo" else "small.en"]
                    env = os.environ.copy()
                    env.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1",
                               HF_HUB_DISABLE_TELEMETRY="1")
                    proc = subprocess.Popen(cmd, env=env, stdout=subprocess.PIPE,
                                            stderr=subprocess.STDOUT, text=True, errors="replace")
                    pid = proc.pid
                    log, _ = proc.communicate()
                    log_path.write_text(log, encoding="utf-8")
                    raw_path = Path(str(outbase) + ".json")
                    if proc.returncode != 0 or not raw_path.is_file():
                        raise RuntimeError(f"whisper-cli failed ({proc.returncode}) for {tag}")
                    if device == "vulkan" and "using Vulkan0 backend" not in log:
                        raise RuntimeError(f"Vulkan0 not confirmed for {tag}; see {log_path}")
                    doc = json.loads(raw_path.read_text(encoding="utf-8"))
                    text, words = base.merge_tokens(doc)
                    actual = "vulkan0" if "using Vulkan0 backend" in log else "cpu"
                    ref = clip["words"]
                    found_pairs = (score.matched_word_pairs(ref, words)
                                   if mode in {"ml1", "dtw"} and clip["set"] == "timing" else [])
                    timing = (score.timing_metrics(ref, words, found_pairs)
                              if mode in {"ml1", "dtw"} and clip["set"] == "timing" else None)
                    duration = float(clip["duration_s"])
                    gate = bool(entry["gate_no_speech"])
                    raw = {
                        "text": text,
                        "words": [{"word": w["text"], "start": w["start_s"], "end": w["end_s"]}
                                  for w in words],
                        "gate_no_speech": gate,
                        "clip_set": clip["set"],
                        "meta": {
                            "runtime": "whisper.cpp", "version": "1.9.6-dev",
                            "model_artifact": model["slug"], "model_sha256": model["sha256"],
                            "requested_device": device, "actual_device": actual,
                            "actual_device_verified_by": ("`using Vulkan0 backend` log line"
                                                          if actual == "vulkan0"
                                                          else "CPU DLL and `CPU total size` log"),
                            "settings": {"language": "en", "threads": 12, "mode": mode,
                                         "decoding": {"full_json": True,
                                                      "dtw_flash_attention": False
                                                      if mode == "dtw" else None}},
                            "process_id": pid, "exit_code": proc.returncode,
                            "process_peak_working_set_bytes": None,
                            "peak_dedicated_gpu_bytes": None,
                            "clip_set": clip["set"],
                        },
                    }
                    outdir = OUT / config
                    outdir.mkdir(parents=True, exist_ok=True)
                    (outdir / f"{clip['clip_id']}.json").write_text(
                        json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")

                    def record_for(view, view_text, view_words):
                        edit = score.edit_counts(score.tokenize(clip["transcript"]),
                                                 score.tokenize(view_text))
                        target = score.target_metrics(clip["transcript"], view_text,
                                                      gt.get("target_words", []))
                        view_pairs = (score.matched_word_pairs(ref, view_words)
                                      if mode in {"ml1", "dtw"} and clip["set"] == "timing" else [])
                        view_timing = (score.timing_metrics(ref, view_words, view_pairs)
                                       if mode in {"ml1", "dtw"} and clip["set"] == "timing" else None)
                        return {
                            "text": view_text,
                            "words": [{"text": w["text"], "start_s": w["start_s"],
                                       "end_s": w["end_s"]} for w in view_words],
                            "wer_ops": {k: edit[k] for k in ("substitutions", "deletions", "insertions")},
                            "targets": target, "timing": view_timing,
                            "timing_matched_word_pairs": view_pairs if view_timing is not None else None,
                            "timing_mode": mode,
                        }

                    baseline_key = (f"{model_key}-{mode}", device, clip["clip_id"])
                    b = baseline_index[baseline_key]
                    basehyp = b["hypothesis"]
                    baseline = record_for("unmasked-v2", basehyp["text"], basehyp["words"])
                    masked = record_for("masked-run", text, words)
                    skipped = record_for("gated-skip", "" if gate else text,
                                         [] if gate else words)
                    observations.append({
                        "candidate": f"whispercpp-v2-vadmasked-{model_key}-{mode}",
                        "clip_id": clip["clip_id"], "category": clip["category"],
                        "clip_set": clip["set"], "gate_no_speech": gate,
                        "device": {"requested": device, "actual": actual},
                        "run": {"kind": "functional", "process_id": pid,
                                "exit_code": proc.returncode},
                        "measurements": {"audio_duration_s": duration,
                                         "runtime_s": None, "rtf": None},
                        "input": {"masked_sha256": entry["sha256"],
                                  "source_sha256": entry["input_sha256"]},
                        "hypothesis": {"text": text, "words": words},
                        "views": {"unmasked-v2": baseline,
                                  "masked-run": masked, "gated-skip": skipped},
                        "metrics": {"log": str(log_path), "exit_code": proc.returncode},
                    })
                    if len(observations) % 30 == 0:
                        print(f"completed {len(observations)}/480 functional runs", flush=True)

    (OUT / "results.jsonl").write_text(
        "".join(json.dumps(x, ensure_ascii=False) + "\n" for x in observations),
        encoding="utf-8")
    summaries = {}
    clips_by_id = {c["clip_id"]: c for c in clips}
    for model_key in base.MODELS:
        for device in base.DEVICES:
            for mode in ("full", "ml1", "dtw"):
                selected = [r for r in observations
                            if r["candidate"] == f"whispercpp-v2-vadmasked-{model_key}-{mode}"
                            and r["device"]["requested"] == device]
                if not selected:
                    continue
                for view in ("unmasked-v2", "masked-run", "gated-skip"):
                    rows = []
                    for r in selected:
                        v = r["views"][view]
                        rows.append({
                            "clip_id": r["clip_id"], "category": r["category"],
                            "clip_set": r["clip_set"], "hypothesis": v,
                            "measurements": r["measurements"],
                        })
                    key = f"{model_key}/{device}/{mode}/{view}"
                    if mode == "full":
                        summaries[key] = metrics(rows, clips, gt, score)
                    else:
                        summaries[key] = timing_summary(rows, clips_by_id, mode, score)
    (OUT / "score-summary.json").write_text(json.dumps(summaries, indent=2), encoding="utf-8")
    print(f"Wrote {len(observations)} masked runs and three-view scores under {OUT}")


if __name__ == "__main__":
    main()
