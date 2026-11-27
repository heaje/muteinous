import numpy as np

from aligner import Aligner, normalize_text, number_words


def test_normalization_keeps_contractions_and_spells_numbers():
    assert normalize_text("I've got 21 cats, and 1,999 birds") == [
        "i've", "got", "twenty", "one", "cats", "and", "one", "thousand",
        "nine", "hundred", "ninety", "nine", "birds",
    ]


def test_number_words_large_scales():
    assert number_words(2_004_015) == "two million four thousand fifteen"


def test_word_normalizing_outside_alphabet_is_preserved_unaligned():
    aligner = Aligner.__new__(Aligner)
    result = aligner.align(np.zeros(1600, dtype=np.float32), "你好", sample_rate=16000)
    assert result["words"] == [{
        "text": "你好", "start": None, "end": None, "alignment_score": None,
    }]
    assert result["missing_alignment_words"] == 1
