import argparse, hashlib, json, pathlib, sys, runpy
import numpy as np

NS=runpy.run_path(str(pathlib.Path(__file__).with_name("run.py")))
GT_RAW=pathlib.Path(r"C:\scratch\asr50\corpus_v3_frozen\ground_truth_v3.json")
MANIFEST=pathlib.Path(r"C:\scratch\asr50\WP18\corpus_v3_vadmasked\manifest.json")

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--mode",choices=["raw","masked"],required=True)
    p.add_argument("--out",required=True)
    p.add_argument("--audio",default=None)
    a=p.parse_args()
    if hasattr(sys.stdout,"reconfigure"): sys.stdout.reconfigure(errors="backslashreplace")
    audio_dir=pathlib.Path(a.audio or (r"C:\scratch\asr50\corpus_v3_frozen" if a.mode=="raw" else r"C:\scratch\asr50\WP18\corpus_v3_vadmasked"))
    gt=json.loads(GT_RAW.read_text(encoding="utf-8")); clips=gt["clips"]
    vm={}
    if a.mode=="masked":
        m=json.loads(MANIFEST.read_text(encoding="utf-8"))
        vm={x["input"]:x for x in m["clips"]}
    out=pathlib.Path(a.out); out.mkdir(parents=True,exist_ok=True)
    tok=NS["Tokenizer"].from_file(str(NS["ART"]/"tokenizer.json"))
    class Args: pass
    cfg=Args(); cfg.threads=4; cfg.out=str(out); cfg.device="cpu"; cfg.device_id=0; cfg.disable_fallback=False
    enc=NS["session"](NS["ENC"],cfg,False); dec=NS["session"](NS["DEC"],cfg,False); past=NS["session"](NS["PAST"],cfg,False)
    print("providers",enc.get_providers(),dec.get_providers(),past.get_providers())
    for c in clips:
        input_name=c["wav"]
        manifest=vm.get(input_name) if a.mode=="masked" else None
        filename=manifest["output"] if manifest else input_name
        path=audio_dir/filename
        audio=NS["wavread"](path)
        # Frozen v3 input contract: 16 kHz mono float32.
        chunk_size=20*16000
        chunks=[audio[i:i+chunk_size] for i in range(0,len(audio),chunk_size)] if len(audio)>30*16000 else [audio]
        texts=[]; generated=[]; caphit=False; caps=[]
        for chunk in chunks:
            cap=min(512,max(1,int(len(chunk)/16000*6+8))); caps.append(cap)
            text,n,hit=NS["infer"](chunk,enc,dec,past,tok,cap); texts.append(text.strip()); generated.append(n); caphit |= hit
        hyp=" ".join(x for x in texts if x)
        obj={"clip_id":c["clip_id"],"clip_set":c.get("set"),"category":c["category"],"condition":c["condition"],"text":hyp,"words":[],"gate_no_speech":manifest["gate_no_speech"] if manifest else None,"meta":{"runtime":"onnxruntime","version":NS["ort"].__version__,"artifact":"moonshine-base-onnx-int8","requested_device":"cpu","actual_providers":{"encoder":enc.get_providers(),"decoder":dec.get_providers(),"past":past.get_providers()},"threads":4,"sample_rate_hz":16000,"chunk_seconds":20 if len(chunks)>1 else None,"chunk_count":len(chunks),"chunking":"fixed non-overlapping 20-second windows; concatenate text with spaces" if len(chunks)>1 else "none","chunk_token_caps":caps,"chunk_texts":texts if len(chunks)>1 else None,"generated_tokens":generated,"token_cap_hit":caphit,"word_timestamps":"unavailable: text-only HF ONNX export","clip_set":c.get("set"),"category":c["category"],"condition":c["condition"],"voice":c["voice"],"rate":c["rate"],"volume":c["volume"],"snr_db":c["snr_db"],"audio_seconds":len(audio)/16000,"clip_sha256":hashlib.sha256(path.read_bytes()).hexdigest()}}
        (out/(c["clip_id"]+".json")).write_text(json.dumps(obj,ensure_ascii=False,indent=2),encoding="utf-8")
        print(c["clip_id"],repr(hyp),flush=True)
if __name__=="__main__": main()
