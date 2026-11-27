import json
import os
import sys
from pathlib import Path

import soundfile as sf

sys.path.insert(0, str(Path(__file__).resolve().parent))
from aligner import Aligner, normalize_text

BASE = Path(r"C:\scratch\asr50")
MODEL = BASE / "models" / "wav2vec2-base-960h-onnx"
AUDIO = BASE / "WP6" / "audio16k"


def main():
    os.environ.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", HF_HUB_DISABLE_TELEMETRY="1")
    aligner = Aligner(MODEL / "model.onnx", MODEL / "vocab.json", 4)
    examples = {}
    for clip_id, text in [
        ("silence_001", ""),
        ("silence_001", "banana"),
        ("nonspeech_001", "banana harbor"),
        ("clean_001", "The banana rests beside cobalt near the harbor and hallucination"),
    ]:
        audio, _ = sf.read(AUDIO / f"{clip_id}.wav", dtype="float32")
        result = aligner.align(audio, text)
        examples[f"{clip_id}:{text or '<empty>'}"] = result
    examples["normalization"] = {
        "input": "I've got 2 cats, 21 birds and 1999 stories.",
        "normalized_words": normalize_text("I've got 2 cats, 21 birds and 1999 stories."),
    }
    (BASE / "results" / "wav2vec2-aligner" / "behavior.json").write_text(
        json.dumps(examples, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
