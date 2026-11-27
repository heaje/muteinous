"""Summarize WP22 JSONL checkpoints; failed/incomplete runs are excluded."""
import json
import math
import sys
from collections import defaultdict
from pathlib import Path

BASE = Path(r"C:\scratch\asr50\WP22")
DURATIONS = {
    "v3_clean_001_0": 3.4238125,
    "v3_clean_002_0": 4.6688125,
    "v3_clean_003_0": 2.6889375,
    "v3_clean_004_0": 3.6640625,
    "v3_clean_005_0": 4.784,
    "v3_clean_006_0": 5.3790625,
    "v3_clean_007_0": 3.3140625,
    "v3_clean_008_0": 2.2841875,
    "natural_18s_00": 17.8914375,
    "natural_25s_00": 25.3350625,
    "natural_18s_01": 17.9063125,
    "natural_25s_01": 25.505125,
    "natural_sentences_00": 103.486125,
    "natural_sentences_01": 104.83125,
}


def percentile(values, p):
    values = sorted(values)
    if not values:
        return None
    return values[max(0, math.ceil(p * len(values)) - 1)]


def summarize(path):
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8-sig").splitlines() if line.strip()]
    groups = defaultdict(list)
    for row in rows:
        if row.get("status") in ("ok", "partial_valid_timing") and row.get("wall_seconds") is not None:
            group = row.get("class", row.get("clip_class"))
            if group:
                groups[group].append(row)
    output = {"checkpoint": str(path), "config": rows[0].get("config") if rows else path.stem,
              "records": len(rows), "valid_records": sum(map(len, groups.values())),
              "classes": {}}
    for name, group in groups.items():
        walls = [float(row["wall_seconds"]) for row in group]
        durations = [DURATIONS[row["clip_id"]] for row in group]
        rtfs = [w / d for w, d in zip(walls, durations)]
        total_wall = sum(walls)
        total_audio = sum(durations)
        cpu = [row["cores_used"] for row in group if row.get("cores_used") is not None]
        loads_by_pid = {}
        warmups_by_clip = {}
        for row in group:
            pid = row.get("pid", row.get("process_id", row.get("repeat")))
            load = row.get("model_load_s")
            if load is None:
                internal = row.get("internal") or {}
                load = internal.get("load_time_ms", internal.get("load_ms"))
                if load is None:
                    load = (row.get("internal_ms") or {}).get("load")
                if load is not None:
                    load = float(load) / 1000
            if load is not None:
                loads_by_pid[pid] = float(load)
            warm = row.get("warmup_seconds")
            if warm is None:
                warm = row.get("warmup_seconds")
            if warm is not None:
                warmups_by_clip[(pid, row["clip_id"])] = float(warm)
        output["classes"][name] = {
            "n": len(group),
            "latency_median_s": percentile(walls, 0.5),
            "latency_p95_s": percentile(walls, 0.95),
            "rtf_median": percentile(rtfs, 0.5),
            "rtf_p95": percentile(rtfs, 0.95),
            "aggregate_rtf": total_wall / total_audio if total_audio else None,
            "speed_multiple": total_audio / total_wall if total_wall else None,
            "mean_cores_used": sum(cpu) / len(cpu) if cpu else None,
            "model_load_median_s": percentile(list(loads_by_pid.values()), 0.5),
            "model_load_p95_s": percentile(list(loads_by_pid.values()), 0.95),
            "first_inference_median_s": percentile(list(warmups_by_clip.values()), 0.5),
            "first_inference_p95_s": percentile(list(warmups_by_clip.values()), 0.95),
            "transcript_mismatches": sum(not row.get("text_matches_reference", False) for row in group),
            "working_set_peak_bytes": max((row.get("peak_working_set_bytes") or 0) for row in group) or None,
        }
    return output


def main():
    paths = [Path(arg) for arg in sys.argv[1:]] or sorted(BASE.glob("*.jsonl"))
    results = [summarize(path) for path in paths if path.is_file()]
    dest = BASE / "summary.json"
    dest.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(dest)
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
