"""Corpus-v2 evaluation and time-aligned masking for the WP18 study."""
import argparse, json, shutil, hashlib, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import numpy as np
import soundfile as sf
from apply_gate import SileroRunner, mask

SR = 16000

def union_samples(intervals):
    if not intervals: return []
    xs = sorted(intervals); out = [list(xs[0])]
    for a,b in xs[1:]:
        if a <= out[-1][1]: out[-1][1] = max(out[-1][1], b)
        else: out.append([a,b])
    return out

def count(intervals): return sum(b-a for a,b in union_samples(intervals))

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--corpus",type=Path,required=True); p.add_argument("--ground-truth",type=Path,required=True)
    p.add_argument("--model",type=Path,required=True); p.add_argument("--output",type=Path,required=True)
    a=p.parse_args(); gt=json.loads(a.ground_truth.read_text(encoding="utf-8"))
    runner=SileroRunner(a.model); clips=gt["clips"]; cache={}
    for c in clips:
        x,sr=sf.read(a.corpus/c["wav"],dtype="float32")
        assert sr==SR and x.ndim==1
        cache[c["clip_id"]]=(x,c)
    # Verify our base algorithm against faster-whisper's implementation.
    from faster_whisper.vad import get_speech_timestamps, VadOptions
    checks=[]
    for cid in list(cache)[:8]:
        x,_=cache[cid]
        ours=runner.segments(x,threshold=.5,min_silence_duration_ms=200,speech_pad_ms=100)
        theirs=get_speech_timestamps(x,VadOptions(threshold=.5,min_silence_duration_ms=200,speech_pad_ms=100))
        checks.append({"clip":cid,"identical":ours==theirs,"ours":ours,"reference":theirs})
    sweep=[]
    for th in (.3,.5,.7):
      for pad in (30,100,200):
       for silence in (100,200,500):
        no=0; recnums=recden=precnum=precden=cuts=0
        for x,c in cache.values():
            seg=runner.segments(x,threshold=th,min_silence_duration_ms=silence,speech_pad_ms=pad)
            if c["set"]=="timing":
                refs=[[w["start_sample"],w["end_sample"]] for w in c["words"]]
                speech=[[s["start"],s["end"]] for s in seg]
                recden+=count(refs)
                recnums+=sum(max(0,min(b,d)-max(a,z)) for a,b in refs for z,d in speech)
                # precision against words expanded by 40 ms (gap-tolerant)
                expanded=[[max(0,a-640),min(len(x),b+640)] for a,b in refs]
                precden+=count(speech)
                intersections = [[max(a,z), min(b,d)] for a,b in speech for z,d in expanded
                                 if min(b,d) > max(a,z)]
                precnum += count(intersections)
                cuts+=sum(not any(min(b,d)>max(a,z) for z,d in speech) for a,b in refs)
            elif c["category"] in ("silence","non_speech"):
                no+=not bool(seg)
        sweep.append({"threshold":th,"speech_pad_ms":pad,"min_silence_duration_ms":silence,
          "timing_recall":recnums/recden,"timing_precision_gap40ms":precnum/precden if precden else 0,
          "words_cut":cuts,"zero_of_20":no})
    # Chosen setting: central threshold, 200ms silence debounce, 100ms pad.
    chosen={"threshold":.5,"neg_threshold":.35,"min_speech_duration_ms":0,
            "min_silence_duration_ms":200,"speech_pad_ms":100,"sample_rate_hz":SR}
    a.output.mkdir(parents=True,exist_ok=True); manifest=[]
    for x,c in cache.values():
        seg=runner.segments(x,threshold=.5,min_silence_duration_ms=200,speech_pad_ms=100)
        dst=a.output/c["wav"]; sf.write(dst,mask(x,seg),SR,subtype="FLOAT")
        manifest.append({"clip_id":c["clip_id"],"file":dst.name,"segments":seg,
          "gate_no_speech":not bool(seg),"samples":len(x),
          "input_sha256":hashlib.sha256((a.corpus/c["wav"]).read_bytes()).hexdigest(),
          "sha256":hashlib.sha256(dst.read_bytes()).hexdigest()})
    shutil.copy2(a.ground_truth,a.output/"ground_truth_v2.json")
    (a.output/"manifest.json").write_text(json.dumps({"settings":chosen,"clips":manifest},indent=2),encoding="utf-8")
    report={"settings":chosen,"sweep":sweep,"verification":checks,
            "segments":{c["clip_id"]:runner.segments(x,**{"threshold":.5,"min_silence_duration_ms":200,"speech_pad_ms":100}) for x,c in cache.values()}}
    (a.output.parent/"evaluation.json").write_text(json.dumps(report,indent=2),encoding="utf-8")
if __name__=="__main__": main()
