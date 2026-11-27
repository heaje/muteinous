# Runtime-neutral Silero speech gate (WP18)

`apply_gate.py` runs the Silero VAD ONNX model through ONNX Runtime's CPU
provider and NumPy; it has no ASR or faster-whisper runtime dependency. The
model file is supplied by the caller (`--model`). Install ONNX Runtime, NumPy
and SoundFile in a disposable environment. Input must be 16 kHz mono WAV; this
tool does not resample or change duration.

```powershell
python -I apply_gate.py INPUT_DIR OUTPUT_DIR `
  --model PATH\silero_vad_v6.onnx `
  --threshold 0.5 --speech-pad-ms 100 --min-silence-duration-ms 200
```

Every input WAV is written at the same sample count. Samples outside detected
speech intervals are set to digital zero. `OUTPUT_DIR\manifest.json` lists
sample-index segments and `gate_no_speech`; callers should skip ASR for clips
marked `true`. This is a heuristic gate, not speech recognition or proof that
unmarked audio contains speech. The bundled asset tested for WP18 was copied
from faster-whisper 1.2.1 and is MIT-licensed Silero VAD; see the report for
SHA-256, corpus metrics, limitations and provenance.

`evaluate.py` is the corpus-v2 study runner. It verifies segment parity against
faster-whisper, evaluates the parameter sweep, creates a timeline-preserving
masked corpus and writes `evaluation.json` beside it.
