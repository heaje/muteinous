"""Score WP24 outputs. All source dialogue and derived text stays under WP24."""
from __future__ import annotations

import importlib.util
import json
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path
from statistics import median

import numpy as np
import soundfile as sf

ROOT = Path(r"C:\scratch\asr50\WP24")
CODE = Path(r"C:\code\muteinous-spike50\spike\asr50")
HUSHPATCH_SRC = Path(r"C:\code\hushpatch\src")
ALIGNER_MODEL = Path(r"C:\scratch\asr50\models\wav2vec2-base-960h-onnx")
ALIGNER_CODE = CODE / "runners" / "wav2vec2-aligner" / "aligner.py"
SCORER_CODE = CODE / "benchmark" / "score.py"

ENGINES = {
    "Parakeet TDT int8 CPU": ("parakeet", "direct"),
    "whisper.cpp Turbo q5_0 Vulkan": ("whispercpp-turbo-vulkan", "direct"),
    "whisper.cpp Small.en q5_1 Vulkan": ("whispercpp-small-en-vulkan", "direct"),
    "ORT Whisper Small.en fp16 DML-request": ("ort-whisper-small-en", "dml"),
    "faster-whisper Small.en int8 CPU": ("faster-whisper", "direct"),
    "ORT Whisper Turbo q4 DML-request": ("ort-whisper-turbo", "dml"),
}
CPU_CONTROLS = {
    "whisper.cpp Turbo q5_0 CPU": ("whispercpp-turbo-cpu", "direct"),
    "whisper.cpp Small.en q5_1 CPU": ("whispercpp-small-en-cpu", "direct"),
}


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def load_record(engine: tuple[str, str], clip_id: str) -> dict:
    folder, nested = engine
    path = ROOT / "results" / folder
    if nested != "direct":
        path = path / nested
    source = path / f"{clip_id}.json"
    if not source.exists():
        candidates = sorted(path.glob(f"{clip_id}_*.json"))
        if not candidates:
            raise FileNotFoundError(source)
        source = next((p for p in candidates if "_real_audio_" in p.name), candidates[-1])
    doc = json.loads(source.read_text(encoding="utf-8"))
    return {"text": doc.get("text", ""), "words": doc.get("words", []),
            "meta": doc.get("meta", {}), "error": doc.get("error")}


def word_text(w: dict) -> str:
    return str(w.get("text", w.get("word", "")))


def time_value(w: dict, key: str):
    value = w.get(key)
    if value is None:
        value = w.get(f"{key}_s")
    return value if isinstance(value, (float, int)) else None


def token_edit_distance(a: list[str], b: list[str]) -> int:
    prev = list(range(len(b) + 1))
    for i, aw in enumerate(a, 1):
        cur = [i]
        for j, bw in enumerate(b, 1):
            cur.append(min(cur[-1] + 1, prev[j] + 1, prev[j - 1] + (aw != bw)))
        prev = cur
    return prev[-1]


def summary_metric(items: list[float]) -> dict:
    ordered = sorted(items)
    return {
        "n": len(ordered),
        "median": median(ordered) if ordered else None,
        "p95": ordered[max(0, int(np.ceil(.95 * len(ordered))) - 1)] if ordered else None,
    }


def main() -> None:
    sys.path.insert(0, str(HUSHPATCH_SRC))
    from muteinous.wordlist import WordList

    score = load_module("wp24_score", SCORER_CODE)
    align_module = load_module("wp24_aligner", ALIGNER_CODE)
    sample = json.loads((ROOT / "sample_manifest.json").read_text(encoding="utf-8"))["sampled"]
    speech = [r for r in sample if r["sample_kind"] == "speech"]
    nonspeech = [r for r in sample if r["sample_kind"] != "speech"]
    records = {engine: {r["clip_id"]: load_record(config, r["clip_id"])
                        for r in sample}
               for engine, config in ENGINES.items()}
    cpu_controls = {engine: {r["clip_id"]: load_record(config, r["clip_id"])
                             for r in sample}
                    for engine, config in CPU_CONTROLS.items()}

    # Forced subtitle alignment is one source-local, checkpointed pass.
    alignment_file = ROOT / "alignments.json"
    alignments = (json.loads(alignment_file.read_text(encoding="utf-8"))
                  if alignment_file.exists() else {})
    aligner = align_module.Aligner(ALIGNER_MODEL / "model.onnx",
                                   ALIGNER_MODEL / "vocab.json", threads=4)
    for i, row in enumerate(speech, 1):
        if row["clip_id"] in alignments:
            continue
        try:
            audio, sr = sf.read(row["wav"], dtype="float32")
            if sr != 16000:
                raise ValueError("not 16 kHz")
            alignments[row["clip_id"]] = {
                "result": aligner.align(np.asarray(audio, dtype=np.float32),
                                        row["subtitle"], sample_rate=sr),
                "error": None,
            }
        except Exception as exc:
            alignments[row["clip_id"]] = {
                "result": {"words": []}, "error": f"{type(exc).__name__}: {exc}",
            }
        if i % 25 == 0 or i == len(speech):
            alignment_file.write_text(json.dumps(alignments, ensure_ascii=False),
                                      encoding="utf-8")
            print(f"subtitle alignment checkpoint {i}/{len(speech)}", flush=True)
    alignment_file.write_text(json.dumps(alignments, ensure_ascii=False), encoding="utf-8")

    refs = {r["clip_id"]: score.tokenize(r["subtitle"]) for r in speech}
    asr_tokens = {
        engine: {r["clip_id"]: score.tokenize(records[engine][r["clip_id"]]["text"])
                 for r in speech}
        for engine in ENGINES
    }
    # Per-clip consensus is the medoid transcript minimizing total pairwise
    # Levenshtein distance among the six requested model configurations.
    consensus = {}
    consensus_source = {}
    for row in speech:
        cid = row["clip_id"]
        candidate_list = [(engine, asr_tokens[engine][cid]) for engine in ENGINES]
        winner = min(candidate_list, key=lambda x: sum(
            token_edit_distance(x[1], y) for _, y in candidate_list))
        consensus[cid] = winner[1]
        consensus_source[cid] = winner[0]

    def calculate(engine: str, clip_rows: list[dict], reference_map: dict[str, list[str]]):
        totals = Counter()
        reference_words = 0
        per_clip = {}
        for row in clip_rows:
            cid = row["clip_id"]
            ref = reference_map[cid]
            hyp = score.tokenize(records[engine][cid]["text"])
            edits = score.edit_counts(ref, hyp)
            if edits["wer"] is None:
                continue
            totals["substitutions"] += edits["substitutions"]
            totals["deletions"] += edits["deletions"]
            totals["insertions"] += edits["insertions"]
            reference_words += len(ref)
            per_clip[cid] = {"s": edits["substitutions"], "d": edits["deletions"],
                             "i": edits["insertions"], "n": len(ref)}
        errors = totals["substitutions"] + totals["deletions"] + totals["insertions"]
        return {
            "clips_scored": len(per_clip),
            "reference_words": reference_words,
            "substitutions": totals["substitutions"],
            "deletions": totals["deletions"],
            "insertions": totals["insertions"],
            "wer": errors / reference_words if reference_words else None,
            "_per_clip": per_clip,
        }

    def breakdown(engine: str, dimensions: list[str], reference_map: dict[str, list[str]]):
        output = {}
        for dim in dimensions:
            groups: dict[str, list[dict]] = defaultdict(list)
            for row in speech:
                value = row[dim]
                if isinstance(value, bool):
                    value = "effect-heavy" if value else "clean"
                groups[str(value)].append(row)
            output[dim] = {
                value: calculate(engine, group, reference_map)
                for value, group in sorted(groups.items())
            }
        return output

    result = {
        "sample": {
            "speech_n": len(speech), "vocalization_candidate_n": len(nonspeech),
            "characters": dict(Counter(r["character"] for r in speech)),
            "line_types": dict(Counter(r["line_type"] for r in speech)),
            "length_buckets": dict(Counter(r["length_bucket"] for r in speech)),
            "effects": dict(Counter("effect-heavy" if r["effect_heavy"] else "clean"
                                    for r in speech)),
        },
        "subtitle_wer": {}, "hushpatch_asr_coverage": {}, "consensus_wer": {}, "subgroup_subtitle_wer": {},
        "subgroup_consensus_wer": {}, "subtitle_mismatch": {},
        "targets": {}, "non_speech": {}, "gpu_cpu_agreement": {},
        "timing_agreement": {}, "aligner_errors": Counter(
            x["error"] for x in alignments.values() if x.get("error")
        ),
    }
    for engine in ENGINES:
        subtitle = calculate(engine, speech, refs)
        consens = calculate(engine, speech, consensus)
        result["subtitle_wer"][engine] = {k: v for k, v in subtitle.items() if not k.startswith("_")}
        result["consensus_wer"][engine] = {k: v for k, v in consens.items() if not k.startswith("_")}
        result["subgroup_subtitle_wer"][engine] = breakdown(
            engine, ["character", "line_type", "length_bucket", "effect_heavy"], refs)
        result["subgroup_consensus_wer"][engine] = breakdown(
            engine, ["character", "line_type", "length_bucket", "effect_heavy"], consensus)
    result["hushpatch_asr_coverage"] = {
        "sampled_mapped_clips": len(speech),
        "with_transcript": sum(bool(r["hushpatch_transcript"].strip()) for r in speech),
        "without_transcript": sum(not r["hushpatch_transcript"].strip() for r in speech),
        "wer": None,
        "reason": "Hushpatch transcripts.json stores the unsubtitled-line ASR cache; "
                  "mapped subtitle-bearing lines have no corresponding cached ASR text.",
    }

    all_words = WordList.all_words()
    all_list = WordList(all_words)
    active_list = WordList.load("strict")
    word_by_text = {w.text.casefold(): w for w in all_words}
    target_ref = {}
    for row in speech:
        target_ref[row["clip_id"]] = all_list.find(row["subtitle"])

    # A clip is a likely subtitle mismatch only when >=4/6 transcripts are
    # exactly the medoid transcript and that consensus differs from the subtitle.
    mismatch = []
    mismatch_by_engine = Counter()
    for row in speech:
        cid = row["clip_id"]
        ref = refs[cid]
        cs = consensus[cid]
        agree = sum(asr_tokens[e][cid] == cs for e in ENGINES)
        differs = cs != ref
        if differs and agree >= 4:
            mismatch.append({"clip_id": cid, "agreement": agree,
                             "subtitle_edit_distance": token_edit_distance(ref, cs)})
        for engine in ENGINES:
            if differs and agree >= 4 and asr_tokens[engine][cid] == cs:
                mismatch_by_engine[engine] += 1
    result["subtitle_mismatch"] = {
        "high_consensus_clips": len(mismatch),
        "threshold": "at least 4 of 6 model configurations exactly equal per-clip medoid",
        "engine_at_consensus_in_high_consensus_clips": dict(mismatch_by_engine),
        "mismatch_records": mismatch,
        "consensus_definition": "per-clip medoid: candidate transcript minimizing summed "
                                "pairwise edit distance across the six requested model configurations",
        "consensus_source_counts": dict(Counter(consensus_source.values())),
    }

    # Practical listed-word coverage. WordList.find uses the production
    # tokenizer/matching rules and returns canonical Word identities.
    targets_summary = {}
    for engine in ENGINES:
        cells = Counter()
        miss_types = Counter()
        group_counts: dict[str, Counter] = defaultdict(Counter)
        for row in speech:
            cid = row["clip_id"]
            ref_hits = target_ref[cid]
            hyp_hits = all_list.find(records[engine][cid]["text"])
            ref_counts = Counter(m.word.text.casefold() for m in ref_hits)
            hyp_counts = Counter(m.word.text.casefold() for m in hyp_hits)
            true = sum(min(n, hyp_counts[word]) for word, n in ref_counts.items())
            false_negative = sum(max(0, n - hyp_counts[word]) for word, n in ref_counts.items())
            false_positive = sum(max(0, n - ref_counts[word]) for word, n in hyp_counts.items())
            cells["reference_occurrences"] += sum(ref_counts.values())
            cells["recognized_occurrences"] += true
            cells["missed_occurrences"] += false_negative
            cells["added_occurrences"] += false_positive
            asr = records[engine][cid]["text"]
            asr_tokens_clip = score.tokenize(asr)
            for word, count in ref_counts.items():
                wobj = word_by_text[word]
                key = ("ambiguous" if wobj.ambiguous else "non-ambiguous")
                group_counts[key]["reference"] += count
                group_counts[wobj.category]["reference"] += count
                hit = min(count, hyp_counts[word])
                group_counts[key]["recognized"] += hit
                group_counts[wobj.category]["recognized"] += hit
                miss = count - hit
                if not miss:
                    continue
                if re.search(r"(?:\*{2,}|\bbleep(?:ed)?\b|\bbeep\b|\[censored\])", asr, re.I):
                    category = "euphemized/bleeped/asterisk"
                elif re.search(r"\b(?:heck|darn|dang|shoot|frick|fricking|freaking)\b", asr, re.I):
                    category = "euphemized/bleeped/asterisk"
                elif any(any(abs(len(t) - len(form)) <= 1 and
                             token_edit_distance([t], [form]) <= 1
                             for form in (word, *wobj.forms))
                         for t in asr_tokens_clip):
                    category = "mangled/variant"
                else:
                    category = "missing"
                miss_types[category] += miss
                group_counts[key][category] += miss
                group_counts[wobj.category][category] += miss
        targets_summary[engine] = {
            **dict(cells),
            "recall": (cells["recognized_occurrences"] / cells["reference_occurrences"]
                       if cells["reference_occurrences"] else None),
            "miss_categories": dict(miss_types),
            "by_type": {k: dict(v) for k, v in group_counts.items()},
        }
    result["targets"] = targets_summary
    result["target_word_count"] = {
        "all_wordlist_entries": len(all_words),
        "strict_preset_entries": len(active_list.words),
        "ambiguous_entries": sum(w.ambiguous for w in all_words),
        "subtitle_occurrences": sum(len(h) for h in target_ref.values()),
        "clips_with_target": sum(bool(h) for h in target_ref.values()),
    }

    # Non-speech/vocalization candidate hallucination metrics and output forms.
    ns_total_seconds = sum(r["duration_s"] for r in nonspeech)
    for engine in ENGINES:
        words = sum(len(score.tokenize(records[engine][r["clip_id"]]["text"]))
                    for r in nonspeech)
        clips_with_output = sum(bool(score.tokenize(records[engine][r["clip_id"]]["text"]))
                                for r in nonspeech)
        categories = Counter()
        for row in nonspeech:
            text = records[engine][row["clip_id"]]["text"]
            tokens = score.tokenize(text)
            if not tokens:
                categories["empty"] += 1
            elif re.search(r"\[(?:music|noise|laughter|laughing|sigh|gasp|scream)[^\]]*\]",
                           text, re.I):
                categories["bracketed_nonverbal_marker"] += 1
            elif any(tokens[j] == tokens[j + 1] == tokens[j + 2]
                     for j in range(max(0, len(tokens) - 2))):
                categories["repeated_tokens"] += 1
            elif row.get("vocalization_type") == "laugh":
                categories["vocalization_words"] += 1
            else:
                categories["spurious_lexical_words"] += 1
        result["non_speech"][engine] = {
            "clips": len(nonspeech), "duration_s": ns_total_seconds,
            "words_per_minute": words * 60 / ns_total_seconds if ns_total_seconds else None,
            "words": words, "clips_with_output": clips_with_output,
            "clips_with_output_fraction": clips_with_output / len(nonspeech) if nonspeech else None,
            "output_categories": dict(categories),
        }

    # Exact-transcript and token-level GPU-vs-CPU comparison for both whisper.cpp models.
    for model in ("Turbo q5_0", "Small.en q5_1"):
        gpu_key = f"whisper.cpp {model} Vulkan"
        cpu_key = f"whisper.cpp {model} CPU"
        pairs = [(r["clip_id"], records[gpu_key][r["clip_id"]]["text"],
                  cpu_controls[cpu_key][r["clip_id"]]["text"]) for r in sample]
        result["gpu_cpu_agreement"][model] = {
            "clips": len(pairs),
            "exact_transcript_agreement": sum(a == b for _, a, b in pairs),
            "token_exact_agreement": sum(score.tokenize(a) == score.tokenize(b)
                                         for _, a, b in pairs),
            "speech_exact_transcript_agreement": sum(
                a == b for cid, a, b in pairs if cid in refs),
        }

    # Native word timing agreement with subtitle-forced wav2vec2 alignment.
    for engine in ENGINES:
        starts, ends = [], []
        missing, predicted_words = 0, 0
        clip_timing = {}
        for row in speech:
            cid = row["clip_id"]
            asr_words = records[engine][cid]["words"]
            predicted_words += len(asr_words)
            missing += sum(time_value(w, "start") is None or time_value(w, "end") is None
                           for w in asr_words)
            aligned_words = alignments.get(cid, {}).get("result", {}).get("words", [])
            native = [{"text": word_text(w), "start_s": time_value(w, "start"),
                       "end_s": time_value(w, "end")} for w in asr_words]
            ref = [{"text": word_text(w), "start_s": w.get("start"),
                    "end_s": w.get("end")} for w in aligned_words]
            matches = score.matched_word_pairs(ref, native)
            clip_starts, clip_ends = [], []
            for ri, hi in matches:
                a, b = ref[ri], native[hi]
                if all(isinstance(x, (float, int)) for x in (
                    a["start_s"], a["end_s"], b["start_s"], b["end_s"]
                )):
                    clip_starts.append(abs(a["start_s"] - b["start_s"]) * 1000)
                    clip_ends.append(abs(a["end_s"] - b["end_s"]) * 1000)
            starts.extend(clip_starts)
            ends.extend(clip_ends)
            clip_timing[cid] = {"matches": len(clip_starts),
                                "start_abs_ms": clip_starts, "end_abs_ms": clip_ends}
        result["timing_agreement"][engine] = {
            "matched_words_with_both_boundaries": len(starts),
            "hypothesis_words": predicted_words,
            "missing_native_timing_words": missing,
            "missing_native_timing_fraction": missing / predicted_words if predicted_words else None,
            "start_abs_ms": summary_metric(starts),
            "end_abs_ms": summary_metric(ends),
        }

    # Strip internal fields before saving; report/output contains no dialogue strings.
    (ROOT / "analysis_summary.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps({
        "speech_clips": len(speech), "nonspeech_candidates": len(nonspeech),
        "aligner_errors": len(result["aligner_errors"]),
        "high_consensus_mismatch_clips": len(mismatch),
        "engines": {k: {"subtitle_wer": result["subtitle_wer"][k]["wer"],
                        "consensus_wer": result["consensus_wer"][k]["wer"]}
                    for k in ENGINES},
        "non_speech": {k: {"words_per_minute": v["words_per_minute"],
                           "clips_with_output": v["clips_with_output"]}
                       for k, v in result["non_speech"].items()},
        "target_word_count": result["target_word_count"],
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
