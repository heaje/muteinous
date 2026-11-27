#!/usr/bin/env python
"""Compare corpus output and intermediate-layer hashes from two output roots."""
import json
import sys
from pathlib import Path


def load(root):
    root = Path(root)
    manifest = json.loads((root / "audio16k_v2" / "ground_truth_v2.json").read_text(encoding="utf-8"))
    diagnostics = json.loads((root / "diagnostics_v2.json").read_text(encoding="utf-8"))
    wavs = {c["wav"]: c["wav_sha256"] for c in manifest["clips"]}
    speech = {c["speech_only_wav"]: c["speech_only_sha256"]
              for c in manifest["clips"] if c.get("speech_only_wav")}
    return manifest, diagnostics, wavs, speech


def main():
    if len(sys.argv) != 3:
        raise SystemExit("usage: compare_generations.py ROOT_A ROOT_B")
    a, da, wa, sa = load(sys.argv[1])
    b, db, wb, sb = load(sys.argv[2])
    comparisons = [
        ("cached SAPI raw WAVs", da["sapi_inputs"], db["sapi_inputs"]),
        ("intermediate arrays and headers", da["layers"], db["layers"]),
        ("speech-only WAVs", sa, sb),
        ("final WAVs", wa, wb),
    ]
    all_equal = True
    for label, left, right in comparisons:
        keys = sorted(set(left) | set(right))
        differing = [key for key in keys if left.get(key) != right.get(key)]
        print(f"{label}: {len(keys)-len(differing)}/{len(keys)} equal")
        if differing:
            if all_equal:
                print(f"first differing layer: {label}")
            all_equal = False
            for key in differing[:10]:
                print(f"  {key}: {left.get(key)!r} != {right.get(key)!r}")
    print("RESULT:", "ALL IDENTICAL" if all_equal else "DIFFERENCES FOUND")
    if not all_equal:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
