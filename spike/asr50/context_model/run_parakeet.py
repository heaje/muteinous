"""Functional Parakeet TDT int8 CPU pass on WP23 generated clips."""
import json
import os
from pathlib import Path

import numpy as np
import sherpa_onnx
import soundfile as sf

os.environ.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1",
                  HF_HUB_DISABLE_TELEMETRY="1")
root = Path(r"C:\scratch\asr50\WP23")
audio = root / "corpus" / "audio16k_v3"
truth = json.loads((audio / "ground_truth_v3.json").read_text(encoding="utf-8"))
model = Path(r"C:\scratch\asr50\models\parakeet-tdt-0-6b-v2-sherpa-onnx-int8")
rec = sherpa_onnx.OfflineRecognizer.from_transducer(
    str(model / "encoder.int8.onnx"), str(model / "decoder.int8.onnx"),
    str(model / "joiner.int8.onnx"), str(model / "tokens.txt"),
    num_threads=4, sample_rate=16000, feature_dim=80, dither=0.0,
    decoding_method="greedy_search", provider="cpu",
    model_type="nemo_transducer", debug=False)
out = root / "asr" / "parakeet-cpu"
out.mkdir(parents=True, exist_ok=True)
records = []
for i, clip in enumerate(truth["clips"], 1):
    try:
        samples, sr = sf.read(audio / clip["wav"], dtype="float32", always_2d=True)
        if sr != 16000 or samples.shape[1] != 1:
            raise ValueError(f"bad audio format {sr} {samples.shape}")
        stream = rec.create_stream()
        stream.accept_waveform(sr, np.ascontiguousarray(samples[:, 0]))
        rec.decode_stream(stream)
        records.append({"clip_id": clip["clip_id"], "text": stream.result.text,
                        "transcript": clip["transcript"], "condition": clip["condition"],
                        "voice": clip.get("voice"), "error": None})
    except Exception as e:
        records.append({"clip_id": clip["clip_id"], "text": "", "transcript": clip["transcript"],
                        "condition": clip["condition"], "error": repr(e)})
    if i % 50 == 0:
        (out / "partial.json").write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"completed {i}/{len(truth['clips'])}", flush=True)
(out / "outputs.json").write_text(json.dumps(records, ensure_ascii=False, indent=2) + "\n",
                                  encoding="utf-8")
print(f"finished {len(records)} clips; failures={sum(bool(x.get('error')) for x in records)}")
