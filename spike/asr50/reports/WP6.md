# WP6 — ASR benchmark preparation report

**Date:** 2026-11-26  
**Scope:** Benchmark specification, synthetic corpus generator, scorer/tests. No ASR inference, model downloads, or GPU claims were made.

## Deliverables

Added under `spike/asr50/benchmark/` in `C:\code\muteinous-spike50`:

- `README.md` — benchmark definitions, normalization and metric conventions, JSONL results schema, measurement rules, equivalent-input rules, and limitations.
- `generate_corpus.py` — deterministic SAPI + NumPy corpus builder.
- `score.py` — pure helpers for normalization, WER/edit counts, target metrics, timing statistics, and hallucinations on negative clips.
- `tests/test_score.py` — scorer unit tests.

Generated corpus is outside the repository at `C:\scratch\asr50\WP6\audio`. Ground truth includes each transcript, word timing/target flag, SAPI events, mix parameters, seed, duration, and per-WAV SHA-256.

## Environment and validation

- Created disposable `C:\scratch\asr50\WP6\venv` with uv / CPython **3.14.10**, installed **NumPy 2.5.5**. Ran the generator using `python.exe -I`.
- Available SAPI voices: **Microsoft David Desktop (en-US)** and **Microsoft Zira Desktop (en-US)**. Generated with Zira.
- SAPI `SpeakProgress` callbacks were observed: **58 word event records for 58 spoken words** in 12 speech clips. Checked event-derived first word starts against a 20 ms RMS envelope on the speech-only SAPI signal before mixing: deltas ranged **7–47 ms** across 12 clips. This is a coarse sanity check, not proof of phonetic boundary accuracy. Starts come from word progress events; ends are approximated by the next word event or utterance end.
- Tests: `uv run --no-project --with pytest --python 3.14.10 -- pytest -q C:\code\muteinous-spike50\spike\asr50\benchmark\tests` → **5 passed**.
- Generated twice with the same seed and compared per-clip WAV SHA-256: **14/14 identical**.

## Corpus inventory

14 clips, **35.178458 seconds** total; mono 22,050 Hz PCM WAV.

| Category | Clips | Duration (s) |
|---|---:|---:|
| clean speech | 1 | 3.404 |
| speech + white noise (10, 0, -5 dB SNR) | 3 | 6.447 |
| speech + synthetic tones/effects | 1 | 2.704 |
| quiet speech (-30, -40 dBFS RMS) | 2 | 4.368 |
| silence | 1 | 1.000 |
| non-speech effects | 1 | 3.000 |
| rapid speech | 1 | 3.359 |
| repeated targets | 1 | 3.394 |
| similar-sounding words | 1 | 2.549 |
| target near start | 1 | 2.559 |
| target near end | 1 | 2.394 |

### WAV SHA-256 manifest

| Clip | SHA-256 |
|---|---|
| `clean_001.wav` | `9fe873c2c2e5779713fbe2526e4ef5cf1405fb5f6f6638bd96476ddaa330a9` |
| `noise_10db.wav` | `9d3af77f648dac2abc950baae4d608dfc1a81647ca5a15d2c67fa0d35dd08fe2` |
| `noise_0db.wav` | `0ca1a21e7cc56630fa7c7799830ae269961e87a1ba02d4e7b404ed8b23ff20fb` |
| `noise_m5db.wav` | `692acd1b070b70d9335b56db73b34f64e186efec7da564ef19800ab1e47f4b4a` |
| `effects_001.wav` | `6c7ed402ee0a1f5f4ef1baca360f89ce53be07d7070c6b17ba8e0a6bdbd78664` |
| `quiet_m30.wav` | `18f675809d981ac4765b7ad19c56354db9eec48fe1232881d35830004e613119` |
| `quiet_m40.wav` | `c83addf0e9bbd35c1456e4acd3cf663a281d48ea994c8a863c9bdbfa66a59234` |
| `silence_001.wav` | `842d8ff3d9508138bd96476dbb2e3c0639ea69070ca01766ad47184befd309b8ec` |
| `nonspeech_001.wav` | `896c6ccbdabd4b5ba5d23fdffa6ee590da1402fa266a7ab854d5f315c2564234` |
| `rapid_001.wav` | `f00509f296c00841b8a0771d3113d89aebae87a4dc36b705a3a7b63d30821f77` |
| `repeated_001.wav` | `66a425b1a365e28783bcb7cb13e1277714451de197d8fa075f20633bf069d507` |
| `similar_001.wav` | `6c3a36aa5a02142f6a684d60719f19347364a8695da4a38ccb533ce6a2098ae8` |
| `edge_start.wav` | `b87d67a2c5c31915f2239e41296da880e999a476c8bcbdc61aaed0af798104cf` |
| `edge_end.wav` | `f7682209a4667686429dd2e3161141d4eed12992e8cc262f4bc2f3a420139249` |

## Limitations and summary

SAPI TTS is not game dialogue, and speech progress timing is not a phonetic forced aligner. Synthetic tones, bursts, and white noise do not reproduce a game's full soundscape. Speech is English only; results should not be generalized to spontaneous or multilingual audio. Later candidate runs must provide actual model artifact IDs/hashes and actual device; none were downloaded or fabricated here.

WP6 is complete: benchmark rules, deterministic corpus, JSON ground truth, scorer, and passing tests are prepared. Evidence is local generation/test evidence only—not ASR or hardware-support evidence. Commands included uv environment/install, isolated (`-I`) generator runs, uv pytest, and per-clip hash comparison. No inference/model download occurred. Wall-clock effort: approximately 12 minutes. Blockers: none for WP6; candidate implementations and model metadata are needed for future measurements. No maintainer approval is needed for this preparation scope.
