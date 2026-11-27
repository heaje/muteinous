import argparse, json, pathlib, sys, time, hashlib, os
import numpy as np
from runpy import run_path

base=pathlib.Path(__file__).parent
ns=run_path(str(base/"run.py"))

def delta(a,b):
    a=np.asarray(a,dtype=np.float32); b=np.asarray(b,dtype=np.float32)
    diff=np.abs(a-b)
    denom=float(np.linalg.norm(a.ravel())*np.linalg.norm(b.ravel()))
    return {"shape":list(a.shape),"max_abs_diff":float(diff.max(initial=0)),"mean_abs_diff":float(diff.mean()),"cosine_similarity":float(np.dot(a.ravel(),b.ravel())/denom) if denom else None}

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--device",choices=["cpu","dml"],required=True)
    p.add_argument("--out",required=True)
    p.add_argument("--audio",default=r"C:\scratch\asr50\corpus_v2_frozen")
    p.add_argument("--sets",default="all")
    p.add_argument("--clip-id")
    p.add_argument("--threads",type=int,default=4)
    p.add_argument("--diagnostic",action="store_true")
    a=p.parse_args()
    if hasattr(sys.stdout,"reconfigure"): sys.stdout.reconfigure(errors="backslashreplace")
    out=pathlib.Path(a.out); out.mkdir(parents=True,exist_ok=True)
    gt=json.loads((pathlib.Path(a.audio)/"ground_truth_v2.json").read_text(encoding="utf-8"))
    selected=[c for c in gt["clips"] if a.sets=="all" or c["set"] in a.sets.split(",")]
    if a.clip_id: selected=[c for c in selected if c["clip_id"]==a.clip_id]
    tok=ns["Tokenizer"].from_file(str(ns["ART"]/"tokenizer.json"))
    class Args: pass
    cfg=Args(); cfg.threads=a.threads; cfg.out=str(out); cfg.device=a.device; cfg.device_id=0; cfg.disable_fallback=False
    enc=ns["session"](ns["ENC"],cfg,True); dec=ns["session"](ns["DEC"],cfg,True); past=ns["session"](ns["PAST"],cfg,True)
    print("providers",enc.get_providers(),dec.get_providers(),past.get_providers())
    diagnosis=None
    for c in selected:
        path=pathlib.Path(a.audio)/c["wav"]; audio=ns["wavread"](path)
        chunk_n=20*16000
        chunks=[audio[i:i+chunk_n] for i in range(0,len(audio),chunk_n)] if len(audio)>30*16000 else [audio]
        texts=[]; generated=[]; caphit=False
        for chunk in chunks:
            limit=min(512,max(1,int(len(chunk)/16000*6+8)))
            text,n,hit=ns["infer"](chunk,enc,dec,past,tok,limit)
            texts.append(text.strip()); generated.append(n); caphit |= hit
        full=" ".join(t for t in texts if t)
        obj={"text":full,"words":[],"clip_set":c["set"],"meta":{"runtime":"onnxruntime","version":ns["ort"].__version__,"artifact":"moonshine-base-onnx-int8","requested_device":a.device,"actual_providers":{"encoder":enc.get_providers(),"decoder":dec.get_providers(),"past":past.get_providers()},"actual_device_verified_by":"InferenceSession.get_providers and per-node ORT profile","threads":a.threads,"sample_rate_hz":16000,"chunk_seconds":20 if len(chunks)>1 else None,"chunk_count":len(chunks),"chunking":"fixed non-overlapping 20-second windows; concatenate text with spaces" if len(chunks)>1 else "none","chunk_token_caps":[min(512,max(1,int(len(q)/16000*6+8))) for q in chunks],"generated_tokens":generated,"token_cap_hit":caphit,"word_timestamps":"unavailable: text-only HF ONNX export","clip_set":c["set"],"audio_seconds":len(audio)/16000,"clip_sha256":hashlib.sha256(path.read_bytes()).hexdigest()}}
        (out/(c["clip_id"]+".json")).write_text(json.dumps(obj,ensure_ascii=False,indent=2),encoding="utf-8")
        print(c["clip_id"],repr(full),flush=True)
        if a.diagnostic and diagnosis is None:
            # Reuse this clip's first chunk; compare encoder outputs on both
            # providers, then compare decoder logits with identical CPU encoder
            # hidden states and identical zero-cache first-step feeds.
            x=chunks[0]
            cpuenc=ns["ort"].InferenceSession(str(ns["ENC"]),providers=["CPUExecutionProvider"])
            cpudec=ns["ort"].InferenceSession(str(ns["DEC"]),providers=["CPUExecutionProvider"])
            hc=cpuenc.run(None,{"input_values":x[None,:]})[0]
            hd=enc.run(None,{"input_values":x[None,:]})[0]
            cache={n.name:np.zeros((1,8,0,52),dtype=np.float32) for n in dec.get_inputs() if n.name.startswith("past_key_values.")}
            def first_logits(sess,h):
                feed={"input_ids":np.array([[1]],dtype=np.int64),"encoder_hidden_states":h,"use_cache_branch":np.array([False],dtype=np.bool_)}; feed.update(cache)
                outs=sess.run(None,feed)
                return {v.name:x for v,x in zip(sess.get_outputs(),outs)}
            oc=first_logits(cpudec,hc); od_same=first_logits(dec,hc)
            oc_same=first_logits(cpudec,hd); od=first_logits(dec,hd)
            lc,ld=oc["logits"],od["logits"]
            next_id=int(np.argmax(lc[0,-1]))
            def second(sess,hidden,first):
                pasts={k.replace("present.","past_key_values."):v for k,v in first.items() if k.startswith("present.")}
                f={"input_ids":np.array([[next_id]],dtype=np.int64),"encoder_hidden_states":hidden,"use_cache_branch":np.array([True],dtype=np.bool_)}; f.update(pasts)
                return sess.run(["logits"],f)[0]
            sc=second(cpudec,hc,oc); sd=second(dec,hd,od)
            def trace(sess,h):
                ca={k:np.zeros((1,8,0,52),dtype=np.float32) for k in cache}
                trace_rows=[]; token=1; first=True
                for step in range(8):
                    f={"input_ids":np.array([[token]],dtype=np.int64),"encoder_hidden_states":h,"use_cache_branch":np.array([not first],dtype=np.bool_)}; f.update(ca)
                    os_=sess.run(None,f); vals={v.name:x for v,x in zip(sess.get_outputs(),os_)}
                    logits=vals["logits"]; top=int(np.argmax(logits[0,-1]))
                    trace_rows.append({"step":step,"input_token_id":token,"top1_id":top,"logits":logits,"logits_nan_count":int(np.isnan(logits).sum()),"logits_inf_count":int(np.isinf(logits).sum()),"present":vals})
                    for k,v in vals.items():
                        if k.startswith("present.") and (".decoder." in k or (first and ".encoder." in k)): ca[k.replace("present.","past_key_values.")]=v
                    token=top; first=False
                return trace_rows
            tc=trace(cpudec,hc); td=trace(dec,hd)
            stepwise=[]
            for u,v in zip(tc,td):
                stepwise.append({"step":u["step"],"cpu_top1_id":u["top1_id"],"dml_top1_id":v["top1_id"],"cpu_nan_logits":u["logits_nan_count"],"dml_nan_logits":v["logits_nan_count"],"same_top1":u["top1_id"]==v["top1_id"],"logits_cpu_vs_dml":delta(u["logits"],v["logits"])})
                if u["top1_id"]!=v["top1_id"]: break
            diagnosis={"clip_id":c["clip_id"],"encoder_cpu_vs_dml":delta(hc,hd),"decoder_first_step_logits_cpu_vs_dml_same_cpu_encoder_input":{**delta(oc["logits"],od_same["logits"]),"cpu_top1_id":int(np.argmax(oc["logits"][0,-1])),"dml_top1_id":int(np.argmax(od_same["logits"][0,-1]))},"decoder_first_step_logits_cpu_vs_dml_same_dml_encoder_input":{**delta(oc_same["logits"],od["logits"]),"cpu_top1_id":int(np.argmax(oc_same["logits"][0,-1])),"dml_top1_id":int(np.argmax(od["logits"][0,-1]))},"first_step_logits_cpu_route_vs_dml_route":{**delta(lc,ld),"cpu_top1_id":int(np.argmax(lc[0,-1])),"dml_top1_id":int(np.argmax(ld[0,-1]))},"second_decoder_step_logits_cpu_vs_dml_separate_provider_caches_same_next_token":{**delta(sc,sd),"cpu_top1_id":int(np.argmax(sc[0,-1])),"dml_top1_id":int(np.argmax(sd[0,-1]))},"greedy_cpu_vs_dml_stepwise":stepwise,"first_greedy_token_divergence_step":next((r["step"] for r in stepwise if not r["same_top1"]),None)}
            (out/"operator-diagnostic.json").write_text(json.dumps(diagnosis,indent=2),encoding="utf-8")
    for s in (enc,dec,past):
        try: print("profile",s.end_profiling(),flush=True)
        except Exception: pass
if __name__=="__main__": main()
