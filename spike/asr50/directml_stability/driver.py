"""Timed process harness with stdout/stderr, GPU counters and System TDR event snapshots."""
import json
import base64
import os
import pathlib
import subprocess
import sys
import time
import psutil

ROOT = pathlib.Path(r"C:\scratch\asr50\WP19")
PY = pathlib.Path(r"C:\scratch\asr50\WP19\venv-dml\Scripts\python.exe")
CHILD = pathlib.Path(__file__).with_name("asr_child.py")

def powershell(script):
    p = subprocess.run(["powershell.exe", "-NoProfile", "-Command", script],
                       capture_output=True, text=True, timeout=20)
    return p.stdout.strip()

def events(since):
    query = ("Get-WinEvent -FilterHashtable @{LogName='System';StartTime=[datetime]::Parse('" +
             since + "')} -ErrorAction SilentlyContinue | Where-Object {$_.ProviderName -match 'amdkmdag|Display'} | "
             "Select-Object TimeCreated,ProviderName,Id,Message | ConvertTo-Json -Compress")
    raw = powershell(query)
    if not raw: return []
    try:
        v=json.loads(raw); return v if isinstance(v,list) else [v]
    except Exception: return [{"raw":raw}]

def gpu_samples(pids):
    script = r"""$a=(Get-Counter '\GPU Process Memory(*)\Dedicated Usage' -ErrorAction SilentlyContinue).CounterSamples | ForEach-Object {[ordered]@{path=$_.Path;bytes=[int64]$_.CookedValue}}; ConvertTo-Json -InputObject @($a) -Compress"""
    raw=powershell(script)
    try: values=json.loads(raw) if raw else []
    except Exception: return {"parse_error":raw}
    if isinstance(values,dict): values=[values]
    return [x for x in (values or []) if any(("pid_"+str(pid)+"_") in x.get("path","").lower() for pid in pids)]

def main():
    name=sys.argv[1]
    timeout=int(sys.argv[2])
    commands=json.loads(base64.b64decode(sys.argv[3]).decode("utf-8"))
    start=time.strftime("%Y-%m-%dT%H:%M:%S")
    before=events(start)
    children=[]
    for i,argv in enumerate(commands):
        out=(ROOT/f"{name}-{i}.stdout.txt").open("wb")
        err=(ROOT/f"{name}-{i}.stderr.txt").open("wb")
        p=subprocess.Popen(argv,stdout=out,stderr=err,creationflags=subprocess.CREATE_NEW_PROCESS_GROUP)
        children.append({"proc":p,"out":out,"err":err,"pid":p.pid,"argv":argv,"timeout":False})
    samples=[]
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline and any(c["proc"].poll() is None for c in children):
        pids=[]
        for c in children:
            pids.append(c["pid"])
            try: pids.extend(x.pid for x in psutil.Process(c["pid"]).children(recursive=True))
            except (psutil.NoSuchProcess, psutil.AccessDenied): pass
        samples.append({"at":time.time(),"pids":pids,"counters":gpu_samples(pids)})
        time.sleep(1)
    for c in children:
        if c["proc"].poll() is None:
            c["timeout"]=True
            c["proc"].kill()
    for c in children:
        try: c["proc"].wait(timeout=10)
        except subprocess.TimeoutExpired: pass
        c["out"].close(); c["err"].close()
    after=events(start)
    results=[]
    for c in children:
        decode=lambda p: p.read_bytes().decode("utf-8",errors="replace")
        results.append({"pid":c["pid"],"argv":c["argv"],"timed_out":c["timeout"],
            "exit_code":c["proc"].returncode,
            "stdout":decode(ROOT/f"{name}-{children.index(c)}.stdout.txt"),
            "stderr":decode(ROOT/f"{name}-{children.index(c)}.stderr.txt")})
    result={"experiment":name,"timeout_seconds":timeout,"children":results,
            "gpu_dedicated_process_samples":samples,"system_events_before":before,
            "system_events_after":after}
    (ROOT/f"{name}.json").write_text(json.dumps(result,indent=2),encoding="utf-8")
    print(json.dumps(result,indent=2))

if __name__=="__main__": main()
