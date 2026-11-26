import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from score import edit_counts, hallucination_metrics, target_metrics, timing_metrics, tokenize


def test_normalization_and_punctuation():
    assert tokenize("CÓBALT, cobalt/cobol—harbor!") == ["cóbalt", "cobalt", "cobol", "harbor"]


def test_wer_substitutions_deletions_insertions_and_empty_reference():
    result = edit_counts(["a", "b", "c"], ["a", "x", "d", "c"])
    assert (result["substitutions"], result["deletions"], result["insertions"]) == (1, 0, 1)
    assert result["wer"] == 2 / 3
    assert edit_counts([], [])["wer"] == 0
    assert edit_counts([], ["x"])["wer"] is None


def test_target_counts_similar_sounding_words_are_not_equivalent():
    got = target_metrics("banana cobalt harbor", "banana cobol arbor")
    assert got["true_positives"] == 1
    assert got["false_negatives"] == 2
    assert got["false_positives"] == 0
    assert got["recall"] == 1 / 3


def test_timing_summary_and_missing_alignment():
    refs = [{"text": "a", "start_s": 1.0, "end_s": 1.2},
            {"text": "b", "start_s": 1.5, "end_s": 1.7}]
    hyps = [{"text": "a", "start_s": 1.05, "end_s": 1.3},
            {"text": "b", "start_s": None, "end_s": None}]
    got = timing_metrics(refs, hyps)
    assert got["start_error"]["mean_ms"] == pytest.approx(50)
    assert got["end_error"]["mean_ms"] == pytest.approx(100)
    assert got["missing_alignment_words"] == 1
    assert got["missing_alignment_rate"] == .5


def test_hallucination_rates_only_count_provided_negative_clips():
    got = hallucination_metrics([
        {"duration_s": 30, "hypothesis": "noise"},
        {"duration_s": 30, "hypothesis": ""},
    ])
    assert got == {"words_per_minute": 1.0, "clips_with_output_fraction": .5}
