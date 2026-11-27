"""Compare Hushpatch production context decisions over WP24 speech only."""
from __future__ import annotations

import json
import re
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(r"C:\scratch\asr50\WP24")
sys.path.insert(0, r"C:\code\hushpatch\src")

from muteinous import games
from muteinous.application import context as application_context
from muteinous.inference import context as inference_context
from muteinous.wordlist import WordList

ENGINE_DIRS = {
    "Parakeet TDT int8 CPU": ("parakeet", None),
    "whisper.cpp Turbo q5_0 Vulkan": ("whispercpp-turbo-vulkan", None),
    "whisper.cpp Small.en q5_1 Vulkan": ("whispercpp-small-en-vulkan", None),
    "ORT Whisper Small.en fp16 DML-request": ("ort-whisper-small-en", "dml"),
    "faster-whisper Small.en int8 CPU": ("faster-whisper", None),
    "ORT Whisper Turbo q4 DML-request": ("ort-whisper-turbo", "dml"),
}


def record_path(folder: str, nested: str | None, clip_id: str) -> Path:
    path = ROOT / "results" / folder
    if nested:
        path /= nested
    exact = path / f"{clip_id}.json"
    if exact.exists():
        return exact
    candidates = sorted(path.glob(f"{clip_id}_*.json"))
    if not candidates:
        raise FileNotFoundError(exact)
    return next((p for p in candidates if "_real_audio_" in p.name), candidates[-1])


def is_name(text, start, end, keep_names):
    return inference_context.overlaps(text, keep_names, start, end)


def main():
    t0 = time.perf_counter()
    samples = json.loads((ROOT / "sample_manifest.json").read_text(encoding="utf-8"))["sampled"]
    speech = [r for r in samples if r["sample_kind"] == "speech"]
    wordlist = WordList.load("strict")
    keep_names = games.GAMES["ff7r"].keep_names
    loader = application_context.model_loader
    cache = {}
    cache_stats = Counter()
    errors = Counter()
    summary = {
        "model_device": "CPU (application context.model_loader(None))",
        "wordlist_preset": "strict",
        "game_name_rules": "games.GAMES['ff7r'].keep_names",
        "engines": {},
    }

    for engine, (folder, nested) in ENGINE_DIRS.items():
        totals = Counter()
        by_type = {}
        for row in speech:
            cid = row["clip_id"]
            source_hits = wordlist.find(row["subtitle"])
            asr_doc = json.loads(record_path(folder, nested, cid).read_text(encoding="utf-8"))
            asr_text = asr_doc.get("text", "")
            hypothesis_hits = wordlist.find(asr_text)
            by_word_source = {}
            for hit in source_hits:
                word = hit.word
                key = word.text.casefold()
                bucket = by_type.setdefault(
                    "ambiguous" if word.ambiguous else "non-ambiguous", Counter())
                totals["subtitle_listed_occurrences"] += 1
                bucket["subtitle_listed_occurrences"] += 1

                def production_decision(text: str, match) -> tuple[bool, str]:
                    if is_name(text, match.start, match.end, keep_names):
                        return False, "name"
                    if not match.word.ambiguous:
                        return True, "wordlist"
                    signature = (text, match.start, match.end, match.word.category,
                                 match.word.text.casefold())
                    if signature in cache:
                        cache_stats["hits"] += 1
                        return cache[signature]
                    try:
                        decision = inference_context.decide(
                            text, match.start, match.end, match.word.category, loader,
                            speaker="", keep_names=keep_names, idioms=wordlist.idioms,
                            device=None, innocent=wordlist.innocent,
                        )
                        value = (bool(decision.censor), str(decision.source))
                    except Exception as exc:
                        errors[type(exc).__name__] += 1
                        value = (False, f"error:{type(exc).__name__}")
                    cache[signature] = value
                    cache_stats["misses"] += 1
                    return value

                source_censor, source_rule = production_decision(row["subtitle"], hit)
                if source_censor:
                    totals["subtitle_decision_censor"] += 1
                    bucket["subtitle_decision_censor"] += 1
                else:
                    totals["subtitle_decision_keep"] += 1
                    bucket["subtitle_decision_keep"] += 1
                if source_rule.startswith("error:"):
                    totals["decision_errors"] += 1

                same_word = [h for h in hypothesis_hits
                             if h.word.text.casefold() == key]
                nth = by_word_source.get(key, 0)
                by_word_source[key] = nth + 1
                if nth >= len(same_word):
                    totals["subtitle_target_absent_asr"] += 1
                    bucket["subtitle_target_absent_asr"] += 1
                    if source_censor:
                        totals["censor_on_subtitle_not_asr"] += 1
                        bucket["censor_on_subtitle_not_asr"] += 1
                    continue
                asr_hit = same_word[nth]
                asr_censor, asr_rule = production_decision(asr_text, asr_hit)
                totals["matched_decisions"] += 1
                bucket["matched_decisions"] += 1
                if source_censor == asr_censor:
                    totals["decision_agreement"] += 1
                    bucket["decision_agreement"] += 1
                if not source_censor and asr_censor:
                    totals["censor_on_asr_not_subtitle"] += 1
                    bucket["censor_on_asr_not_subtitle"] += 1
                if asr_rule.startswith("error:"):
                    totals["decision_errors"] += 1

            # Count listed words emitted by ASR that have no corresponding subtitle hit.
            src_counts = Counter(h.word.text.casefold() for h in source_hits)
            hyp_counts = Counter(h.word.text.casefold() for h in hypothesis_hits)
            extras = sum(max(0, n - src_counts[k]) for k, n in hyp_counts.items())
            totals["asr_listed_occurrences_absent_subtitle"] += extras

        summary["engines"][engine] = {
            **dict(totals),
            "agreement": (totals["decision_agreement"] / totals["matched_decisions"]
                          if totals["matched_decisions"] else None),
            "by_type": {k: dict(v) for k, v in by_type.items()},
        }
        print(f"context engine checkpoint {engine}", flush=True)

    summary["model_calls"] = cache_stats["misses"]
    summary["cache_hits"] = cache_stats["hits"]
    summary["decision_errors"] = dict(errors)
    summary["elapsed_s_observation_only"] = time.perf_counter() - t0
    try:
        application_context.release()
    except Exception as exc:
        summary["release_error"] = type(exc).__name__
    (ROOT / "context_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps({
        "models_calls": cache_stats["misses"], "cache_hits": cache_stats["hits"],
        "decision_errors": dict(errors),
        "engine_metrics": {k: {"matched_decisions": v["matched_decisions"],
                              "agreement": v["agreement"],
                              "censor_on_subtitle_not_asr": v.get("censor_on_subtitle_not_asr", 0),
                              "censor_on_asr_not_subtitle": v.get("censor_on_asr_not_subtitle", 0)}
                          for k, v in summary["engines"].items()},
    }))


if __name__ == "__main__":
    main()
