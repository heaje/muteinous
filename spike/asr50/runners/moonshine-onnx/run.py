import argparse, json, os, time, wave, hashlib, pathlib, sys, struct
os.environ.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", HF_HUB_DISABLE_TELEMETRY="1")
import numpy as np
import onnxruntime as ort
from tokenizers import Tokenizer
import psutil, ctypes

ART = pathlib.Path(r"C:\scratch\asr50\models\moonshine-base-onnx-int8")
ENC = ART / "onnx" / "encoder_model_int8.onnx"
DEC = ART / "onnx" / "decoder_model_merged_int8.onnx"
PAST = ART / "onnx" / "decoder_with_past_model_int8.onnx"

def wavread(path):
    b=pathlib.Path(path).read_bytes()
    assert b[:4] == b"RIFF" and b[8:12] == b"WAVE"
    pos=12; fmt=None; raw=None
    while pos+8 <= len(b):
        tag=b[pos:pos+4]; size=struct.unpack_from("<I",b,pos+4)[0]; chunk=b[pos+8:pos+8+size]
        if tag==b"fmt ": fmt=struct.unpack_from("<HHIIHH",chunk)
        if tag==b"data": raw=chunk
        pos += 8+size+(size&1)
    code,ch,rate,_,align,bits=fmt
    assert ch==1 and rate==16000 and bits==32 and code==3
    return np.frombuffer(raw,dtype="<f4").copy()

def infer(audio, enc, dec, past, tok, limit):
    hidden = enc.run(None, {"input_values": audio[None, :]})[0]
    cfg = json.loads((ART / "config.json").read_text(encoding="utf-8"))
    gen = json.loads((ART / "generation_config.json").read_text(encoding="utf-8"))
    heads = cfg["decoder_num_attention_heads"]
    layers = cfg["decoder_num_hidden_layers"]
    dim = cfg["hidden_size"] // heads
    names = [x.name for x in dec.get_inputs()]
    cache = {}
    for n in names:
        if n.startswith("past_key_values."):
            cache[n] = np.zeros((1, heads, 0, dim), dtype=np.float32)
    ids = [gen["decoder_start_token_id"]]
    usepast = False
    eos = gen["eos_token_id"]
    for _ in range(limit):
        # The merged graph consumes all caches on every step. Decoder caches
        # grow each iteration; encoder cross-attention caches are retained from
        # the initial call, as emitted by the graph.
        sess = dec
        feeds = {"input_ids": np.array([[ids[-1]]] if usepast else [ids], dtype=np.int64)}
        feeds["encoder_hidden_states"] = hidden
        feeds["use_cache_branch"] = np.array([usepast], dtype=np.bool_)
        feeds.update(cache)
        expected = {x.name for x in sess.get_inputs()}
        feeds = {k: v for k, v in feeds.items() if k in expected}
        outs = sess.run(None, feeds)
        onames = [o.name for o in sess.get_outputs()]
        vals = dict(zip(onames, outs))
        nxt = int(np.argmax(vals["logits"][0, -1]))
        if nxt == eos: break
        ids.append(nxt)
        for n, v in vals.items():
            if n.startswith("present.") and ".decoder." in n:
                cache[n.replace("present.", "past_key_values.")] = v
            elif not usepast and n.startswith("present.") and ".encoder." in n:
                cache[n.replace("present.", "past_key_values.")] = v
        usepast = True
    return tok.decode(ids[1:]), len(ids)-1, len(ids)-1 >= limit

def session(path, args, prof=False, disable_fallback=False):
    so = ort.SessionOptions()
    so.intra_op_num_threads = args.threads
    if prof:
        so.enable_profiling = True
        so.profile_file_prefix = str(pathlib.Path(args.out) / f"profile-{args.device}")
    if disable_fallback:
        so.add_session_config_entry("session.disable_cpu_ep_fallback", "1")
    prov = [("DmlExecutionProvider", {"device_id": args.device_id}), "CPUExecutionProvider"] if args.device == "dml" else ["CPUExecutionProvider"]
    return ort.InferenceSession(str(path), so, providers=prov)

def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="backslashreplace")
    p=argparse.ArgumentParser()
    p.add_argument("--audio", default=r"C:\scratch\asr50\WP6\audio16k")
    p.add_argument("--out", required=True)
    p.add_argument("--device", choices=["cpu","dml"], default="cpu")
    p.add_argument("--device-id", type=int, default=0)
    p.add_argument("--threads", type=int, default=4)
    p.add_argument("--limit", type=int, default=128)
    p.add_argument("--disable-fallback", action="store_true")
    a=p.parse_args(); pathlib.Path(a.out).mkdir(parents=True,exist_ok=True)
    tok=Tokenizer.from_file(str(ART/"tokenizer.json"))
    t=time.perf_counter()
    enc=session(ENC,a,True,a.disable_fallback); dec=session(DEC,a,True,a.disable_fallback); past=session(PAST,a,True,a.disable_fallback)
    load=time.perf_counter()-t
    print("providers",enc.get_providers(),dec.get_providers(),past.get_providers(),"load_s",load,flush=True)
    for f in sorted(pathlib.Path(a.audio).glob("*.wav")):
        if f.name in ("ground_truth.json",): continue
        x=wavread(f); start=time.perf_counter()
        try:
            audio_s=len(x)/16000
            limit=min(a.limit,512,max(1,int(audio_s*6+8)))
            text,generated,cap_hit=infer(x,enc,dec,past,tok,limit)
            elapsed=time.perf_counter()-start
            obj={"text":text,"words":[],"meta":{"runtime":"onnxruntime","version":ort.__version__,"artifact":"moonshine-base-onnx-int8","requested_device":a.device,"actual_providers":{"encoder":enc.get_providers(),"decoder":dec.get_providers(),"past":past.get_providers()},"actual_device_verified_by":"InferenceSession.get_providers; DML node placement separately checked in ORT profiling JSON","threads":a.threads,"wall_seconds":elapsed,"audio_seconds":audio_s,"rtf":elapsed/audio_s,"max_new_tokens":limit,"generated_tokens":generated,"token_cap_hit":cap_hit,"word_timestamps":"unavailable: text-only HF ONNX export","peak_process_working_set_bytes":psutil.Process().memory_info().peak_wset if hasattr(psutil.Process().memory_info(),"peak_wset") else None}}
            (pathlib.Path(a.out)/(f.stem+".json")).write_text(json.dumps(obj,ensure_ascii=False,indent=2),encoding="utf-8")
            print(f.name,repr(text),obj["meta"]["wall_seconds"],flush=True)
        except Exception as e:
            print(f.name,"ERROR",repr(e),flush=True); raise
    for s in (enc,dec,past):
        try: print("profile",s.end_profiling(),flush=True)
        except Exception: pass
if __name__=="__main__": main()
