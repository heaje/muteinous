# Transcript-only corpus v3

`generate_corpus_v3.py` deterministically creates 380 clips: 150 authored sentences in two Microsoft SAPI voices (300 clean clips), 40 acoustic-condition variants, and 40 non-speech clips. The fixed corpus seed is 5021; numpy `default_rng` derives every rate, volume, noise and condition seed. Rates are varied from -4 through +4; volume from 65 through 100. SAPI WAVs are retained in a content-addressed cache (SHA-256 filenames and manifest); its key includes exact text, voice, rate and volume.

All delivered files are mono 16 kHz IEEE float32 WAVs, resampled from SAPI's 22.05 kHz PCM with `scipy.signal.resample_poly`. The libsndfile `PEAK` timestamp is zeroed before hashing. `ground_truth_v3.json` and `clip_list_v3.tsv` contain transcript-level reference only; **there are no word timings**. Schema entries include `clip_id`, `set`, `category`, `transcript`, `voice`, `rate`, `volume`, `snr_db`, `condition`, `seed`, and WAV SHA-256.

Transcripts are exactly the written, spoken-form sentences. Numbers and dates are spelled out in words (not digits); contractions and punctuation are retained. Names are spelled as intended to be spoken. For scoring, lowercase and remove standard punctuation, then compare whitespace-separated words. Non-speech clips use an empty transcript. The five `non_speech_*` classes are silence with -70 dBFS dither, low-level room tone, music-only, effects-only and babble-like overlapping noise. Babble mixed from intelligible synthesized sentences is speech, so it appears only as `babble_10dB` / `babble_0dB` condition variants.

Condition variants include white and pink noise at 15/5/0 dB SNR (RMS-calibrated), synthesized-speech babble at 10/0 dB, music-like loops, game-like transients, synthetic reverberation with 0.3–1.2 second decays, and band-limited/8-bit-ish radio processing. Requested durations for non-speech classes span 2–30 seconds. The generator prints aggregate counts and duration by category.

Run in a disposable Python environment with numpy, scipy and soundfile installed:

```powershell
python -I generate_corpus_v3.py --output-root C:\scratch\asr50\WP21\run_a --sapi-cache C:\scratch\asr50\WP21\sapi_cache
```

Keep generated audio, caches and comparison outputs under `C:\scratch\asr50\WP21\`; only generator/documentation and text manifests belong in this directory.
