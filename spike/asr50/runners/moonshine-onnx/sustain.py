import argparse, json, pathlib, time, runpy, sys
ns=runpy.run_path(str(pathlib.Path(__file__).with_name("run.py")))
def main():
    p=argparse.ArgumentParser(); p.add_argument("--seconds",type=int,default=25); p.add_argument("--out",required=True); p.add_argument("--audio",required=True)
    a=p.parse_args()
    pathlib.Path(a.out, "candidate-pid.txt").write_text(str(__import__("os").getpid()),encoding="ascii")
    class Args: pass
    cfg=Args(); cfg.threads=4; cfg.out=a.out; cfg.device="dml"; cfg.device_id=0; cfg.disable_fallback=False
    pathlib.Path(a.out).mkdir(parents=True,exist_ok=True)
    ort=ns["ort"]; tok=ns["Tokenizer"].from_file(str(ns["ART"]/"tokenizer.json"))
    enc=ns["session"](ns["ENC"],cfg,True); dec=ns["session"](ns["DEC"],cfg,True); past=ns["session"](ns["PAST"],cfg,True)
    x=ns["wavread"](a.audio); lim=min(512,int(len(x)/16000*6+8))
    end=time.perf_counter()+a.seconds; count=0
    while time.perf_counter()<end:
        ns["infer"](x,enc,dec,past,tok,lim); count+=1
    print(json.dumps({"pid":__import__("os").getpid(),"elapsed_s":a.seconds,"passes":count,"providers":[enc.get_providers(),dec.get_providers(),past.get_providers()]}),flush=True)
    for s in (enc,dec,past): print(s.end_profiling(),flush=True)
if __name__=="__main__": main()
