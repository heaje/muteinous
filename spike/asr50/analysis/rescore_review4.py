import json, pathlib, sys, collections, csv
sys.path.insert(0, r"C:\code\muteinous-spike50\spike\asr50\benchmark")
import score

ROOT = pathlib.Path(r"C:\scratch\asr50")
OUT = ROOT / "reviewer4"
OUT.mkdir(exist_ok=True)

def load(path):
    return json.loads(path.read_text(encoding="utf-8"))

def clips_from(path, key="clips"):
    x=load(path)
    return x[key] if isinstance(x,dict) else x

def compute(gt, files, gated=set()):
    S=D=I=N=tp=fp=fn=0
    negwords=negout=negdur=0
    per={}
    for c in gt:
        cid=c["clip_id"]
        if cid not in files: continue
        d=load(files[cid])
        text="" if cid in gated else d.get("text","")
        h=score.tokenize(text); ref=score.tokenize(c.get("transcript",""))
        if c.get("transcript","").strip():
            z=score.edit_counts(ref,h)
            S+=z["substitutions"]; D+=z["deletions"]; I+=z["insertions"]; N+=len(ref)
            per[cid]={"S":z["substitutions"],"D":z["deletions"],"I":z["insertions"],"N":len(ref),"errors":z["substitutions"]+z["deletions"]+z["insertions"]}
        t=score.target_metrics(c.get("transcript",""),text)
        tp+=t["true_positives"]; fp+=t["false_positives"]; fn+=t["false_negatives"]
        if not c.get("transcript","").strip():
            negwords+=len(h); negout+=bool(h); negdur+=float(c.get("duration_s",0))
    return {"n":len(files),"speech_n":sum(bool(c.get("transcript","").strip()) for c in gt if c["clip_id"] in files),
      "ref_words":N,"S":S,"D":D,"I":I,"WER":(S+D+I)/N if N else None,
      "TP":tp,"FP":fp,"FN":fn,"target_precision":tp/(tp+fp) if tp+fp else (1.0 if not fn else 0.0),
      "target_recall":tp/(tp+fn) if tp+fn else (1.0 if not fp else 0.0),
      "neg_words":negwords,"neg_clips_output":negout,"neg_clips":sum(not c.get("transcript","").strip() for c in gt if c["clip_id"] in files),
      "neg_wpm":negwords*60/negdur if negdur else 0,"per_clip":per}

def files_in(path):
    return {p.stem:p for p in path.glob("*.json") if p.name not in ("score-summary.json","scores.json")}

v2=clips_from(ROOT/"corpus_v2_frozen"/"ground_truth_v2.json")
v3=clips_from(ROOT/"corpus_v3_frozen"/"ground_truth_v3.json")
v2ids={c["clip_id"] for c in v2}; v3ids={c["clip_id"] for c in v3}
m2={x["clip_id"]:x["gate_no_speech"] for x in load(ROOT/"WP18"/"corpus_v2_vadmasked"/"manifest.json")["clips"]}
m3={pathlib.Path(x["input"]).stem:x["gate_no_speech"] for x in load(ROOT/"WP18"/"corpus_v3_vadmasked"/"manifest.json")["clips"]}
results={"v2":{},"v3":{},"incomplete_v3":[],"agreements":{}}
# V2 direct config layouts, skip helper gated-skip dirs.
for runner in ["whispercpp","sherpa-parakeet","faster-whisper","moonshine-onnx","ort-whisper-turbo","ort-whisper-small-en"]:
    base=ROOT/"results_v2_vadmasked"/runner
    for p in sorted(base.rglob("*.json")):
        if p.name in ("score-summary.json","scores.json","scoring_comparison.json","score-comparison.json","vadmasked-comparison.json"): continue
        # one clip directory is parent; config is parent for flat files, device for device layouts
        if p.stem not in {c["clip_id"] for c in v2}: continue
        rel=p.relative_to(base)
        if "gated-skip" in str(rel).lower(): continue
        config=str(rel.parent)
        # combined dimensions such as cpu are the actual available run group.
        files={k:v for k,v in files_in(p.parent).items() if k in v2ids}
        if len(files)<60: continue
        key=f"{runner}/{config}"
        if key not in results["v2"]:
            results["v2"][key]={"masked_run":compute(v2,files),"gated_skip":compute(v2,files,{k for k,val in m2.items() if val})}

# V3: detect leaf folders containing clip JSONs; restrict exact full 380.
for runner_dir in (ROOT/"results_v3").iterdir():
    if not runner_dir.is_dir(): continue
    runner=runner_dir.name
    for p in runner_dir.rglob("*.json"):
        pass
    for leaf in {x.parent for x in runner_dir.rglob("*.json")}:
        files=files_in(leaf)
        if not files or not any(c["clip_id"] in files for c in v3): continue
        # aggregates may sit in leaf; filter clip IDs
        files={k:v for k,v in files.items() if k in v3ids}
        if "gated-skip" in str(leaf).lower(): continue
        rel=leaf.relative_to(runner_dir)
        if len(files)!=380:
            results["incomplete_v3"].append({"runner":runner,"config":str(rel),"clips":len(files)})
            continue
        key=f"{runner}/{rel}"
        results["v3"][key]={"raw":compute(v3,files),"gated_skip":compute(v3,files,{k for k,val in m3.items() if val}) if "masked" in str(rel) else None,
                            "conditions":{}}
        for cond in sorted({c["condition"] for c in v3 if c.get("transcript","").strip()}):
            subset=[c for c in v3 if c.get("transcript","").strip() and c["condition"]==cond]
            # using full all clips impossible without preserving global metrics; condition scorer
            r=compute(subset,files)
            results["v3"][key]["conditions"][cond]={k:r[k] for k in ("speech_n","ref_words","S","D","I","WER")}
# CPU/device text agreement across raw/masked; pairs discovered by matching configs and device subfolders.
for runner in (ROOT/"results_v3").iterdir():
    if not runner.is_dir(): continue
    for view in ("raw","masked"):
        vdir=runner/view
        if not vdir.exists(): continue
        devices={d.name:{k:v for k,v in files_in(d).items() if k in v3ids} for d in vdir.iterdir() if d.is_dir() and d.name in ("cpu","dml","vulkan")}
        if "cpu" in devices and ("dml" in devices or "vulkan" in devices):
            other="dml" if "dml" in devices else "vulkan"
            ids=set(devices["cpu"])&set(devices[other])
            diff=[i for i in ids if load(devices["cpu"][i]).get("text","")!=load(devices[other][i]).get("text","")]
            results["agreements"][f"{runner.name}/{view}/cpu-vs-{other}"]={"compared":len(ids),"agree":len(ids)-len(diff),"different":diff}
(OUT/"scores.json").write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding="utf-8")
print("v2 configurations",len(results["v2"]),"v3 complete",len(results["v3"]),"incomplete",results["incomplete_v3"])
for k,v in results["v2"].items():
    print("V2",k,json.dumps({x:{a:b for a,b in y.items() if a!="per_clip"} for x,y in v.items()}))
for k,v in results["v3"].items():
    print("V3",k,json.dumps({x:({a:b for a,b in y.items() if a not in ("per_clip","conditions")} if isinstance(y,dict) else y) for x,y in v.items()}))
for k,v in results["agreements"].items(): print("AGREE",k,v)
