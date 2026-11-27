# whisper.cpp WP8 functional runner

The CI binaries and approved model files are staged under `C:\scratch\asr50`
as described in `C:\scratch\asr50\reports\WP8.md`.

Functional matrix (no timing lock, thread sweep, cold/warm pass or RTF work):

```powershell
python C:\code\muteinous-spike50\spike\asr50\runners\whispercpp\benchmark.py --functional
python C:\code\muteinous-spike50\spike\asr50\runners\whispercpp\benchmark.py --functional --mode ml1
python C:\code\muteinous-spike50\spike\asr50\runners\whispercpp\benchmark.py --functional --mode dtw
python C:\code\muteinous-spike50\spike\asr50\runners\whispercpp\summarize.py
```

Each mode covers both approved models, all 14 canonical audio clips, and three
device/build configurations: Vulkan GPU (`-dev 0`), Vulkan binary forced to CPU
(`-ng`), and CPU-DL binary (`-ng`). All runs use English and `-ojf`.

Token-to-word rule: discard control/special tokens (including `[BLANK_AUDIO]`)
and punctuation-only pieces; token text beginning with whitespace starts a
word, otherwise append to the preceding word. Trim outer punctuation and keep
internal apostrophes. Convert JSON `offsets.from/to` from milliseconds to
seconds. DTW outputs use the aligned offsets; pinned `whisper.h` does not
specify units for `t_dtw`, so do not interpret it as centiseconds. These are
recognition word-boundary estimates, not phonetic forced alignments.

## Frozen corpus v2

Run the corpus-v2 matrix with:

```powershell
python C:\code\muteinous-spike50\spike\asr50\runners\whispercpp\benchmark_v2.py
```

This checks the frozen corpus WAV hashes and approved model hashes before
execution. It runs full JSON on all 60 clips and `-ml 1` plus DTW on only the
30 constructed timing clips, for both models on Vulkan and CPU. It collects no
speed measurements and takes no timing lock. Normalized outputs, JSONL and
score summary are written under `C:\scratch\asr50\results_v2\whispercpp\`.
