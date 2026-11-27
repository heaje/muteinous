"""Exercise WinML GenAI Phi and ORT Whisper DML sessions in one interpreter."""
import argparse,json,os,sys,time,gc,statistics,math
from pathlib import Path
ROOT=Path(r"C:\scratch\asr50\WP23")
sys.path.insert(0,str(ROOT))
sys.path.insert(0,r"C:\code\hushpatch\src")
os.environ.update(HF_HUB_OFFLINE="1",TRANSFORMERS_OFFLINE="1",HF_HUB_DISABLE_TELEMETRY="1")
import numpy as np, psutil
from muteinous.application import context as app_context
from muteinous.inference import context as inference_context
from muteinous.inference import devices
from ort_whisper import WhisperOrt,transcribe_wav

def main():
 p=argparse.ArgumentParser();p.add_argument("--cases",type=Path,required=True);p.add_argument("--clips",type=Path,required=True);p.add_argument("--output",type=Path,required=True);a=p.parse_args()
 dev=next(d for d in devices.list_devices() if d.kind=="gpu" and d.preferred)
 load0=time.perf_counter()
 phi=app_context.model_loader(dev)
 phi_load=time.perf_counter()-load0
 ort0=time.perf_counter()
 whisper=WhisperOrt("DmlExecutionProvider")
 whisper_load=time.perf_counter()-ort0
 cases=json.loads(a.cases.read_text(encoding="utf-8"))
 t=time.perf_counter();phi_rows=[]
 for r in cases:
  s=r["sentence"]; w=r["target_word"]; dec=inference_context.classify(s,s[int(r["start"]):int(r["end"])],r["category"],app_context.model_loader,device=dev)
  phi_rows.append({"sentence":s,"target_word":w,"category":r["category"],"label":int(r["label"]),
                   "pred":int(dec.censor),"confidence":dec.confidence})
 phi_elapsed=time.perf_counter()-t
 clipdoc=json.loads(a.clips.read_text(encoding="utf-8"));audio_root=ROOT/"corpus"/"audio16k_v3"
 t=time.perf_counter();asr_rows=[]
 for c in clipdoc["clips"]:
  txt=transcribe_wav(whisper,audio_root/c["wav"])
  asr_rows.append({"clip_id":c["clip_id"],"text":txt,"reference":c["transcript"]})
 asr_elapsed=time.perf_counter()-t
 process=psutil.Process()
 a.output.parent.mkdir(parents=True,exist_ok=True)
 a.output.write_text(json.dumps({"pid":os.getpid(),"device":dev.key,
   "runtime":{"genai":__import__("onnxruntime_genai").__version__,"onnxruntime":__import__("onnxruntime").__version__},
   "phi_load_s":phi_load,"whisper_load_s":whisper_load,"phi_elapsed_s":phi_elapsed,"whisper_elapsed_s":asr_elapsed,
   "peak_working_set_bytes":process.memory_info().peak_wset,"phi_results":phi_rows,"asr_results":asr_rows},
   ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
 print(json.dumps({"pid":os.getpid(),"phi_load_s":phi_load,"whisper_load_s":whisper_load,
                   "phi_elapsed_s":phi_elapsed,"whisper_elapsed_s":asr_elapsed,
                   "peak_working_set_bytes":process.memory_info().peak_wset}))
 del whisper,phi
 app_context.release();gc.collect()
if __name__=="__main__":main()
