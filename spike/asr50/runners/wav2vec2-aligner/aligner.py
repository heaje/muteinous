"""Forced alignment with the approved wav2vec2-base-960h ONNX model."""
from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path

import numpy as np


def number_words(value: int) -> str:
    small = ["zero", "one", "two", "three", "four", "five", "six", "seven",
             "eight", "nine", "ten", "eleven", "twelve", "thirteen", "fourteen",
             "fifteen", "sixteen", "seventeen", "eighteen", "nineteen"]
    tens = ["", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy",
            "eighty", "ninety"]
    if value < 20:
        return small[value]
    if value < 100:
        return tens[value // 10] + (("-" + small[value % 10]) if value % 10 else "")
    if value < 1000:
        return small[value // 100] + " hundred" + ((" " + number_words(value % 100)) if value % 100 else "")
    for scale, name in ((1_000_000_000_000, "trillion"),
                        (1_000_000_000, "billion"), (1_000_000, "million"),
                        (1000, "thousand")):
        if value >= scale:
            return (number_words(value // scale) + " " + name
                    + ((" " + number_words(value % scale)) if value % scale else ""))
    return str(value)


def normalize_text(text: str) -> list[str]:
    text = unicodedata.normalize("NFKC", text).casefold()
    text = re.sub(r"(?<=\d),(?=\d)", "", text)
    text = re.sub(r"\d+", lambda m: number_words(int(m.group())), text)
    text = text.replace("’", "'")
    return re.findall(r"[a-z]+(?:'[a-z]+)*", text)


class Aligner:
    def __init__(self, model_path: str | Path, vocab_path: str | Path,
                 threads: int = 4):
        import onnxruntime as ort
        opts = ort.SessionOptions()
        opts.intra_op_num_threads = threads
        opts.inter_op_num_threads = 1
        opts.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
        self.session = ort.InferenceSession(str(model_path), sess_options=opts,
                                            providers=["CPUExecutionProvider"])
        self.vocab = json.loads(Path(vocab_path).read_text(encoding="utf-8"))
        self.id_to_token = {i: token for token, i in self.vocab.items()}
        self.threads = threads

    def _log_probs(self, audio: np.ndarray) -> np.ndarray:
        audio = np.asarray(audio, dtype=np.float32).reshape(-1)
        if audio.size == 0:
            return np.empty((0, len(self.vocab)), dtype=np.float32)
        # wav2vec2 convention: per-utterance zero mean / unit variance.
        audio = (audio - audio.mean()) / max(float(audio.std()), 1e-7)
        logits = self.session.run(None, {"input_values": audio[None, :]})[0][0]
        logits = logits.astype(np.float32)
        logits -= logits.max(axis=-1, keepdims=True)
        return logits - np.log(np.exp(logits).sum(axis=-1, keepdims=True))

    def _viterbi(self, lp: np.ndarray, labels: list[int]) -> tuple[list[int], float]:
        # Expanded CTC state path: blank, token, blank, ...; retain one backpointer byte/state/frame.
        if lp.shape[0] == 0:
            raise ValueError("empty audio")
        states = np.zeros(2 * len(labels) + 1, dtype=np.int32)
        states[1::2] = labels
        t_count, s_count = len(lp), len(states)
        neg = np.float32(-1e30)
        prev = np.full(s_count, neg, np.float32)
        prev[0] = lp[0, 0]
        if s_count > 1:
            prev[1] = lp[0, states[1]]
        back = np.zeros((t_count, s_count), dtype=np.uint8)
        for t in range(1, t_count):
            cur = np.full(s_count, neg, np.float32)
            for s in range(s_count):
                best, source = prev[s], 0
                if s and prev[s - 1] > best:
                    best, source = prev[s - 1], 1
                if s > 1 and states[s] != 0 and states[s] != states[s - 2] and prev[s - 2] > best:
                    best, source = prev[s - 2], 2
                cur[s] = best + lp[t, states[s]]
                back[t, s] = source
            prev = cur
        state = s_count - 1
        if state and prev[state - 1] > prev[state]:
            state -= 1
        score = float(prev[state])
        path = [state]
        for t in range(t_count - 1, 0, -1):
            state -= int(back[t, state])
            path.append(state)
        path.reverse()
        return path, score

    def align(self, audio: np.ndarray, text: str, sample_rate: int = 16000) -> dict:
        # Keep unknown source words visible with null timing rather than silently dropping them.
        source_text = unicodedata.normalize("NFKC", text)
        source_text = re.sub(r"(?<=\d),(?=\d)", "", source_text)
        source_words = re.findall(r"[^\W_]+(?:['’][^\W_]+)*", source_text, flags=re.UNICODE)
        normalized = [normalize_text(w) for w in source_words]
        words = [part for parts in normalized for part in parts]
        unknown_count = sum(not parts for parts in normalized)
        if not words:
            return {"words": [{"text": w, "start": None, "end": None, "alignment_score": None}
                              for w in source_words],
                    "missing_alignment_words": len(source_words), "mean_log_probability": None}
        if sample_rate != 16000:
            raise ValueError("audio must be 16 kHz mono float32")
        # 20 s inference windows with 2 s overlap; conservative fallback divides at word boundaries.
        if len(audio) > 20 * sample_rate:
            result = self._align_chunked(audio, words)
        else:
            result = self._align_window(audio, words, 0.0)
        if unknown_count:
            ordered, cursor = [], 0
            for source, parts in zip(source_words, normalized):
                if not parts:
                    ordered.append({"text": source, "start": None, "end": None, "alignment_score": None})
                else:
                    ordered.extend(result["words"][cursor:cursor + len(parts)])
                    cursor += len(parts)
            result["words"] = ordered
            result["missing_alignment_words"] += unknown_count
        return result

    def _align_window(self, audio: np.ndarray, words: list[str], offset: float) -> dict:
        lp = self._log_probs(audio)
        tokens = []
        word_ranges = []
        for wi, word in enumerate(words):
            start = len(tokens)
            tokens.extend(self.vocab[c.upper()] for c in word)
            word_ranges.append((start, len(tokens)))
            if wi != len(words) - 1:
                tokens.append(self.vocab["|"])
        if any(t == self.vocab.get("<unk>") for t in tokens):
            raise ValueError("text contains characters outside model vocabulary")
        path, total_score = self._viterbi(lp, tokens)
        frames_per_second = lp.shape[0] / (len(audio) / 16000)
        out = []
        for word, (begin, end) in zip(words, word_ranges):
            frames = [t for t, state in enumerate(path)
                      if state and state % 2 and begin <= state // 2 < end]
            if not frames:
                out.append({"text": word, "start": None, "end": None, "alignment_score": None})
                continue
            first, last = min(frames), max(frames)
            char_scores = [float(lp[t, tokens[path[t] // 2]]) for t in frames]
            out.append({"text": word, "start": offset + first / frames_per_second,
                        "end": offset + (last + 1) / frames_per_second,
                        "alignment_score": float(np.mean(char_scores))})
        return {"words": out, "missing_alignment_words": sum(w["start"] is None for w in out),
                "mean_log_probability": total_score / max(1, len(path))}

    def _align_chunked(self, audio: np.ndarray, words: list[str]) -> dict:
        # Allocate windows by character mass, with 2 s overlap to preserve boundary context.
        # Each core region owns its words; overlap predictions are clipped to the core boundary.
        result = []
        n = len(words)
        duration = len(audio) / 16000
        chunks = max(1, int(np.ceil(duration / 18.0)))
        for ci in range(chunks):
            a = ci * duration / chunks
            b = (ci + 1) * duration / chunks
            lo = max(0.0, a - (1.0 if ci else 0.0))
            hi = min(duration, b + (1.0 if ci < chunks - 1 else 0.0))
            left = round(lo / duration * n)
            right = round(b / duration * n) if ci < chunks - 1 else n
            if ci == chunks - 1:
                left = round(a / duration * n)
            subwords = words[left:right]
            if not subwords:
                continue
            aligned = self._align_window(audio[round(lo * 16000):round(hi * 16000)],
                                         subwords, lo)
            result.extend(aligned["words"])
        return {"words": result, "missing_alignment_words": sum(w["start"] is None for w in result),
                "mean_log_probability": float(np.mean([w["alignment_score"] for w in result
                                                       if w["alignment_score"] is not None]))
                if any(w["alignment_score"] is not None for w in result) else None}
