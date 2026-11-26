"""Immutable recognition output, separate from source text and edit authority."""

import math
from dataclasses import InitVar, dataclass

from muteinous.models.segment import SegmentKey


@dataclass(frozen=True, slots=True)
class WordTiming:
    """One recognized word; absent paired times mean it is unaligned.

    Present times are segment-relative seconds in a half-open interval.
    Alignment scores retain provider-specific meaning, not edit confidence.
    """

    text: str
    start: float | None = None
    end: float | None = None
    alignment_score: float | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.text, str) or not self.text:
            raise ValueError("recognized word text must be a nonempty string")
        if self.start is not None or self.end is not None:
            if not (
                isinstance(self.start, float)
                and isinstance(self.end, float)
                and math.isfinite(self.start)
                and math.isfinite(self.end)
                and 0 <= self.start < self.end
            ):
                raise ValueError("invalid recognized word interval")
        if self.alignment_score is not None and not (
            isinstance(self.alignment_score, float)
            and math.isfinite(self.alignment_score)
        ):
            raise ValueError("alignment score must be a finite float or None")


@dataclass(frozen=True, slots=True)
class SpeechAnalysisResult:
    """Recognition for an occurrence, not evidence of source validity or safe edits.

    The caller must supply the actual decoded audio duration in seconds, not a
    provider estimate. It is used only for construction-time validation.
    Transcript formatting and analyzed word order are preserved independently.
    An empty result does not establish absence of speech or objectionable content.
    """

    segment_key: SegmentKey
    transcript: str
    words: tuple[WordTiming, ...]
    decoded_duration: InitVar[float]

    def __post_init__(self, decoded_duration: float) -> None:
        if (
            isinstance(decoded_duration, bool)
            or not math.isfinite(decoded_duration)
            or decoded_duration <= 0
        ):
            raise ValueError("decoded duration must be finite and positive")
        if not isinstance(self.words, tuple):
            raise TypeError("recognized words must be a tuple")
        if self.transcript and not self.words:
            raise ValueError("nonempty transcript requires recognized words")

        previous_start = 0.0
        for word in self.words:
            if word.start is None:
                continue
            # WordTiming has already validated that the bounds are paired.
            assert word.end is not None
            if word.end > decoded_duration:
                raise ValueError("recognized word exceeds decoded duration")
            if word.start < previous_start:
                raise ValueError("recognized word starts must be nondecreasing")
            previous_start = word.start
