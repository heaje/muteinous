import argparse, hashlib, importlib.util, json, pathlib, platform, sys, os
ROOT=pathlib.Path(r"C:\code\muteinous-spike50\spike\asr50")
spec=importlib.util.spec_from_file_location("score",ROOT/"benchmark"/"score.py")
score=importlib.util.module_from_spec(spec); spec.loader.exec_module(score)
GT=pathlib.Path(r"C:\scratch\asr50\WP6\audio16k\ground_truth.json")
ART=pathlib.Path(r"C:\scratch\asr50\models\moonshine-base-onnx-int8")

def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()
def main():
    p=argparse.ArgumentParser(); p.add_argument("--raw",required=True); p.add_argument("--device",required=True); p.add_argument("--threads",type=int,default=4); p.add_argument("--kind",default="warm"); p.add_argument("--index",type=int,default=1)
    a=p.parse_args(); raw=pathlib.Path(a.raw); gt=json.loads(GT.read_text(encoding="utf-8"))
    refs={c["clip_id"]:c for c in gt["clips"]}
    files={x.name:x for x in list(ART.rglob("*")) if x.is_file()}
    bytes_model=sum(x.stat().st_size for x in files.values())
    model_hash=hashlib.sha256("".join(sha(files[k]) for k in sorted(files)).encode()).hexdigest()
    records=[]; silence=[]
    for f in sorted(raw.glob("*.json")):
        if f.stem.startswith("profile-") or f.stem == "score-summary": continue
        r=json.loads(f.read_text(encoding="utf-8")); cid=f.stem; c=refs[cid]
        hyp=r["text"]; mets=score.edit_counts(score.tokenize(c["transcript"]),score.tokenize(hyp))
        tm=score.timing_metrics(c["words"],[])
        targets=score.target_metrics(c["transcript"],hyp)
        if c["category"] in ("silence","non_speech"): silence.append({"duration_s":c["duration_s"],"hypothesis":hyp})
        d=r["meta"]; wav=pathlib.Path(r"C:\scratch\asr50\WP6\audio16k")/c["wav"]
        rec={"schema_version":1,"candidate":"moonshine-base-onnx-int8","clip_id":cid,"category":c["category"],"run":{"kind":a.kind,"index":a.index,"process_id":d.get("process_id")},"hardware":{"cpu":platform.processor(),"gpu":"AMD Radeon RX 7900 XT" if a.device=="dml" else None,"ram_bytes":int(__import__("psutil").virtual_memory().total),"os":platform.platform(),"driver":"32.0.32029.2010" if a.device=="dml" else None},"device":{"requested":a.device,"actual":d["actual_providers"]},"runtime":{"name":"onnxruntime","version":d["version"],"package_version":d["version"],"installed_bytes":None},"model":{"artifact_id":"moonshine-base-onnx-int8","sha256":model_hash,"bytes":bytes_model,"cache_bytes":0},"settings":{"language":"en","sample_rate_hz":16000,"channels":1,"threads":a.threads,"decoding":{"method":"greedy","max_new_tokens":d["max_new_tokens"],"generated_tokens":d["generated_tokens"],"token_cap_hit":d["token_cap_hit"]}},"input":{"sample_rate_hz":16000,"channels":1,"dtype":"float32","clip_sha256":sha(wav)},"measurements":{"audio_duration_s":d["audio_seconds"],"runtime_s":d["wall_seconds"],"rtf":d["rtf"],"peak_ram_bytes":d["peak_process_working_set_bytes"],"peak_vram_bytes":None,"peak_vram_method":"not available per process","model_footprint_bytes":bytes_model},"hypothesis":{"text":hyp,"words":[]},"metrics":{"wer":mets["wer"],"substitutions":mets["substitutions"],"deletions":mets["deletions"],"insertions":mets["insertions"],"target":targets,"timing":tm}}
        records.append(rec)
    (raw/"results.jsonl").write_text("".join(json.dumps(x,ensure_ascii=False)+"\n" for x in records),encoding="utf-8")
    ref_count=sum(len(score.tokenize(c["transcript"])) for c in gt["clips"])
    errs=sum(x["metrics"]["substitutions"]+x["metrics"]["deletions"]+x["metrics"]["insertions"] for x in records)
    summary={"clip_count":len(records),"wer":errs/ref_count if ref_count else None,"errors":errs,"reference_words":ref_count,"target":score.target_metrics([w for c in gt["clips"] for w in score.tokenize(c["transcript"])],[w for x in records for w in score.tokenize(x["hypothesis"]["text"])]),"timing":{"missing_alignment_words":sum(len(score.tokenize(x["hypothesis"]["text"])) for x in records),"missing_alignment_rate":1.0},"hallucination":score.hallucination_metrics(silence),"mean_rtf":sum(x["measurements"]["rtf"] for x in records)/len(records)}
    (raw/"score-summary.json").write_text(json.dumps(summary,indent=2),encoding="utf-8")
    print(json.dumps(summary,indent=2))
if __name__=="__main__": main()
