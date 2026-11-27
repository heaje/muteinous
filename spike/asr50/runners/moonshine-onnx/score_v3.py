import argparse, hashlib, importlib.util, json, pathlib, platform
ROOT=pathlib.Path(r"C:\code\muteinous-spike50\spike\asr50")
sp=importlib.util.spec_from_file_location("score",ROOT/"benchmark"/"score.py")
sc=importlib.util.module_from_spec(sp); sp.loader.exec_module(sc)
GT=pathlib.Path(r"C:\scratch\asr50\corpus_v3_frozen\ground_truth_v3.json")
MAN=pathlib.Path(r"C:\scratch\asr50\WP18\corpus_v3_vadmasked\manifest.json")
ART=pathlib.Path(r"C:\scratch\asr50\models\moonshine-base-onnx-int8")
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def calculate(clips, hyps, include_records=False):
    speech=[]; silence=[]; target=[0,0,0]; per={}
    for c in clips:
        cid=c["clip_id"]; h=hyps[cid]; ref=sc.tokenize(c["transcript"]); ht=sc.tokenize(h)
        ec=sc.edit_counts(ref,ht); tm=sc.target_metrics(c["transcript"],h)
        for k,v in zip(("true_positives","false_positives","false_negatives"),tm.values()):
            if k in tm: target[("true_positives","false_positives","false_negatives").index(k)]+=v
        per[cid]={"S":ec["substitutions"],"D":ec["deletions"],"I":ec["insertions"],"ref_words":len(ref),"wer":ec["wer"],"target":tm}
        if ref: speech.append((c,ec,ref,ht))
        if not ref: silence.append({"duration_s":c["duration_s"],"hypothesis":h})
    refn=sum(len(x[2]) for x in speech); s=sum(x[1]["substitutions"] for x in speech); d=sum(x[1]["deletions"] for x in speech); i=sum(x[1]["insertions"] for x in speech)
    tp,fp,fn=target; prec=tp/(tp+fp) if tp+fp else (1.0 if not fn else 0.0); rec=tp/(tp+fn) if tp+fn else (1.0 if not fp else 0.0)
    return {"speech_clip_count":len(speech),"speech_reference_words":refn,"speech_wer":(s+d+i)/refn if refn else None,"S":s,"D":d,"I":i,"target":{"true_positives":tp,"false_positives":fp,"false_negatives":fn,"recall":rec,"precision":prec,"f1":2*prec*rec/(prec+rec) if prec+rec else 0.0},"non_speech_hallucination":sc.hallucination_metrics(silence),"per_clip":per}
def main():
    p=argparse.ArgumentParser(); p.add_argument("--out-dir",required=True); p.add_argument("--mode",choices=["raw","masked"],required=True); a=p.parse_args()
    out=pathlib.Path(a.out_dir); gt=json.loads(GT.read_text(encoding="utf-8")); clips=gt["clips"]
    vm={}
    if a.mode=="masked":
        manifest=json.loads(MAN.read_text(encoding="utf-8")); vm={x["input"]:x for x in manifest["clips"]}
    raw={}; hyps={}
    for c in clips:
        rpath=out/(c["clip_id"]+".json"); r=json.loads(rpath.read_text(encoding="utf-8"))
        c["gate_no_speech"]=vm[c["wav"]]["gate_no_speech"] if a.mode=="masked" else None
        r["gate_no_speech"]=c["gate_no_speech"]; rpath.write_text(json.dumps(r,ensure_ascii=False,indent=2),encoding="utf-8")
        raw[c["clip_id"]]=r; hyps[c["clip_id"]]=r["text"]
    overall=calculate(clips,hyps)
    by_condition={}
    for condition in sorted({x["condition"] for x in clips}):
        subset=[x for x in clips if x["condition"]==condition]
        m=calculate(subset,hyps)
        by_condition[condition]={k:m[k] for k in ("speech_clip_count","speech_reference_words","speech_wer","S","D","I","target","non_speech_hallucination")}
    by_voice={}; by_rate={}
    for key,dest in (("voice",by_voice),("rate",by_rate)):
        for value in sorted({str(x[key]) for x in clips if x[key] is not None}):
            subset=[x for x in clips if str(x[key])==value and sc.tokenize(x["transcript"])]
            m=calculate(subset,hyps)
            dest[value]={k:m[k] for k in ("speech_clip_count","speech_reference_words","speech_wer","S","D","I")}
    model_files=[x for x in ART.rglob("*") if x.is_file()]; model_bytes=sum(x.stat().st_size for x in model_files)
    model_hash=hashlib.sha256("".join(sha(x) for x in sorted(model_files)).encode()).hexdigest()
    records=[]
    for c in clips:
        r=raw[c["clip_id"]]; m=overall["per_clip"][c["clip_id"]]; input_name=c["wav"]
        input_path=(pathlib.Path(r"C:\scratch\asr50\corpus_v3_frozen")/input_name) if a.mode=="raw" else (pathlib.Path(r"C:\scratch\asr50\WP18\corpus_v3_vadmasked")/vm[input_name]["output"])
        records.append({"schema_version":1,"candidate":"moonshine-base-onnx-int8-v3-"+a.mode,"clip_id":c["clip_id"],"clip_set":c.get("set"),"category":c["category"],"condition":c["condition"],"run":{"kind":"v3-"+a.mode,"index":0,"process_id":None},"hardware":{"cpu":platform.processor(),"gpu":None,"ram_bytes":None,"os":platform.platform(),"driver":None},"device":{"requested":"cpu","actual":r["meta"]["actual_providers"]},"runtime":{"name":"onnxruntime","version":r["meta"]["version"],"package_version":r["meta"]["version"],"installed_bytes":None},"model":{"artifact_id":"moonshine-base-onnx-int8","sha256":model_hash,"bytes":model_bytes,"cache_bytes":0},"settings":{"language":"en","sample_rate_hz":16000,"channels":1,"threads":4,"decoding":{"method":"greedy","chunking":r["meta"]["chunking"],"chunk_seconds":r["meta"]["chunk_seconds"],"chunk_count":r["meta"]["chunk_count"],"token_caps":r["meta"]["chunk_token_caps"]},"voice":c["voice"],"rate":c["rate"],"volume":c["volume"],"snr_db":c["snr_db"]},"input":{"sample_rate_hz":16000,"channels":1,"dtype":"float32","clip_sha256":sha(input_path)},"measurements":{"audio_duration_s":r["meta"]["audio_seconds"],"runtime_s":None,"rtf":None,"peak_ram_bytes":None,"peak_vram_bytes":None,"peak_vram_method":"not measured","model_footprint_bytes":model_bytes},"hypothesis":{"text":r["text"],"words":[]},"gate_no_speech":c["gate_no_speech"],"metrics":{"wer":m["wer"],"substitutions":m["S"],"deletions":m["D"],"insertions":m["I"],"target":m["target"],"timing":{"missing_alignment_words":len(sc.tokenize(r["text"])),"missing_alignment_rate":1.0 if sc.tokenize(r["text"]) else 0.0}}})
    (out/"results.jsonl").write_text("".join(json.dumps(x,ensure_ascii=False)+"\n" for x in records),encoding="utf-8")
    summary={k:v for k,v in overall.items() if k!="per_clip"}; summary.update({"clip_count":len(clips),"mode":a.mode,"by_condition":by_condition,"by_voice":by_voice,"by_rate":by_rate})
    (out/"score-summary.json").write_text(json.dumps(summary,indent=2),encoding="utf-8")
    if a.mode=="masked":
        gated={cid:("" if raw[cid]["gate_no_speech"] else raw[cid]["text"]) for cid in raw}
        gate_score=calculate(clips,gated)
        gate_result={"mode":"VAD skip applied to masked-run hypotheses","gated_count":sum(bool(r["gate_no_speech"]) for r in raw.values()),"gated_speech_count":sum(bool(raw[c["clip_id"]]["gate_no_speech"]) for c in clips if sc.tokenize(c["transcript"])),"gate_passed_non_speech_count":sum(not raw[c["clip_id"]]["gate_no_speech"] for c in clips if not sc.tokenize(c["transcript"])),"metrics":{k:v for k,v in gate_score.items() if k!="per_clip"}}
        (out.parent/"gated-skip-summary.json").write_text(json.dumps(gate_result,indent=2),encoding="utf-8")
        (out.parent/"gated-skip-results.jsonl").write_text("".join(json.dumps({"clip_id":cid,"condition":next(c["condition"] for c in clips if c["clip_id"]==cid),"gate_no_speech":raw[cid]["gate_no_speech"],"text_before_skip":raw[cid]["text"],"gated_text":gated[cid]},ensure_ascii=False)+"\n" for cid in raw),encoding="utf-8")
        print(json.dumps(gate_result,indent=2))
    print(json.dumps({k:v for k,v in summary.items() if k not in ("by_condition","by_voice","by_rate")},indent=2))
if __name__=="__main__": main()
