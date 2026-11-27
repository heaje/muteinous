"""Run Hushpatch's real context decision composition over scratch-labeled WP23 cases."""
from __future__ import annotations
import argparse, json, os, statistics, sys, time
from pathlib import Path

os.environ.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", HF_HUB_DISABLE_TELEMETRY="1")
HUSHPATCH = Path(r"C:\code\hushpatch")
sys.path.insert(0, str(HUSHPATCH / "src"))
from muteinous.adapters.ff7r import FF7R
from muteinous import games
from muteinous.application import context as application_context
from muteinous.inference import context as inference_context
from muteinous.inference import devices
from muteinous.wordlist import WordList
import psutil

def run_case(row, wordlist, keep_names, device):
    text = row["sentence"]
    start, end = int(row["start"]), int(row["end"])
    found = text[start:end]
    raw = inference_context.classify(text, found, row["category"], application_context.model_loader,
                                     speaker=row.get("speaker", ""), device=device)
    matches = [m for m in wordlist.find(text) if m.start < end and m.end > start]
    match = next((m for m in matches if m.word.category == row["category"]), matches[0] if matches else None)
    if match is None:
        pred, source, confidence = False, "not-in-wordlist", 1.0
        word_meta = None
    elif not match.word.ambiguous:
        pred, source, confidence = True, "wordlist-nonambiguous", 1.0
        word_meta = match.word
    else:
        decision = inference_context.decide(text, match.start, match.end, match.word.category,
                                            application_context.model_loader, row.get("speaker", ""),
                                            keep_names, wordlist.idioms, device, wordlist.innocent)
        pred, source, confidence = decision.censor, decision.source, decision.confidence
        word_meta = match.word
    return {
        **row,
        "raw_pred": int(raw.censor), "p_yes": raw.confidence if raw.censor else 1.0 - raw.confidence,
        "pipeline_pred": int(pred), "pipeline_source": source, "pipeline_confidence": confidence,
        "matched_word": (word_meta.text if word_meta else None),
        "matched_category": (word_meta.category if word_meta else None),
        "matched_ambiguous": (word_meta.ambiguous if word_meta else None),
        "matched_level": (word_meta.level if word_meta else None),
    }

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--device",choices=("cpu","gpu"),required=True)
    ap.add_argument("--input",type=Path,required=True)
    ap.add_argument("--output",type=Path,required=True)
    a=ap.parse_args()
    found=devices.list_devices()
    device=next(d for d in found if (d.kind=="gpu") == (a.device=="gpu"))
    wl=WordList.load("strict")
    keep_names=games.GAMES["ff7r"].keep_names
    rows=json.loads(a.input.read_text(encoding="utf-8"))
    load_start=time.perf_counter()
    application_context.model_loader(device)
    load_s=time.perf_counter()-load_start
    t0=time.perf_counter()
    results=[]
    timings=[]
    for row in rows:
        one=time.perf_counter()
        result=run_case(row,wl,keep_names,device)
        result["latency_s"]=time.perf_counter()-one
        timings.append(result["latency_s"])
        results.append(result)
    elapsed=time.perf_counter()-t0
    process=psutil.Process()
    peak_wset=process.memory_info().peak_wset
    a.output.parent.mkdir(parents=True,exist_ok=True)
    a.output.write_text(json.dumps({"device":a.device,"device_key":device.key,"pid":os.getpid(),"n":len(results),
        "runtime_version":__import__("onnxruntime_genai").__version__,"load_s":load_s,
        "elapsed_s":elapsed,"median_s":statistics.median(timings),
        "p95_s":sorted(timings)[int(.95*len(timings)+.999999)-1],
        "peak_working_set_bytes":peak_wset,"results":results},ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({"device":a.device,"device_key":device.key,"n":len(results),"load_s":load_s,
        "elapsed_s":elapsed,"median_s":statistics.median(timings),
        "sources":{s:sum(r["pipeline_source"]==s for r in results) for s in sorted({r["pipeline_source"] for r in results})}},ensure_ascii=False))
    application_context.release()
if __name__=="__main__": main()
