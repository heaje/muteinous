"""One long local Vulkan-requested whisper.cpp pass to permit PID-scoped counters."""
import json,os,subprocess,sys,time
from pathlib import Path
import argparse
ROOT=Path(r"C:\scratch\asr50\WP23")
def main():
 ap=argparse.ArgumentParser();ap.add_argument("--input",type=Path,required=True);ap.add_argument("--output",type=Path,required=True);a=ap.parse_args()
 import soundfile as sf,numpy as np
 wav=a.input;out=a.output
 binary=Path(r"C:\scratch\asr50\WP2\artifacts\whisper-vulkan-dl-windows-x64\whisper-cli.exe")
 model=Path(r"C:\scratch\asr50\models\whisper-large-v3-turbo-whisper-cpp-q5-0\ggml-large-v3-turbo-q5_0.bin")
 base=out.with_suffix("")
 t=time.perf_counter()
 p=subprocess.run([str(binary),"-m",str(model),"-f",str(wav),"-l","en","-t","12","-ojf","-of",str(base),"-dev","0"],
                 capture_output=True,text=True,errors="replace")
 log=p.stdout+p.stderr
 if p.returncode or "using Vulkan0 backend" not in log: raise RuntimeError(log[-3000:])
 doc=json.loads(Path(str(base)+".json").read_text(encoding="utf-8"))
 text=" ".join(x.get("text","").strip() for x in doc.get("transcription",[]))
 result={"runner_pid":os.getpid(),"cli_pid":None,"runtime_s":time.perf_counter()-t,
         "backend":"Vulkan0","text":text,"stderr_tail":log[-2000:]}
 out.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
 print(json.dumps({"runner_pid":os.getpid(),"runtime_s":result["runtime_s"],"text_chars":len(text),"backend":"Vulkan0"}))
if __name__=="__main__":main()
