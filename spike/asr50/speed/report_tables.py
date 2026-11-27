"""Render checkpoint-derived WP22 completion and per-class statistics tables."""
import json
import math
from collections import Counter
from pathlib import Path

BASE = Path(r"C:\scratch\asr50\WP22")
CLIPS = {"short": 40, "medium": 20, "long": 6}
PLANNED = [
    ("turbo-vulkan-t12", "turbo-vulkan-t12-direct-python"),
    ("turbo-cpu-t12", "turbo-cpu-t12"),
    ("turbo-vulkan-t4", "turbo-vulkan-t4"),
    ("turbo-cpu-t4", "turbo-cpu-t4-clean-python"),
    ("small-en-vulkan-t12", "small-en-vulkan-t12"),
    ("small-en-cpu-t12", "small-en-cpu-t12"),
    ("small-en-vulkan-t4", "small-en-vulkan-t4"),
    ("small-en-cpu-t4", "small-en-cpu-t4"),
    ("ort-turbo-dml-t12-b5", "ort-turbo-dml-t12-b5-corrected-runtime"),
    ("ort-turbo-cpu-t12-b5", "ort-turbo-cpu-t12-b5-corrected-runtime"),
    ("ort-turbo-dml-t4-b5", "ort-turbo-dml-t4-b5-corrected-runtime"),
    ("ort-turbo-cpu-t4-b5", "ort-turbo-cpu-t4-b5-corrected-runtime"),
    ("ort-small-dml-t12-b5", "ort-small-dml-t12-b5-corrected-runtime"),
    ("ort-small-cpu-t12-b5", "ort-small-cpu-t12-b5-corrected-runtime"),
    ("ort-small-dml-t4-b5", "ort-small-dml-t4-b5-corrected-runtime"),
    ("ort-small-cpu-t4-b5", "ort-small-cpu-t4-b5-corrected-runtime"),
    ("parakeet-cpu-t12-b5", "parakeet-cpu-t12-b5-corrected-runtime"),
    ("parakeet-cpu-t4-b5", "parakeet-cpu-t4-b5-corrected-runtime"),
    ("faster-cpu-t12-b1", "faster-cpu-t12-b1"),
    ("faster-cpu-t4-b1", "faster-cpu-t4-b1"),
    ("faster-cpu-t12-b5", "faster-cpu-t12-b5"),
    ("faster-cpu-t4-b5", "faster-cpu-t4-b5"),
    ("moonshine-cpu-t12-b5", "moonshine-cpu-t12-b5"),
    ("moonshine-cpu-t4-b5", "moonshine-cpu-t4-b5"),
    ("vad-cpu-t12-b5", "vad-cpu-t12-b5-corrected-runtime"),
    ("vad-cpu-t4-b5", "vad-cpu-t4-b5-corrected-runtime"),
    ("aligner-cpu-t12-b5", "aligner-cpu-t12-b5"),
    ("aligner-cpu-t4-b5", "aligner-cpu-t4-b5"),
    ("turbo-vulkan-t12-drift", "turbo-vulkan-t12-drift-clean-python"),
]


def read_rows(stem):
    p = BASE / f"{stem}.jsonl"
    if not p.is_file():
        return []
    rows = []
    for line in p.read_text(encoding="utf-8-sig").splitlines():
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def quantile(values, pct):
    if not values:
        return None
    values = sorted(values)
    return values[max(0, math.ceil(pct * len(values)) - 1)]


def number(v, digits=3):
    return "—" if v is None else f"{v:.{digits}f}"


def pid_dedicated_peak(telemetry):
    value = telemetry.get("dedicated_gpu_pid_bytes_peak")
    if value is not None:
        return value
    counter = telemetry.get("counter_file")
    if not counter or not Path(counter).is_file():
        return None
    values = []
    for line in Path(counter).read_text(encoding="utf-8-sig", errors="replace").splitlines():
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if (row.get("counter_set") == "GPU Process Memory" and row.get("pid_matched")
                and isinstance(row.get("value"), (int, float))):
            values.append(row["value"])
    return max(values) if values else None


def fmt_coverage(rows):
    def valid_for_results(r):
        if r.get("status") not in ("ok", "partial_valid_timing") or r.get("wall_seconds") is None:
            return False
        if r.get("kind") in ("ort-turbo", "ort-small"):
            return r.get("provider_verified") is True
        return True
    valid = [r for r in rows if valid_for_results(r)]
    failures = [r for r in rows if not valid_for_results(r)]
    found = {k: sum(1 for r in valid if r.get("class", r.get("clip_class")) == k)
             for k in CLIPS}
    classes_complete = all(found[k] >= CLIPS[k] for k in CLIPS)
    state = "complete" if classes_complete else "partial"
    if classes_complete and failures:
        state = "complete (failed attempts retained)"
    return valid, failures, found, state


def main():
    print("## Planned configuration completion")
    print("| Configuration | State | Valid / 66 | Errors/timeouts | Short | Medium | Long |")
    print("|---|---:|---:|---:|---:|---:|---:|")
    loaded = {}
    for label, stem in PLANNED:
        rows = read_rows(stem)
        valid, failures, found, state = fmt_coverage(rows)
        loaded[label] = (stem, rows, valid, failures)
        print(f"| `{label}` | {state} | {len(valid)}/66 | {len(failures)} | "
              f"{found['short']}/40 | {found['medium']}/20 | {found['long']}/6 |")
    print("\n## Latency and resource results")
    print("| Configuration | Class | n | Latency median / p95 (s) | RTF aggregate | Speed × | Load median (s) | CPU cores / % logical* | Peak RSS* (MB) | GPU adapter / PID peak* (%) | GPU dedicated adapter / PID* (MB) | Ref mismatches | Baseline disagreements |")
    print("|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    for label, (stem, rows, valid, _) in loaded.items():
        telemetry_path = BASE / f"{stem}-gpu-sample-python" / "metadata.json"
        if not telemetry_path.exists():
            telemetry_path = BASE / f"{stem}-system-sample-python" / "metadata.json"
        if not telemetry_path.exists():
            telemetry_path = BASE / f"{label}-gpu-sample-python" / "metadata.json"
        if not telemetry_path.exists():
            telemetry_path = BASE / f"{label}-system-sample-python" / "metadata.json"
        telemetry = {}
        if telemetry_path.is_file():
            try:
                telemetry = json.loads(telemetry_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                pass
        pid_mem_peak = pid_dedicated_peak(telemetry)
        for klass in ("short", "medium", "long"):
            group = [r for r in valid if r.get("class", r.get("clip_class")) == klass]
            if not group:
                print(f"| `{label}` | {klass} | 0 | — | — | — | — | — | — | — | — | — | — |")
                continue
            latency = [float(r["wall_seconds"]) for r in group]
            durations = [float(r.get("audio_seconds") or 0) for r in group]
            if not any(durations):
                durations = [float(r.get("duration_s") or 0) for r in group]
            total_audio = sum(durations)
            rtf = sum(latency) / total_audio if total_audio else None
            loads, cores, rss = [], [], []
            mismatches = 0
            baseline_disagreements = 0
            for r in group:
                load = r.get("model_load_s")
                if load is None:
                    load = (r.get("internal") or {}).get("load_time_ms")
                    if load is None:
                        load = (r.get("internal") or {}).get("load_ms")
                    if load is None:
                        load = (r.get("internal_ms") or {}).get("load")
                    if load is not None:
                        load = float(load) / 1000
                if load is not None:
                    loads.append(float(load))
                if r.get("cores_used") is not None:
                    cores.append(float(r["cores_used"]))
                if r.get("peak_working_set_bytes") is not None:
                    rss.append(float(r["peak_working_set_bytes"]) / (1024 * 1024))
                if r.get("text_matches_reference") is False:
                    mismatches += 1
                if r.get("matches_accuracy_baseline_words") is False:
                    baseline_disagreements += 1
            avg_cores = sum(cores)/len(cores) if cores else telemetry.get("process_cores_used")
            avg_percent = (100 * avg_cores / 24 if avg_cores is not None else
                           telemetry.get("process_cpu_percent_of_logical"))
            print(f"| `{label}` | {klass} | {len(group)} | "
                  f"{number(quantile(latency,.5))} / {number(quantile(latency,.95))} | "
                  f"{number(rtf,4)} | {number(1/rtf if rtf else None,2)} | "
                  f"{number(quantile(loads,.5))} | "
                  f"{number(avg_cores)} / {number(avg_percent,1)} | "
                  f"{number(max(rss) if rss else (telemetry.get('peak_working_set_bytes') or 0)/(1024*1024),1)} | "
                  f"{number(telemetry.get('gpu_3d_compute_peak_percent'))} / "
                  f"{number(telemetry.get('gpu_pid_3d_compute_peak_percent'))} | "
                  f"{number(telemetry.get('dedicated_gpu_bytes_peak')/(1024*1024) if telemetry.get('dedicated_gpu_bytes_peak') is not None else None,1)} / "
                  f"{number(pid_mem_peak/(1024*1024) if pid_mem_peak is not None else None,1)} | "
                  f"{mismatches} | {baseline_disagreements} |")
    print("\n## Failed or incomplete records")
    for label, (stem, rows, valid, failures) in loaded.items():
        causes = Counter()
        for row in failures:
            detail = row.get("error") or row.get("note") or ""
            if row.get("status") in ("incomplete_monitor_timeout", "incomplete_monitor_timeout_contaminated"):
                detail = "Legacy synchronous counter monitor stalled; timed latency excluded; outer timeout 600/3600s (exit 143)"
            if not detail and row.get("kind") in ("ort-turbo", "ort-small"):
                detail = ("superseded: requested execution provider was not recorded/verified"
                          if row.get("provider_verified") is not True else "")
            if isinstance(detail, str):
                detail = detail.splitlines()[-1][:180]
            causes[(row.get("status"), detail)] += 1
        for (status, detail), count in causes.items():
            print(f"- `{label}`: {count} `{status}` record(s); {detail}")


if __name__ == "__main__":
    main()
