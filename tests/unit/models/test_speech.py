"""Recognition invariants and refusal of invalid segment-relative timing."""

import math
from dataclasses import FrozenInstanceError, fields

import pytest

from muteinous.models.segment import SegmentKey
from muteinous.models.speech import SpeechAnalysisResult, WordTiming

pytestmark = pytest.mark.portable
KEY = SegmentKey("content:A", "occurrence:1")


def test_result_preserves_independent_transcript_and_analyzed_order() -> None:
    words = (
        WordTiming("go", 0.0, 1.0, -2.5),
        WordTiming("go"),
        WordTiming("NOW", 1.0, 2.0, 3.0),
    )
    transcript = " Go, go now!\n"
    result = SpeechAnalysisResult(KEY, transcript, words, decoded_duration=2.0)

    assert result.segment_key == KEY
    assert result.transcript == transcript
    assert result.words == words
    assert isinstance(result.words, tuple)
    assert result.words[1].start is None and result.words[1].end is None
    assert [field.name for field in fields(result)] == [
        "segment_key",
        "transcript",
        "words",
    ]
    assert not hasattr(result, "decoded_duration")
    with pytest.raises(FrozenInstanceError):
        setattr(result, "words", ())
    with pytest.raises(FrozenInstanceError):
        setattr(result, "transcript", "changed")
    with pytest.raises(FrozenInstanceError):
        setattr(result.words[0], "start", 0.5)


def test_result_rejects_mutable_word_sequence() -> None:
    with pytest.raises(TypeError):
        SpeechAnalysisResult(
            KEY,
            "go",
            [WordTiming("go")],  # type: ignore[arg-type]
            decoded_duration=1.0,
        )


def test_nested_overlapping_and_identical_intervals_are_preserved() -> None:
    words = (
        WordTiming("one", 0.0, 3.0),
        WordTiming("two", 1.0, 2.0),
        WordTiming("three", 1.0, 2.0),
        WordTiming("four", 1.5, 4.0),
    )
    result = SpeechAnalysisResult(KEY, "one two three four", words, 4.0)
    assert result.words == words


def test_all_unaligned_words_are_valid() -> None:
    words = (WordTiming("hello", alignment_score=-0.5), WordTiming("hello"))
    result = SpeechAnalysisResult(KEY, "Hello, hello.", words, 1.0)
    assert result.words == words
    assert all(word.start is None and word.end is None for word in result.words)


def test_empty_recognition_is_valid() -> None:
    result = SpeechAnalysisResult(KEY, "", (), 1.0)
    assert result.transcript == ""
    assert result.words == ()


def test_nonempty_transcript_requires_words() -> None:
    with pytest.raises(ValueError):
        SpeechAnalysisResult(KEY, "hello", (), 1.0)


def test_empty_word_is_rejected() -> None:
    with pytest.raises(ValueError):
        WordTiming("")


@pytest.mark.parametrize(
    ("start", "end"),
    [
        (-0.1, 1.0),
        (1.0, 0.5),
        (1.0, 1.0),
        (math.nan, 1.0),
        (0.0, math.nan),
        (-math.inf, 1.0),
        (0.0, math.inf),
        (None, 1.0),
        (0.0, None),
        (0, 1.0),
        (0.0, 1),
    ],
)
def test_invalid_intrinsic_timing_is_rejected(
    start: float | None, end: float | None
) -> None:
    with pytest.raises(ValueError):
        WordTiming("word", start, end)


@pytest.mark.parametrize("score", [None, -3.5, 0.0, 2.5])
def test_alignment_score_preserves_provider_scale(score: float | None) -> None:
    assert WordTiming("word", 0.0, 1.0, score).alignment_score == score


@pytest.mark.parametrize("score", [math.nan, math.inf, -math.inf, 1])
def test_invalid_alignment_score_is_rejected(score: float) -> None:
    with pytest.raises(ValueError):
        WordTiming("word", alignment_score=score)


@pytest.mark.parametrize("duration", [0.0, -1.0, math.nan, math.inf, -math.inf, True])
def test_invalid_decoded_duration_is_rejected_even_without_timed_words(
    duration: float,
) -> None:
    with pytest.raises(ValueError):
        SpeechAnalysisResult(KEY, "", (), duration)


def test_decoded_duration_is_required() -> None:
    with pytest.raises(TypeError):
        SpeechAnalysisResult(KEY, "", ())  # type: ignore[call-arg]


def test_interval_cannot_exceed_decoded_duration_even_by_one_float_step() -> None:
    word = WordTiming("word", 0.0, math.nextafter(1.0, math.inf))
    with pytest.raises(ValueError):
        SpeechAnalysisResult(KEY, "word", (word,), 1.0)


def test_decreasing_timed_start_across_unaligned_word_is_rejected() -> None:
    words = (
        WordTiming("one", 1.0, 2.0),
        WordTiming("two"),
        WordTiming("three", math.nextafter(1.0, 0.0), 3.0),
    )
    with pytest.raises(ValueError):
        SpeechAnalysisResult(KEY, "one two three", words, 3.0)
