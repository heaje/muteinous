"""Pure scoring functions for ASR benchmark transcripts and word alignments."""
from __future__ import annotations

import math
import re
import unicodedata
from statistics import mean, median
from typing import Iterable, Sequence

TARGET_WORDS = frozenset({"banana", "cobalt", "harbor"})


def tokenize(text: str) -> list[str]:
    normalized = unicodedata.normalize("NFKC", text).casefold()
    return re.findall(r"[^\W_]+(?:'[^\W_]+)*", normalized, flags=re.UNICODE)


def edit_counts(reference: Sequence[str], hypothesis: Sequence[str]) -> dict:
    """Levenshtein alignment with deterministic diagonal/delete/insert tie order."""
    rows, cols = len(reference) + 1, len(hypothesis) + 1
    cost = [[0] * cols for _ in range(rows)]
    back = [[None] * cols for _ in range(rows)]
    for i in range(1, rows):
        cost[i][0], back[i][0] = i, "D"
    for j in range(1, cols):
        cost[0][j], back[0][j] = j, "I"
    for i in range(1, rows):
        for j in range(1, cols):
            same = reference[i - 1] == hypothesis[j - 1]
            options = [
                (cost[i - 1][j - 1] + (not same), "M" if same else "S"),
                (cost[i - 1][j] + 1, "D"),
                (cost[i][j - 1] + 1, "I"),
            ]
            cost[i][j], back[i][j] = min(options, key=lambda pair: pair[0])
    i, j = len(reference), len(hypothesis)
    substitutions = deletions = insertions = 0
    matches = []
    while i or j:
        op = back[i][j]
        if op == "M":
            matches.append((i - 1, j - 1))
            i, j = i - 1, j - 1
        elif op == "S":
            substitutions += 1
            i, j = i - 1, j - 1
        elif op == "D":
            deletions += 1
            i -= 1
        else:
            insertions += 1
            j -= 1
    matches.reverse()
    n = len(reference)
    wer = (substitutions + deletions + insertions) / n if n else (0.0 if not hypothesis else None)
    return {"substitutions": substitutions, "deletions": deletions,
            "insertions": insertions, "matches": matches, "wer": wer}


def matched_word_pairs(reference_words: Sequence[dict],
                       hypothesis_words: Sequence[dict]) -> list[tuple[int, int]]:
    """Return exact-word (reference index, hypothesis index) pairs from WER's edit path."""
    reference = [tokenize(word["text"])[0] if tokenize(word["text"]) else ""
                 for word in reference_words]
    hypothesis = [tokenize(word["text"])[0] if tokenize(word["text"]) else ""
                  for word in hypothesis_words]
    return edit_counts(reference, hypothesis)["matches"]


def target_metrics(reference: str | Sequence[str], hypothesis: str | Sequence[str],
                   targets: Iterable[str] = TARGET_WORDS) -> dict:
    ref = tokenize(reference) if isinstance(reference, str) else list(reference)
    hyp = tokenize(hypothesis) if isinstance(hypothesis, str) else list(hypothesis)
    target_set = {t.casefold() for t in targets}
    r, h = [w for w in ref if w in target_set], [w for w in hyp if w in target_set]
    aligned = edit_counts(r, h)
    tp = len(aligned["matches"])
    fp, fn = len(h) - tp, len(r) - tp
    precision = tp / (tp + fp) if tp + fp else (1.0 if not fn else 0.0)
    recall = tp / (tp + fn) if tp + fn else (1.0 if not fp else 0.0)
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {"true_positives": tp, "false_positives": fp, "false_negatives": fn,
            "precision": precision, "recall": recall, "f1": f1}


def percentile_nearest_rank(values: Sequence[float], p: float) -> float | None:
    if not values:
        return None
    if not 0 < p <= 1:
        raise ValueError("p must be in (0, 1]")
    ordered = sorted(values)
    return ordered[max(0, math.ceil(p * len(ordered)) - 1)]


def timing_metrics(reference_words: Sequence[dict], hypothesis_words: Sequence[dict],
                   matches: Sequence[tuple[int, int]] | None = None) -> dict:
    if matches is None:
        matches = edit_counts([w["text"].casefold() for w in reference_words],
                              [w["text"].casefold() for w in hypothesis_words])["matches"]
    starts, ends = [], []
    aligned_ref = set()
    for ri, hi in matches:
        r, h = reference_words[ri], hypothesis_words[hi]
        if all(isinstance(x, (int, float)) and math.isfinite(x)
               for x in (r.get("start_s"), r.get("end_s"), h.get("start_s"), h.get("end_s"))):
            aligned_ref.add(ri)
            starts.append(abs(r["start_s"] - h["start_s"]) * 1000)
            ends.append(abs(r["end_s"] - h["end_s"]) * 1000)
    def summary(values: list[float]) -> dict:
        return {"mean_ms": mean(values) if values else None,
                "median_ms": median(values) if values else None,
                "p95_ms": percentile_nearest_rank(values, .95),
                "within_ms": {str(t): sum(v <= t for v in values) / len(values) if values else None
                              for t in (50, 100, 200)}}
    missing = sum(1 for w in hypothesis_words
                  if not all(isinstance(w.get(k), (int, float)) and math.isfinite(w[k])
                             for k in ("start_s", "end_s")))
    return {"start_error": summary(starts), "end_error": summary(ends),
            "missing_alignment_words": missing,
            "missing_alignment_rate": missing / len(hypothesis_words) if hypothesis_words else 0.0}


def hallucination_metrics(clips: Sequence[dict]) -> dict:
    """Input clips are silence/non-speech records with duration_s and hypothesis text."""
    total_s = sum(float(c["duration_s"]) for c in clips)
    word_count = sum(len(tokenize(c.get("hypothesis", ""))) for c in clips)
    any_count = sum(bool(tokenize(c.get("hypothesis", ""))) for c in clips)
    return {"words_per_minute": word_count * 60 / total_s if total_s else None,
            "clips_with_output_fraction": any_count / len(clips) if clips else None}
