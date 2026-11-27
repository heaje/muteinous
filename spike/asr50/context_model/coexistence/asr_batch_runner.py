"""Untimed/short concurrency batches for the WP23 local Whisper and Parakeet models."""
import argparse,json,os,subprocess,sys,time
from pathlib import Path
ROOT=Path(r"C:\scratch\asr50\WP23")
sys.path.insert(0,str(ROOT))
AUDIO=ROOT/"corpus"/"audio16k_v3"
MODEL=Path(r"C:\scratch\asr50\models")
def main():
 p=argparse.ArgumentParser()
 p.add_argument("--engine",choices=("ort","vulkan","parakeet"),required=True)
 p.add_argument("--input",type=Path,default=ROOT/"corpus"/"ort_probe20_gt.json")
 p.add_argument("--output",type=Path,required=True)
 a=p.parse_args()
 os.environ.update(HF_HUB_OFFLINE="1",TRANSFORMERS_OFFLINE="1",HF_HUB_DISABLE_TELEMETRY="1")
 clips=json.loads(a.input.read_text(encoding="utf-8"))["clips"]
 start=time.perf_counter(); load_s=None; rec=None
 if a.engine=="ort":
  from ort_whisper import WhisperOrt
  rec=WhisperOrt("DmlExecutionProvider")
 elif a.engine=="parakeet":
  import sherpa_onnx
  d=MODEL/"parakeet-tdt-0-6b-v2-sherpa-onnx-int8"
  rec=sherpa_onnx.OfflineRecognizer.from_transducer(str(d/"encoder.int8.onnx"),str(d/"decoder.int8.onnx"),
    str(d/"joiner.int8.onnx"),str(d/"tokens.txt"),num_threads=4,sample_rate=16000,feature_dim=80,
    dither=0.0,decoding_method="greedy_search",provider="cpu",model_type="nemo_transducer",debug=False)
 else:
  rec=None
 load_s=time.perf_counter()-start
 outputs=[]
 for clip in clips:
  wav=AUDIO/clip["wav"]; t=time.perf_counter()
  if a.engine=="ort":
   import soundfile as sf
   samples,sr=sf.read(wav,dtype="float32",always_2d=True)
   if sr!=16000 or samples.shape[1]!=1: raise ValueError((sr,samples.shape))
   text=rec.transcribe(samples[:,0])
   providers={k:rec.encoder.get_providers() for k in ("encoder","decoder","decoder_past")}
  elif a.engine=="parakeet":
   import soundfile as sf,numpy as np
   samples,sr=sf.read(wav,dtype="float32",always_2d=True); stream=rec.create_stream()
   stream.accept_waveform(sr,np.ascontiguousarray(samples[:,0]));rec.decode_stream(stream);text=stream.result.text
   providers={"provider":"cpu"}
  else:
   binary=Path(r"C:\scratch\asr50\WP2\artifacts\whisper-vulkan-dl-windows-x64\whisper-cli.exe")
   model=MODEL/"whisper-large-v3-turbo-whisper-cpp-q5-0"/"ggml-large-v3-turbo-q5_0.bin"
   base=a.output.parent/f"{a.output.stem}_{clip['clip_id']}"
   proc=subprocess.run([str(binary),"-m",str(model),"-f",str(wav),"-l","en","-t","12","-ojf","-of",str(base),"-dev","0"],
                       capture_output=True,text=True,errors="replace")
   log=proc.stdout+proc.stderr
   if proc.returncode or "using Vulkan0 backend" not in log: raise RuntimeError(f"Vulkan ASR failure {proc.returncode}: {log[-1000:]}")
   doc=json.loads(Path(str(base)+".json").read_text(encoding="utf-8"))
   text=" ".join(seg.get("text","").strip() for seg in doc.get("transcription",[]))
   providers={"backend":"Vulkan0"}
  outputs.append({"clip_id":clip["clip_id"],"text":text,"reference":clip["transcript"],"seconds":time.perf_counter()-t})
 a.output.parent.mkdir(parents=True,exist_ok=True)
 a.output.write_text(json.dumps({"engine":a.engine,"pid":os.getpid(),"n":len(outputs),"load_s":load_s,
    "batch_s":sum(x["seconds"] for x in outputs),"providers":providers,"results":outputs},ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
 print(json.dumps({"engine":a.engine,"pid":os.getpid(),"n":len(outputs),"load_s":load_s,
     "batch_s":sum(x["seconds"] for x in outputs),"providers":providers}))
if __name__=="__main__":main()
