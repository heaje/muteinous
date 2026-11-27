import argparse, hashlib, importlib.util, json, pathlib, platform, re
ROOT=pathlib.Path(r"C:\code\muteinous-spike50\spike\asr50")
sp=importlib.util.spec_from_file_location("sc",ROOT/"benchmark"/"score.py")
sc=importlib.util.module_from_spec(sp); sp.loader.exec_module(sc)
CORPUS=pathlib.Path(r"C:\scratch\asr50\WP18\corpus_v2_vadmasked")
UNMASKED=pathlib.Path(r"C:\scratch\asr50\results_v2\moonshine-onnx\cpu")
def evaluate(refs, hyps):
    speech=[]; sil=[]; targets=[0,0,0]
    for cid,c in refs.items():
        h=hyps[cid]; toks=sc.tokenize(c["transcript"])
        m=sc.edit_counts(toks,sc.tokenize(h))
        if toks: speech.append((cid,c,m,toks,h))
        if c["category"] in ("silence","non_speech"): sil.append({"duration_s":c["duration_s"],"hypothesis":h})
        tm=sc.target_metrics(c["transcript"],h)
        targets[0]+=tm["true_positives"]; targets[1]+=tm["false_positives"]; targets[2]+=tm["false_negatives"]
    n=sum(len(x[3]) for x in speech); errors=sum(x[2]["substitutions"]+x[2]["deletions"]+x[2]["insertions"] for x in speech)
    tp,fp,fn=targets; precision=tp/(tp+fp) if tp+fp else (1.0 if not fn else 0.0); recall=tp/(tp+fn) if tp+fn else (1.0 if not fp else 0.0)
    return {"speech_clip_count":len(speech),"speech_wer":errors/n if n else None,"speech_errors":errors,"speech_reference_words":n,"speech_substitutions":sum(x[2]["substitutions"] for x in speech),"speech_deletions":sum(x[2]["deletions"] for x in speech),"speech_insertions":sum(x[2]["insertions"] for x in speech),"target":{"true_positives":tp,"false_positives":fp,"false_negatives":fn,"precision":precision,"recall":recall},"silence_non_speech_hallucination":sc.hallucination_metrics(sil)}
def main():
    p=argparse.ArgumentParser(); p.add_argument("--raw",required=True); a=p.parse_args()
    gt=json.loads((CORPUS/"ground_truth_v2.json").read_text(encoding="utf-8")); refs={c["clip_id"]:c for c in gt["clips"]}
    man=json.loads((CORPUS/"manifest.json").read_text(encoding="utf-8")); flags={x["clip_id"]:x for x in man["clips"]}
    raw=pathlib.Path(a.raw); masked={}; unmasked={}
    for cid in refs:
        f=raw/(cid+".json"); r=json.loads(f.read_text(encoding="utf-8")); masked[cid]=r["text"]
        r["gate_no_speech"]=flags[cid]["gate_no_speech"]; r["meta"]["clip_set"]=refs[cid]["set"]
        f.write_text(json.dumps(r,ensure_ascii=False,indent=2),encoding="utf-8")
        u=json.loads((UNMASKED/(cid+".json")).read_text(encoding="utf-8")); unmasked[cid]=u["text"]
    gated={cid:("" if flags[cid]["gate_no_speech"] else unmasked[cid]) for cid in refs}
    masked_summary=evaluate(refs,masked); unmasked_summary=evaluate(refs,unmasked); gated_summary=evaluate(refs,gated)
    recs=[]
    for cid,c in refs.items():
        r=json.loads((raw/(cid+".json")).read_text(encoding="utf-8"))
        toks=sc.tokenize(c["transcript"]); m=sc.edit_counts(toks,sc.tokenize(masked[cid]))
        recs.append({"schema_version":1,"candidate":"moonshine-base-onnx-int8-vadmasked-v2","clip_id":cid,"clip_set":c["set"],"category":c["category"],"run":{"kind":"masked-all-clips","index":0,"process_id":None},"hardware":{"cpu":platform.processor(),"gpu":None,"ram_bytes":None,"os":platform.platform(),"driver":None},"device":{"requested":"cpu","actual":r["meta"]["actual_providers"]},"runtime":{"name":"onnxruntime","version":r["meta"]["version"],"package_version":r["meta"]["version"],"installed_bytes":None},"model":{"artifact_id":"moonshine-base-onnx-int8","sha256":None,"bytes":None,"cache_bytes":0},"settings":{"language":"en","sample_rate_hz":16000,"channels":1,"threads":4,"decoding":{"method":"greedy","chunking":r["meta"]["chunking"],"chunk_seconds":r["meta"]["chunk_seconds"],"chunk_count":r["meta"]["chunk_count"],"token_caps":r["meta"]["chunk_token_caps"]}},"input":{"sample_rate_hz":16000,"channels":1,"dtype":"float32","clip_sha256":r["meta"]["clip_sha256"]},"measurements":{"audio_duration_s":r["meta"]["audio_seconds"],"runtime_s":None,"rtf":None,"peak_ram_bytes":None,"peak_vram_bytes":None,"peak_vram_method":"not measured","model_footprint_bytes":None},"hypothesis":{"text":masked[cid],"words":[]},"gate_no_speech":flags[cid]["gate_no_speech"],"vad_segments":flags[cid]["segments"],"metrics":{"wer":m["wer"],"substitutions":m["substitutions"],"deletions":m["deletions"],"insertions":m["insertions"],"target":sc.target_metrics(c["transcript"],masked[cid]),"timing":{"missing_alignment_words":len(sc.tokenize(masked[cid])),"missing_alignment_rate":1.0 if sc.tokenize(masked[cid]) else 0.0}}})
    (raw/"results.jsonl").write_text("".join(json.dumps(x,ensure_ascii=False)+"\n" for x in recs),encoding="utf-8")
    summaries={"masked_all_clips":masked_summary,"unmasked_v2_cpu":unmasked_summary,"gated_skip_on_unmasked_v2_cpu":gated_summary,"gated_count":sum(x["gate_no_speech"] for x in flags.values()),"false_speech_skip":{"clip_id":"timing_noise_pink_-5_01","reference":refs["timing_noise_pink_-5_01"]["transcript"],"unmasked_hypothesis":unmasked["timing_noise_pink_-5_01"],"gated_hypothesis":"","edit_counts":sc.edit_counts(sc.tokenize(refs["timing_noise_pink_-5_01"]["transcript"]),[])}}
    (raw/"score-summary.json").write_text(json.dumps(masked_summary,indent=2),encoding="utf-8")
    (raw.parent/"vadmasked-comparison.json").write_text(json.dumps(summaries,indent=2),encoding="utf-8")
    (raw.parent/"gated-skip-results.jsonl").write_text("".join(json.dumps({"clip_id":cid,"clip_set":refs[cid]["set"],"category":refs[cid]["category"],"gate_no_speech":flags[cid]["gate_no_speech"],"unmasked_text":unmasked[cid],"gated_text":gated[cid]},ensure_ascii=False)+"\n" for cid in refs),encoding="utf-8")
    # Error-focused sample for diagnosing where v2 errors originate.
    rows=[]; group={}
    for cid,c in refs.items():
        m=sc.edit_counts(sc.tokenize(c["transcript"]),sc.tokenize(unmasked[cid]))
        nch=(len(__import__("pathlib").Path(UNMASKED/(cid+".json")).read_text(encoding="utf-8")) and json.loads((UNMASKED/(cid+".json")).read_text(encoding="utf-8"))["meta"]["chunk_count"])
        hyp=sc.tokenize(unmasked[cid]); repeated=any(hyp[i]==hyp[i+1] for i in range(len(hyp)-1))
        repeated_phrase=any(hyp[i:i+n]==hyp[j:j+n] for n in range(2,5) for i in range(len(hyp)-2*n+1) for j in range(i+n,len(hyp)-n+1))
        row={"clip_id":cid,"clip_set":c["set"],"category":c["category"],"duration_s":c["duration_s"],"reference":c["transcript"],"hypothesis":unmasked[cid],"wer":m["wer"],"substitutions":m["substitutions"],"deletions":m["deletions"],"insertions":m["insertions"],"chunk_count":nch,"chunk_boundary_candidate":nch>1,"consecutive_repetition":repeated,"repeated_phrase":repeated_phrase,"isolated_word":len(sc.tokenize(c["transcript"]))==1}
        rows.append(row)
        key="chunked_long" if nch>1 else ("isolated_word" if row["isolated_word"] else ("timing_other" if c["set"]=="timing" else "natural_unchunked"))
        z=group.setdefault(key,{"clips":0,"speech_clips":0,"errors":0,"reference_words":0,"subs":0,"dels":0,"ins":0})
        z["clips"]+=1
        if sc.tokenize(c["transcript"]):
            z["speech_clips"]+=1; z["errors"]+=m["substitutions"]+m["deletions"]+m["insertions"]; z["reference_words"]+=len(sc.tokenize(c["transcript"])); z["subs"]+=m["substitutions"];z["dels"]+=m["deletions"];z["ins"]+=m["insertions"]
    rows.sort(key=lambda x:(-(x["wer"] if x["wer"] is not None else 0),-(x["substitutions"]+x["deletions"]+x["insertions"])))
    (raw.parent/"unmasked-v2-worst-clips.json").write_text(json.dumps(rows[:15],indent=2,ensure_ascii=False),encoding="utf-8")
    (raw.parent/"unmasked-v2-error-diagnosis.json").write_text(json.dumps({"groups":group,"repetition_clip_ids":[x["clip_id"] for x in rows if x["repeated_phrase"] or x["consecutive_repetition"]],"isolated_word_clip_ids":[x["clip_id"] for x in rows if x["isolated_word"]],"chunked_clip_ids":[x["clip_id"] for x in rows if x["chunk_boundary_candidate"]]},indent=2,ensure_ascii=False),encoding="utf-8")
    print(json.dumps(summaries,indent=2)); print("worst",json.dumps(rows[:8],ensure_ascii=False,indent=2))
if __name__=="__main__": main()
