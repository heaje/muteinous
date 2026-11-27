"""Functional whisper.cpp inference for raw and WP18-masked corpus v3."""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path

import benchmark_v2 as base

ROOT = base.ROOT
RAW_CORPUS = ROOT / "corpus_v3_frozen"
MASKED_CORPUS = ROOT / "WP18" / "corpus_v3_vadmasked"
OUT = ROOT / "results_v3" / "whispercpp"
LOG = ROOT / "WP8" / "logs" / "v3"
GT_PATH = RAW_CORPUS / "ground_truth_v3.json"
MANIFEST_PATH = MASKED_CORPUS / "manifest.json"


def file_sha256(path: Path) -> str:
    return base.sha256(path)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    LOG.mkdir(parents=True, exist_ok=True)
    gt = json.loads(GT_PATH.read_text(encoding="utf-8"))
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    clips = gt["clips"]
    if len(clips) != 380 or len(manifest["clips"]) != 380:
        raise SystemExit("expected 380 clips in both v3 ground truth and VAD manifest")
    if gt["sample_rate_hz"] != 16000 or gt["channels"] != 1 or gt["dtype"] != "float32":
        raise SystemExit("unexpected corpus-v3 audio format")
    if len({c["clip_id"] for c in clips}) != 380:
        raise SystemExit("duplicate v3 clip IDs")

    # The WP18 manifest is keyed by input filename, not clip ID.
    mask_by_input = {e["input"]: e for e in manifest["clips"]}
    if len(mask_by_input) != 380:
        raise SystemExit("duplicate or missing input names in v3 VAD manifest")
    if sum(bool(e["gate_no_speech"]) for e in manifest["clips"]) != 40:
        raise SystemExit("expected all 40 non-speech clips and no speech clips to be gated")

    media = {}
    for clip in clips:
        raw = RAW_CORPUS / clip["wav"]
        entry = mask_by_input.get(clip["wav"])
        if entry is None:
            raise SystemExit(f"no VAD manifest entry for {clip['wav']}")
        masked = MASKED_CORPUS / entry["output"]
        if not raw.is_file() or file_sha256(raw) != clip["sha256"]:
            raise SystemExit(f"raw v3 WAV missing or hash mismatch: {raw}")
        if not masked.is_file() or file_sha256(masked) != entry["sha256"]:
            raise SystemExit(f"masked v3 WAV missing or hash mismatch: {masked}")
        expected_duration = entry["samples"] / gt["sample_rate_hz"]
        if (expected_duration != base.wav_duration(raw)
                or expected_duration != base.wav_duration(masked)):
            raise SystemExit(f"raw/masked sample count changed for {clip['clip_id']}")
        if entry["gate_no_speech"] != (not bool(clip["transcript"])):
            raise SystemExit(f"gate flag does not match stated v3 speech/non-speech design: {clip['clip_id']}")
        media[clip["clip_id"]] = {"raw": raw, "masked": masked, "mask": entry}

    for model in base.MODELS.values():
        if file_sha256(model["path"]) != model["sha256"]:
            raise SystemExit(f"approved model hash mismatch: {model['path']}")

    observations = []
    jobs = [(corpus_name, model_key, device, clip)
            for corpus_name in ("raw", "masked")
            for model_key in base.MODELS
            for device in base.DEVICES
            for clip in clips]
    for index, (corpus_name, model_key, device, clip) in enumerate(jobs, 1):
        model = base.MODELS[model_key]
        item = media[clip["clip_id"]]
        wav = item[corpus_name]
        gate = bool(item["mask"]["gate_no_speech"])
        config = f"{model_key}-{device}-full"
        tag = f"{corpus_name}-{config}-{clip['clip_id']}"
        outbase = LOG / tag
        log_path = LOG / f"{tag}.log"
        cmd = [str(base.BIN[device]), "-m", str(model["path"]), "-f", str(wav),
               "-l", "en", "-t", "12", "-ojf", "-of", str(outbase)]
        cmd += ["-dev", "0"] if device == "vulkan" else ["-ng"]
        env = os.environ.copy()
        env.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1",
                   HF_HUB_DISABLE_TELEMETRY="1")
        proc = subprocess.Popen(cmd, env=env, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, text=True, errors="replace")
        pid = proc.pid
        log, _ = proc.communicate()
        log_path.write_text(log, encoding="utf-8")
        json_path = Path(str(outbase) + ".json")
        if proc.returncode != 0 or not json_path.is_file():
            raise RuntimeError(f"whisper-cli failed ({proc.returncode}) for {tag}; {log_path}")
        if device == "vulkan" and "using Vulkan0 backend" not in log:
            raise RuntimeError(f"Vulkan0 not confirmed for {tag}; {log_path}")
        if device == "cpu" and "using Vulkan0 backend" in log:
            raise RuntimeError(f"unexpected Vulkan backend in CPU run {tag}; {log_path}")
        doc = json.loads(json_path.read_text(encoding="utf-8"))
        text, words = base.merge_tokens(doc)
        actual = "vulkan0" if "using Vulkan0 backend" in log else "cpu"
        config_dir = OUT / corpus_name / config
        config_dir.mkdir(parents=True, exist_ok=True)
        normalized = {
            "text": text,
            "words": [{"word": w["text"], "start": w["start_s"], "end": w["end_s"]}
                      for w in words],
            "gate_no_speech": gate,
            "corpus": corpus_name,
            "meta": {
                "runtime": "whisper.cpp", "version": "1.9.6-dev",
                "model_artifact": model["slug"], "model_sha256": model["sha256"],
                "requested_device": device, "actual_device": actual,
                "actual_device_verified_by": ("`using Vulkan0 backend` log line"
                                              if actual == "vulkan0"
                                              else "CPU DLL and `CPU total size` log"),
                "settings": {"language": "en", "threads": 12, "mode": "full",
                             "decoding": {"full_json": True}},
                "process_id": pid, "exit_code": proc.returncode,
                "process_peak_working_set_bytes": None,
                "peak_dedicated_gpu_bytes": None,
            },
        }
        (config_dir / f"{clip['clip_id']}.json").write_text(
            json.dumps(normalized, ensure_ascii=False, indent=2), encoding="utf-8")
        duration = float(clip["duration_s"])
        record = {
            "schema_version": 1,
            "candidate": f"whispercpp-v3-{corpus_name}-{model_key}-full",
            "corpus": corpus_name,
            "clip_id": clip["clip_id"],
            "category": clip["category"],
            "condition": clip["condition"],
            "voice": clip["voice"],
            "rate": clip["rate"],
            "volume": clip["volume"],
            "snr_db": clip["snr_db"],
            "gate_no_speech": gate,
            "run": {"kind": "functional", "process_id": pid, "exit_code": proc.returncode},
            "device": {"requested": device, "actual": actual},
            "model": {"artifact_id": model["slug"], "sha256": model["sha256"],
                      "bytes": model["path"].stat().st_size},
            "input": {"wav": str(wav),
                      "sha256": clip["sha256"] if corpus_name == "raw" else item["mask"]["sha256"],
                      "sample_rate_hz": gt["sample_rate_hz"],
                      "channels": gt["channels"], "dtype": gt["dtype"]},
            "settings": {"language": "en", "threads": 12, "mode": "full"},
            "measurements": {"audio_duration_s": duration, "runtime_s": None,
                             "rtf": None, "peak_ram_bytes": None, "peak_vram_bytes": None},
            "hypothesis": {"text": text,
                           "words": [{"text": w["text"], "start_s": w["start_s"],
                                      "end_s": w["end_s"]} for w in words]},
            "metrics": {"log": str(log_path)},
        }
        observations.append(record)
        if index % 50 == 0:
            print(f"completed {index}/{len(jobs)} v3 functional runs", flush=True)

    (OUT / "results.jsonl").write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in observations),
        encoding="utf-8")
    print(f"Wrote {len(observations)} v3 observations under {OUT}")


if __name__ == "__main__":
    main()
