"""Prepare the locally approved FF7R real-audio sample; all derived data stays in WP24."""
from __future__ import annotations

import csv
import json
import random
import re
import wave
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy.signal import resample_poly

SOURCE = Path(
    r"C:\code\hushpatch\work\steam-1462040\copies"
    r"\46cb34bca1609c9cf94ef24bedd3d13e653bf35f30a5d57ccd4737e378b0b9e5"
)
OUT = Path(r"C:\scratch\asr50\WP24")
SEED = 24027
SPEECH_N = 300
NON_SPEECH_N = 60


def line_type(line_id: str) -> str:
    s = line_id.casefold()
    prefix = s[:2]
    if prefix == "tk":
        return "talk"
    if prefix == "ev":
        return "event"
    if prefix == "ba":
        return "battle"
    if prefix == "pv":
        return "pv"
    if re.search(r"(?:^|[_#])pv(?:[_#]|$)|preview|promotion", s):
        return "pv"
    if "battle" in s or re.search(r"(?:^|[_#])bt(?:[_#]|$)", s):
        return "battle"
    if "event" in s or re.search(r"(?:^|[_#])ev(?:[_#]|$)", s):
        return "event"
    if "talk" in s or re.search(r"(?:^|[_#])tk(?:[_#]|$)", s):
        return "talk"
    return "other"


def word_count(text: str) -> int:
    return len(re.findall(r"[^\W_]+(?:['’][^\W_]+)*", text, re.UNICODE))


def vocalization_label(text: str) -> str | None:
    cleaned = re.sub(r"[^a-z' ]", "", text.casefold()).strip()
    cleaned = re.sub(r"\s+", " ", cleaned)
    if re.search(r"\b(?:laugh|laughing|laughter|hahaha|hehe|ha ha|heh heh)\b", cleaned):
        return "laugh"
    if cleaned in {"ah", "oh", "uh", "huh", "hmm", "hm", "ugh", "oof", "ha",
                   "hah", "heh", "gasp", "grunting", "sigh"}:
        return "effort_or_interjection"
    return None


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    audio_root = SOURCE / "audio"
    transcripts = json.loads((SOURCE / "transcripts.json").read_text(encoding="utf-8"))
    subtitles: dict[str, str] = {}
    for textfile in (SOURCE / "text_json").rglob("*.json"):
        doc = json.loads(textfile.read_text(encoding="utf-8"))
        for entry in doc.get("entries", []):
            if entry.get("text"):
                # Matches UnrealTxtRes.lines(): entry id has a leading "$" prefix.
                key = entry["id"].lstrip("$").casefold()
                subtitles.setdefault(key, entry["text"])

    files = sorted(audio_root.rglob("*.wav"))
    per_asset: dict[str, list[Path]] = defaultdict(list)
    for path in files:
        rel = path.relative_to(audio_root)
        asset_id = rel.parts[0] if len(rel.parts) >= 2 else path.stem
        per_asset[asset_id.casefold()].append(path)
    records = []
    for path in files:
        rel = path.relative_to(audio_root)
        asset_id = rel.parts[0] if len(rel.parts) >= 2 else path.stem
        track_paths = sorted(per_asset[asset_id.casefold()])
        track_index = track_paths.index(path)
        # Hushpatch maps a subtitle directly to a voice asset only when that asset
        # contains exactly one track. Multi-track banks are expanded as unsupplied
        # transcript lines (asset#NNN), not as the bank's one subtitle.
        line_id = asset_id if len(track_paths) == 1 else f"{asset_id}#{track_index:03d}"
        subtitle = subtitles.get(asset_id.casefold()) if len(track_paths) == 1 else None
        with wave.open(str(path), "rb") as wav:
            rate, channels, width, frames = (
                wav.getframerate(), wav.getnchannels(), wav.getsampwidth(), wav.getnframes()
            )
        duration = frames / rate
        folder = asset_id
        typ = line_type(asset_id)
        # FF7R extracted line ids end with a speaker code and a track suffix.
        # Keep the code, not the per-line id, as the character stratum.
        pieces = asset_id.split("_")
        character = pieces[-2] if len(pieces) > 2 else "unknown"
        if duration < 2:
            length = "short<2s"
        elif duration < 6:
            length = "2-6s"
        elif duration < 15:
            length = "6-15s"
        else:
            length = "15s+"
        records.append({
            "clip_id": f"clip_{len(records):05d}",
            "source_rel": str(path.relative_to(audio_root)),
            "line_id": line_id,
            "folder": folder,
            "character": character,
            "line_type": typ,
            "duration_s": duration,
            "sample_rate_hz": rate,
            "channels": channels,
            "sample_width_bytes": width,
            "length_bucket": length,
            "mapped": subtitle is not None,
            "subtitle": subtitle or "",
            "hushpatch_transcript": transcripts.get(line_id, ""),
        })

    mapped = [r for r in records if r["mapped"]]
    rng = random.Random(SEED)
    # Round-robin through character × line-type × duration strata; shuffling is seeded.
    strata: dict[tuple[str, str, str], list[dict]] = defaultdict(list)
    for row in mapped:
        strata[row["character"], row["line_type"], row["length_bucket"]].append(row)
    for pool in strata.values():
        rng.shuffle(pool)
    selected = []
    keys = list(strata)
    rng.shuffle(keys)
    while len(selected) < min(SPEECH_N, len(mapped)):
        advanced = False
        for key in keys:
            if strata[key] and len(selected) < SPEECH_N:
                selected.append(strata[key].pop())
                advanced = True
        if not advanced:
            break
    # Keep a diverse set of characters and types where the source has them.
    char_counts = Counter(r["character"] for r in selected)
    type_counts = Counter(r["line_type"] for r in selected)

    # Non-speech proxy candidates: no subtitle / blank Hushpatch transcript, favor
    # short tracks and folders/IDs explicitly marked battle, effort, voice, or effect.
    candidates = []
    for row in records:
        label = vocalization_label(row["hushpatch_transcript"])
        if not row["mapped"] and label:
            row["vocalization_type"] = label
            candidates.append(row)
    by_folder: dict[str, list[dict]] = defaultdict(list)
    for row in candidates:
        by_folder[row["folder"]].append(row)
    for pool in by_folder.values():
        rng.shuffle(pool)
    nonspeech = []
    folders = list(by_folder)
    rng.shuffle(folders)
    folder_used = Counter()
    while len(nonspeech) < min(NON_SPEECH_N, len(candidates)):
        advanced = False
        for folder in folders:
            if by_folder[folder] and folder_used[folder] < 2 and len(nonspeech) < NON_SPEECH_N:
                nonspeech.append(by_folder[folder].pop())
                folder_used[folder] += 1
                advanced = True
        if not advanced:
            break

    sample_rows = []
    for kind, batch in (("speech", selected), ("non_speech_candidate", nonspeech)):
        for row in batch:
            rel = Path(row["source_rel"])
            source_path = audio_root / rel
            audio, rate = sf.read(source_path, dtype="float32", always_2d=True)
            audio = audio.mean(axis=1, dtype=np.float32)
            if rate != 16000:
                from math import gcd
                div = gcd(rate, 16000)
                audio = resample_poly(audio, 16000 // div, rate // div).astype(np.float32)
            audio = np.ascontiguousarray(audio, dtype=np.float32)
            output = OUT / "audio16k" / f"{row['clip_id']}.wav"
            sf.write(output, audio, 16000, subtype="FLOAT", format="WAV")
            row.update({
                "sample_kind": kind,
                "wav": str(output),
                "resample_method": "scipy.signal.resample_poly; float32; mono; 16 kHz",
                "effect_heavy": bool(re.search(
                    r"radio|intercom|distort|filter|phone|helmet|comm|speaker",
                    row["line_id"] + " " + row["folder"], re.I
                )),
            })
            sample_rows.append(row)

    (OUT / "sample_manifest.json").write_text(
        json.dumps({"seed": SEED, "speech_requested": SPEECH_N,
                    "non_speech_requested": NON_SPEECH_N,
                    "sampled": sample_rows}, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )
    # Human-readable clip-list has identifiers and strata only, never game text/audio.
    with (OUT / "clip-list.csv").open("w", newline="", encoding="utf-8") as f:
        fields = ["clip_id", "sample_kind", "character", "line_type", "length_bucket",
                  "duration_s", "effect_heavy", "source_rel"]
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows({k: row.get(k) for k in fields} for row in sample_rows)
    ground_truth = {
        "schema_version": 1,
        "clips": [
            {
                "clip_id": row["clip_id"],
                "wav": f"{row['clip_id']}.wav",
                "category": "speech" if row["sample_kind"] == "speech"
                            else "vocalization_candidate",
                "set": row["sample_kind"],
                "transcript": row["subtitle"] if row["sample_kind"] == "speech" else "",
                "duration_s": row["duration_s"],
                "condition": row["line_type"],
                "character": row["character"],
                "length_bucket": row["length_bucket"],
                "effect_heavy": row["effect_heavy"],
            }
            for row in sample_rows
        ],
    }
    truth_json = json.dumps(ground_truth, ensure_ascii=False, indent=2)
    (OUT / "ground_truth.json").write_text(truth_json, encoding="utf-8")
    (OUT / "audio16k" / "ground_truth.json").write_text(truth_json, encoding="utf-8")

    counts = Counter(r["line_type"] for r in mapped)
    print(json.dumps({
        "audio_count": len(records), "mapped_to_subtitle": len(mapped),
        "speech_sample": len(selected), "non_speech_candidates": len(candidates),
        "non_speech_sample": len(nonspeech), "sample_characters": len(char_counts),
        "sample_line_types": dict(type_counts), "all_mapped_line_types": dict(counts),
        "speech_character_count": len(char_counts),
        "speech_top_characters": dict(char_counts.most_common(10)),
        "speech_by_length": dict(Counter(r["length_bucket"] for r in selected)),
        "mapped_by_length": dict(Counter(r["length_bucket"] for r in mapped)),
        "non_speech_by_type": dict(Counter(r["vocalization_type"] for r in nonspeech)),
        "non_speech_by_line_type": dict(Counter(r["line_type"] for r in nonspeech)),
        "non_speech_distinct_assets": len({r["folder"] for r in nonspeech}),
        "sample_audio_format": "16 kHz mono float32 IEEE WAV",
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
