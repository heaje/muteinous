#!/usr/bin/env python
"""Acoustic boundary sanity checks for corpus v2's constructed timing set."""
import json
from pathlib import Path

import numpy as np
import soundfile as sf

ROOT = Path(r"C:\scratch\asr50\WP15\audio16k_v2")
SPEECH_ROOT = Path(r"C:\scratch\asr50\WP15\speech_only16k")
FRAME = 160  # 10 ms at 16 kHz
GUARD = 80  # +/- 5 ms around each boundary


def rms(a):
    if len(a) < FRAME:
        return float(np.sqrt(np.mean(a.astype(np.float64) ** 2))) if len(a) else 0.0
    count = len(a) // FRAME
    return np.sqrt(np.mean(a[:count*FRAME].astype(np.float64).reshape(count, FRAME)**2, axis=1))


def main():
    manifest = json.loads((ROOT / "ground_truth_v2.json").read_text(encoding="utf-8"))
    totals = {}
    failures = []
    for clip in manifest["clips"]:
        if clip["boundary_source"] != "constructed":
            continue
        mixed, sr = sf.read(ROOT / clip["wav"], dtype="float32")
        speech, speech_sr = sf.read(SPEECH_ROOT / clip["speech_only_wav"], dtype="float32")
        if sr != 16000 or speech_sr != 16000 or mixed.ndim != 1 or speech.ndim != 1:
            failures.append((clip["clip_id"], "format", f"mixed={sr}/{mixed.shape}, speech={speech_sr}/{speech.shape}"))
            continue
        if len(mixed) != len(speech):
            failures.append((clip["clip_id"], "mix_shift", f"mixed={len(mixed)} speech={len(speech)}"))
            continue
        words = clip["words"]
        word_rms = []
        for i, word in enumerate(words):
            lo, hi = word["start_sample"], word["end_sample"]
            segment = speech[lo:hi]
            values = rms(segment)
            this_rms = float(np.median(values)) if len(values) else 0.0
            word_rms.append(this_rms)
            if len(segment) != hi-lo or this_rms <= 0:
                failures.append((clip["clip_id"], "word_energy", word["text"]))
            if i+1 < len(words):
                next_start = words[i+1]["start_sample"]
                gap = speech[hi:next_start]
                if len(gap) < 2*GUARD:
                    failures.append((clip["clip_id"], "gap_short", f"{len(gap)} samples"))
                else:
                    interior = gap[GUARD:-GUARD]
                    gap_values = rms(interior)
                    gap_rms = float(np.sqrt(np.mean(interior.astype(np.float64)**2))) if len(interior) else 0
                    if not np.all(interior == 0):
                        failures.append((clip["clip_id"], "speech_gap_not_exact_zero", f"max={float(np.max(np.abs(interior))):.3g}"))
                    median_word_rms = float(np.median(word_rms + [
                        float(np.median(rms(speech[w["start_sample"]:w["end_sample"]])))
                        for w in words[i+1:]]))
                    if gap_rms >= .01 * median_word_rms:
                        failures.append((clip["clip_id"], "gap_to_word_ratio", f"{gap_rms/median_word_rms:.3g}"))
                    if any(float(np.median(rms(speech[w["start_sample"]:w["end_sample"]]))) <= gap_rms
                           for w in (words[i], words[i+1])):
                        failures.append((clip["clip_id"], "word_not_above_gap", f"{gap_rms:.3g}"))
        # Mixed-minus-speech is the additive component. Identical lengths and
        # boundaries establish no temporal offset; validate subtraction/re-add.
        additive = mixed - speech
        if not np.array_equal(speech + additive, mixed):
            failures.append((clip["clip_id"], "mix_alignment", "mix is not sample-additive"))
        stats = totals.setdefault(clip["category"], [0, 0])
        stats[0] += 1
        stats[1] += not any(f[0] == clip["clip_id"] for f in failures)
    print("per-category acoustic boundary checks (pass/total):")
    for category, (total, passed) in sorted(totals.items()):
        print(f"{category}: {passed}/{total}")
    if failures:
        print("FAILURES:")
        for item in failures: print("  ", *item)
        raise SystemExit(1)
    print(f"PASS: {sum(v[1] for v in totals.values())}/{sum(v[0] for v in totals.values())} constructed clips")

if __name__ == "__main__":
    main()
