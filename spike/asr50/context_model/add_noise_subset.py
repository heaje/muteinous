"""Add balanced pink-5dB and synthesized-babble-10dB overlays for WP23."""
import importlib.util
import csv
import json
import sys
from pathlib import Path

sys.dont_write_bytecode = True
import numpy as np
import soundfile as sf

source = Path(r"C:\code\muteinous-spike50\spike\asr50\benchmark\corpus_v3\generate_corpus_v3.py")
spec = importlib.util.spec_from_file_location("corpus_v3_audio", source)
module = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(module)
root = Path(r"C:\scratch\asr50\WP23\corpus\audio16k_v3")
manifest_path = root / "ground_truth_v3.json"
manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
clean = [row for row in manifest["clips"] if row["condition"] == "clean"]
known_ids = {row["clip_id"] for row in manifest["clips"]}
base = []
for row in clean:
    samples, sr = sf.read(root / row["wav"], dtype="float32")
    if sr != 16000 or samples.ndim != 1:
        raise ValueError(f"bad canonical WAV: {row['wav']}")
    base.append((row, samples))
new = []
for kind, count, snr in (("pink_noise", 20, 5), ("babble", 20, 10)):
    for i in range(count):
        source_row, speech = base[(i * 7 + (0 if kind == "pink_noise" else 19))]
        rng_seed = 98123 + i + (1000 if kind == "babble" else 0)
        if kind == "pink_noise":
            n = module.noise(len(speech), rng_seed, pink=True)
        else:
            other = base[(i * 11 + 121) % len(base)][1]
            tiled = np.resize(other, len(speech)).astype(np.float32)
            n = module.norm(tiled).astype(np.float32)
        speech_rms = float(np.sqrt(np.mean(speech.astype(np.float64) ** 2)))
        noise_rms = float(np.sqrt(np.mean(n.astype(np.float64) ** 2)))
        mixed = speech + n * (speech_rms / (noise_rms * (10 ** (snr / 20))))
        wav_name = f"wp23_{kind}_{snr}dB_{i+1:02d}.wav"
        clip_id = wav_name[:-4]
        if clip_id in known_ids:
            continue
        digest = module.write_wav(root / wav_name, mixed)
        row = {"clip_id": clip_id, "set": "wp23_overlay",
                    "category": kind, "transcript": source_row["transcript"],
                    "voice": source_row["voice"], "rate": source_row["rate"],
                    "volume": source_row["volume"], "snr_db": snr,
                    "condition": kind, "seed": rng_seed, "sha256": digest,
                    "wav": wav_name, "duration_s": len(mixed) / 16000,
                    "source_clean_clip": source_row["clip_id"]}
        new.append(row)
        known_ids.add(clip_id)
manifest["clips"].extend(new)
manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
if new:
    tsv = root / "clip_list_v3.tsv"
    fields = ["clip_id", "category", "transcript", "voice", "rate", "volume",
              "snr_db", "condition", "seed", "duration_s", "wav", "sha256"]
    with tsv.open("a", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, delimiter="\t", lineterminator="\n")
        for row in new:
            writer.writerow({field: row.get(field, "") for field in fields})
print(f"added {len(new)} overlays: {sum(x['category']=='pink_noise' for x in new)} pink and "
      f"{sum(x['category']=='babble' for x in new)} babble")
