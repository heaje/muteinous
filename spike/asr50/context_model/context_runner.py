"""Standalone WP23 Phi context evaluator; imports only prompt data from Hushpatch."""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import statistics
import sys
import time
from pathlib import Path

sys.dont_write_bytecode = True
os.environ.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1",
                  HF_HUB_DISABLE_TELEMETRY="1")
import numpy as np
import onnxruntime_genai as og
import psutil
ROOT = Path(r"C:\scratch\asr50\WP23")
MODELS = Path(r"C:\scratch\asr50\models\phi4mini")
PROMPT_SOURCE = Path(r"C:\code\hushpatch\src\muteinous\inference\context.py")
spec = importlib.util.spec_from_file_location("reference_prompt_data", PROMPT_SOURCE)
prompt_data = importlib.util.module_from_spec(spec)
assert spec and spec.loader
sys.modules[spec.name] = prompt_data
spec.loader.exec_module(prompt_data)

def load_model(device: str):
    model_dir = MODELS / ("phi-4-mini-instruct-cpu-int4" if device == "cpu"
                         else "phi-4-mini-instruct-gpu-int4")
    cfg = og.Config(str(model_dir))
    if device == "gpu":
        cfg.clear_providers()
        cfg.append_provider("dml")
    started = time.perf_counter()
    model = og.Model(cfg)
    tokenizer = og.Tokenizer(model)
    return model, tokenizer, time.perf_counter() - started

def infer(model, tokenizer, text, word, category):
    prompt = tokenizer.encode(prompt_data.prompt(text, word, category))
    params = og.GeneratorParams(model)
    params.set_search_options(max_length=len(prompt) + 1, do_sample=False)
    gen = og.Generator(model, params)
    gen.append_tokens(prompt)
    logits = np.asarray(gen.get_logits()).reshape(-1)
    yes, no = int(tokenizer.encode("Yes")[0]), int(tokenizer.encode("No")[0])
    pair = np.asarray([logits[yes], logits[no]], dtype=np.float64)
    p_yes = float(np.exp(pair[0] - np.logaddexp(pair[0], pair[1])))
    del gen, params
    return p_yes >= 0.5, p_yes

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--device", choices=("cpu", "gpu"), default="cpu")
    ap.add_argument("--input", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()
    model, tokenizer, load_s = load_model(args.device)
    rows = json.loads(args.input.read_text(encoding="utf-8"))
    results = []
    timings = []
    for row in rows:
        t = time.perf_counter()
        pred, p_yes = infer(model, tokenizer, row["sentence"], row["target_word"], row["category"])
        elapsed = time.perf_counter() - t
        timings.append(elapsed)
        results.append({**row, "pred": int(pred), "p_yes": p_yes, "latency_s": elapsed})
    args.output.parent.mkdir(parents=True, exist_ok=True)
    peak_working_set = psutil.Process().memory_info().peak_wset
    args.output.write_text(json.dumps({"device": args.device, "load_s": load_s,
        "runtime_version": getattr(og, "__version__", "unreported"),
        "peak_working_set_bytes": peak_working_set,
        "median_s": statistics.median(timings),
        "p95_s": sorted(timings)[int(0.95 * (len(timings)-1))],
        "results": results}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"{args.device}: loaded in {load_s:.3f}s; n={len(rows)} "
          f"median={statistics.median(timings):.3f}s")

if __name__ == "__main__":
    main()
