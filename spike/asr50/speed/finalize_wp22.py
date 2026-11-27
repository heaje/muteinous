"""Assemble the WP22 report from final checkpoints and recorded telemetry."""
import contextlib
import io
import json
import re
import statistics
from datetime import datetime, timezone
from pathlib import Path

from report_tables import main as render_tables

BASE = Path(r"C:\scratch\asr50")
OUT = BASE / "WP22"
REPORT = BASE / "reports" / "WP22.md"


def rows(stem):
    path = OUT / f"{stem}.jsonl"
    result = []
    if path.is_file():
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            try:
                result.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return result


def token_words(text):
    return re.findall(r"[a-z0-9]+(?:'[a-z0-9]+)*", (text or "").casefold())


def drift_report():
    first = [r for r in rows("turbo-vulkan-t12-direct-python")
             if r.get("status") == "ok" and r.get("wall_seconds") is not None]
    last = [r for r in rows("turbo-vulkan-t12-drift-clean-python")
            if r.get("status") == "ok" and r.get("wall_seconds") is not None]
    by_a, by_b = {}, {}
    for r in first:
        by_a.setdefault(r["clip_id"], []).append(r)
    for r in last:
        by_b.setdefault(r["clip_id"], []).append(r)
    pairs, texts = [], []
    for cid in by_a.keys() & by_b.keys():
        a = statistics.median(r["wall_seconds"] for r in by_a[cid])
        b = statistics.median(r["wall_seconds"] for r in by_b[cid])
        pairs.append((a, b))
        ta = statistics.mode(tuple(token_words(r.get("text"))) for r in by_a[cid])
        tb = statistics.mode(tuple(token_words(r.get("text"))) for r in by_b[cid])
        texts.append(ta == tb)
    deltas = [(b-a)/a*100 for a, b in pairs if a]
    return (f"- Compared full clean Turbo/Vulkan/12 runs across {len(pairs)} clips "
            f"({len(first)} first-pass rows, {len(last)} drift rows).\n"
            f"- Median per-clip latency change: "
            f"{statistics.median(deltas):+.2f}% (positive is slower); "
            f"{sum(not x for x in texts)} transcript disagreements across paired clips.")


def main():
    # The first preflight was later overwritten by the explicit clean rerun;
    # retain its timestamp from the original WP22 checkpoint.
    start = datetime(2026, 11, 27, 6, 12, 26, 159513, tzinfo=timezone.utc)
    end = datetime.now(timezone.utc)
    elapsed = str(end - start).split(".")[0] if start else "unavailable"
    tables = io.StringIO()
    with contextlib.redirect_stdout(tables):
        render_tables()
    report = f"""# WP22 — ASR speed benchmark

- Date: 2026-11-27.
- Initial estimate: **8–14 hours**. Wall elapsed from the first Turbo/Vulkan/12 preflight through report generation: **{elapsed}**.
- Environment: Windows 11 Pro build 26300; Ryzen 9 9900X (12 physical/24 logical cores); Radeon RX 7900 XT, driver 32.0.32029.2010; 31.6 GB RAM; Balanced power plan, AC connected; Vulkan 1.4.359. No system settings were changed.

## Scope and method

- Frozen clips: 8 short (`v3_clean_001_0`–`v3_clean_008_0`), 4 medium (`natural_18s_00`, `natural_25s_00`, `natural_18s_01`, `natural_25s_01`), and 2 long (`natural_sentences_00`, `natural_sentences_01`).
- Short/medium: 5 repeats per clip. Long: **3 repeats per clip** on every configuration to bound long-clip runtime. Thus 66 expected observations per config (40 short, 20 medium, 6 long).
- whisper.cpp uses `whisper_cli_driver.py`: direct `subprocess.run`, argv lists, per-clip 600-second hard timeout, `time.perf_counter`, stderr timing parsing, immediate JSONL flush. Libraries use per-run child-process timeouts and immediate checkpoints; each run loads/warm-ups then times inference in-process.
- Every timed configuration had a separate 3-second idle gate: CPU <5%, RX 7900 XT 3D/Compute <0.1%, retrying up to 60 seconds; preflight readings and process inventory are in its `*-preflight.json`.
- **No GPU counters were sampled during timed inference.** GPU/process telemetry was collected in separate, untimed long-clip passes. The sampler ran BelowNormal at ≤1 Hz with a 20-second no-progress watchdog. Adapter-wide RX engine values are reported separately from PID-matched values; absent PID matches are not imputed. CLI CPU/RSS comes from an untimed representative pass; library CPU/RSS is from each timed worker.
- CLI wall latency includes process/model startup; internal model-load time is listed separately. Library latency is steady-state after model load and a warm-up, so these timings have different inclusion boundaries.
- `text_matches_reference` and prior approved baseline agreements are recorded per observation. VAD and alignment are operation timings, not ASR transcript comparisons.

## Configuration completion and per-class results

{tables.getvalue()}

## Drift check

{drift_report()}

## Failed attempts retained and corrections

- The initial Turbo/Vulkan/12 PowerShell controller stalled after one short clip during wildcard GPU-counter sampling (outer timeout 600 s); its wall/CPU/memory data are excluded.
- The initial Turbo/CPU/12 legacy run stalled during synchronous counter polling (outer timeout 3600 s); its latency is excluded. A later Turbo/Vulkan/12 wrapper rerun yielded one valid counter-free observation, then its PowerShell controller stalled before completing the configuration (outer timeout 3600 s). Those attempts and their partial data remain in the original checkpoints.
- The first Python library matrix used WP10 for every runtime. ORT Turbo, Parakeet and VAD child runs failed because WP10 lacked `transformers`, `sherpa_onnx` and `soundfile`; ORT Small DirectML rows did not verify DML because WP10's ORT build exposed CPU only. All are retained as superseded attempts. Corrected full reruns used existing WP12/WP13/WP9/WP14 environments; the corrected ORT runs verified requested providers. Those corrected DML/CPU pairs were rerun alternating by thread count.
- The first PowerShell GPU telemetry helper failed on unsupported `Start-Process -PriorityClass`; an early Python sampler also started too late for short Vulkan runs. The final untimed sampler waits ready before launching its candidate. Initial failed telemetry files are retained and excluded.
- Turbo/CPU/4's interrupted PowerShell rows remain preserved but excluded; the full clean Python rerun is in `turbo-cpu-t4-clean-python.jsonl`.

## Limitations

- Peak RSS/CPU and GPU telemetry for whisper.cpp are representative separate long-clip passes, not per-repeat timed-process samples. Some Windows GPU counters expose adapter-wide values but no PID-specific instance; those PID values remain unavailable. Dedicated GPU memory is reported only where its counter was returned.
- No pipeline-overhead measurement was made. GPU clock/thermal telemetry was not captured. No timed data from the stalled or superseded attempts is included in class statistics.

## Summary (under 300 words)

The final table reports actual per-run coverage for every planned config and the full clean Turbo/Vulkan/12 drift rerun. There are 66 expected observations per config; long clips use 3 repeats, with short and medium at 5. Timed CLI measurements use a standalone Python driver, and library configurations use per-run child timeouts, provider verification, and flushed JSONL checkpoints. No GPU counters overlap timed inference.

Initial controller failures, missing-runtime child failures, and unverified ORT DirectML attempts are retained but excluded from the results. The corrected library runtimes completed their full clips/repeats. CLI process and GPU telemetry are explicitly marked as separate untimed passes; missing PID-specific or dedicated-memory counters are left unavailable rather than estimated.
"""
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(report, encoding="utf-8")
    print(f"Wrote {REPORT} ({len(report):,} chars); elapsed={elapsed}")


if __name__ == "__main__":
    main()
