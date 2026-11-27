import argparse, hashlib, importlib.util, json, pathlib, platform, os
ROOT=pathlib.Path(r"C:\code\muteinous-spike50\spike\asr50")
spec=importlib.util.spec_from_file_location("score",ROOT/"benchmark"/"score.py")
score=importlib.util.module_from_spec(spec); spec.loader.exec_module(score)
CORPUS=pathlib.Path(r"C:\scratch\asr50\corpus_v2_frozen")
ART=pathlib.Path(r"C:\scratch\asr50\models\moonshine-base-onnx-int8")
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
    p=argparse.ArgumentParser(); p.add_argument("--device-dir",required=True); p.add_argument("--device",required=True); p.add_argument("--threads",type=int,default=4)
    a=p.parse_args(); raw=pathlib.Path(a.device_dir); gt=json.loads((CORPUS/"ground_truth_v2.json").read_text(encoding="utf-8"))
    refs={c["clip_id"]:c for c in gt["clips"]}; files={x.name:x for x in ART.rglob("*") if x.is_file()}
    modelbytes=sum(x.stat().st_size for x in files.values()); modelsha=hashlib.sha256("".join(sha(files[k]) for k in sorted(files)).encode()).hexdigest()
    records=[]; speech=[]; sil=[]; target_counts={"true_positives":0,"false_positives":0,"false_negatives":0}
    for f in sorted(raw.glob("*.json")):
        if f.stem.startswith("profile-") or f.stem in ("operator-diagnostic","score-summary"): continue
        r=json.loads(f.read_text(encoding="utf-8")); c=refs[f.stem]; hyp=r["text"]; ref=c["transcript"]
        tokens_r=score.tokenize(ref); tokens_h=score.tokenize(hyp)
        counts=score.edit_counts(tokens_r,tokens_h); target=score.target_metrics(ref,hyp)
        for k in target_counts: target_counts[k]+=target[k]
        rec={"schema_version":1,"candidate":"moonshine-base-onnx-int8","clip_id":c["clip_id"],"clip_set":c["set"],"category":c["category"],"run":{"kind":"corpus-v2","index":0,"process_id":None},"hardware":{"cpu":platform.processor(),"gpu":"AMD Radeon RX 7900 XT" if a.device=="dml" else None,"ram_bytes":int(__import__("psutil").virtual_memory().total),"os":platform.platform(),"driver":"32.0.32029.2010" if a.device=="dml" else None},"device":{"requested":a.device,"actual":r["meta"]["actual_providers"]},"runtime":{"name":"onnxruntime","version":r["meta"]["version"],"package_version":r["meta"]["version"],"installed_bytes":None},"model":{"artifact_id":"moonshine-base-onnx-int8","sha256":modelsha,"bytes":modelbytes,"cache_bytes":0},"settings":{"language":"en","sample_rate_hz":16000,"channels":1,"threads":a.threads,"decoding":{"method":"greedy","chunk_seconds":r["meta"]["chunk_seconds"],"chunk_count":r["meta"]["chunk_count"],"chunking":r["meta"]["chunking"],"token_caps":r["meta"]["chunk_token_caps"],"generated_tokens":r["meta"]["generated_tokens"],"token_cap_hit":r["meta"]["token_cap_hit"]}},"input":{"sample_rate_hz":16000,"channels":1,"dtype":"float32","clip_sha256":r["meta"]["clip_sha256"]},"measurements":{"audio_duration_s":r["meta"]["audio_seconds"],"runtime_s":None,"rtf":None,"peak_ram_bytes":None,"peak_vram_bytes":None,"peak_vram_method":"not measured in corpus-v2 phase","model_footprint_bytes":modelbytes},"hypothesis":{"text":hyp,"words":[]},"metrics":{"wer":counts["wer"],"substitutions":counts["substitutions"],"deletions":counts["deletions"],"insertions":counts["insertions"],"target":target,"timing":{"missing_alignment_words":len(tokens_h),"missing_alignment_rate":1.0 if tokens_h else 0.0}}}
        (raw/(f.stem+".json")).write_text(json.dumps({**r,"clip_set":c["set"]},ensure_ascii=False,indent=2),encoding="utf-8")
        records.append(rec)
        if tokens_r: speech.append((c,counts,tokens_r,tokens_h))
        if c["category"] in ("silence","non_speech"): sil.append({"duration_s":c["duration_s"],"hypothesis":hyp})
    speech_refs=sum(len(x[2]) for x in speech); errors=sum(x[1]["substitutions"]+x[1]["deletions"]+x[1]["insertions"] for x in speech)
    tp,fp,fn=(target_counts[k] for k in ("true_positives","false_positives","false_negatives"))
    precision=tp/(tp+fp) if tp+fp else (1.0 if not fn else 0.0); recall=tp/(tp+fn) if tp+fn else (1.0 if not fp else 0.0)
    summary={"clip_count":len(records),"sets":dict((s,sum(r["clip_set"]==s for r in records)) for s in ("timing","natural")),"speech_clip_count":len(speech),"speech_wer":errors/speech_refs if speech_refs else None,"speech_errors":errors,"speech_reference_words":speech_refs,"target":{**target_counts,"precision":precision,"recall":recall,"f1":2*precision*recall/(precision+recall) if precision+recall else 0.0},"silence_non_speech_hallucination":score.hallucination_metrics(sil),"missing_native_alignment_words":sum(len(score.tokenize(r["hypothesis"]["text"])) for r in records)}
    (raw/"results.jsonl").write_text("".join(json.dumps(x,ensure_ascii=False)+"\n" for x in records),encoding="utf-8")
    (raw/"score-summary.json").write_text(json.dumps(summary,indent=2),encoding="utf-8")
    print(json.dumps(summary,indent=2))
    if a.device=="dml" and (raw.parent/"cpu").is_dir():
        cpu={x.stem:json.loads(x.read_text(encoding="utf-8")) for x in (raw.parent/"cpu").glob("*.json") if not x.stem.startswith("profile-") and x.stem not in ("operator-diagnostic","score-summary")}
        comps=[]; buckets={}; cats={}
        for cid,dr in sorted({x.stem:json.loads(x.read_text(encoding="utf-8")) for x in raw.glob("*.json") if not x.stem.startswith("profile-") and x.stem not in ("operator-diagnostic","score-summary")}.items()):
            cr=cpu[cid]; c=refs[cid]; dwer=score.edit_counts(score.tokenize(c["transcript"]),score.tokenize(dr["text"]))["wer"]; cwer=score.edit_counts(score.tokenize(c["transcript"]),score.tokenize(cr["text"]))["wer"]
            row={"clip_id":cid,"clip_set":c["set"],"category":c["category"],"duration_s":c["duration_s"],"cpu_wer":cwer,"dml_wer":dwer,"dml_minus_cpu_wer":dwer-cwer,"same_text":dr["text"]==cr["text"],"cpu_text":cr["text"],"dml_text":dr["text"]}
            comps.append(row); cats.setdefault(c["category"],[]).append(dwer)
            b="<1.5s" if c["duration_s"]<1.5 else ("1.5-3s" if c["duration_s"]<=3 else ">3s"); buckets.setdefault(b,[]).append(dwer)
        def agg(v): return {"clips":len(v),"mean_dml_wer":sum(v)/len(v)}
        cpu_errors=sum(score.edit_counts(score.tokenize(refs[x["clip_id"]]["transcript"]),score.tokenize(x["cpu_text"]))["substitutions"]+score.edit_counts(score.tokenize(refs[x["clip_id"]]["transcript"]),score.tokenize(x["cpu_text"]))["deletions"]+score.edit_counts(score.tokenize(refs[x["clip_id"]]["transcript"]),score.tokenize(x["cpu_text"]))["insertions"] for x in comps)
        dml_errors=sum(score.edit_counts(score.tokenize(refs[x["clip_id"]]["transcript"]),score.tokenize(x["dml_text"]))["substitutions"]+score.edit_counts(score.tokenize(refs[x["clip_id"]]["transcript"]),score.tokenize(x["dml_text"]))["deletions"]+score.edit_counts(score.tokenize(refs[x["clip_id"]]["transcript"]),score.tokenize(x["dml_text"]))["insertions"] for x in comps)
        total_ref=sum(len(score.tokenize(refs[x["clip_id"]]["transcript"])) for x in comps)
        compare={"clips":len(comps),"cpu_corpus_wer":cpu_errors/total_ref,"dml_corpus_wer":dml_errors/total_ref,"same_text_count":sum(x["same_text"] for x in comps),"unique_dml_transcripts":len(set(x["dml_text"] for x in comps)),"duration_buckets":{k:agg(v) for k,v in buckets.items()},"category_mean_dml_wer":{k:agg(v) for k,v in cats.items()},"interpretation":"Use per-clip and grouped WERs to distinguish constant output, length trend and content variation."}
        (raw.parent/"dml-vs-cpu.jsonl").write_text("".join(json.dumps(x,ensure_ascii=False)+"\n" for x in comps),encoding="utf-8")
        (raw.parent/"dml-vs-cpu-summary.json").write_text(json.dumps(compare,indent=2),encoding="utf-8")
if __name__=="__main__": main()
