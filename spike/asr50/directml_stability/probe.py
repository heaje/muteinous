"""Contained DirectML probe helpers. Launch each invocation in a timed child."""
import argparse
import json
import os
import pathlib
import time
import psutil
import onnxruntime as ort
import numpy as np

MODEL = pathlib.Path(r"C:\scratch\asr50\models\whisper-small-en-onnx-fp16\onnx")

def session(name, mem_pattern=False, sequential=True, providers=None):
    opts = ort.SessionOptions()
    opts.enable_mem_pattern = mem_pattern
    opts.execution_mode = (ort.ExecutionMode.ORT_SEQUENTIAL if sequential
                           else ort.ExecutionMode.ORT_PARALLEL)
    opts.intra_op_num_threads = 1
    opts.inter_op_num_threads = 1
    return ort.InferenceSession(str(MODEL / name), sess_options=opts,
                                providers=providers or [("DmlExecutionProvider", {"device_id": 0}),
                                                        "CPUExecutionProvider"])

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["encoder200", "two-sequential", "two-threads", "create20",
                                    "options", "devices"])
    ap.add_argument("--mem-pattern", action="store_true")
    ap.add_argument("--parallel", action="store_true")
    a = ap.parse_args()
    encpath = "encoder_model_fp16.onnx"
    proc = psutil.Process()
    feat = np.zeros((1, 80, 3000), dtype=np.float32)
    def run(s):
        return s.run(None, {"input_features": feat})[0]
    result = {"pid": os.getpid(), "ort": ort.__version__, "mode": a.mode}
    t0 = time.perf_counter()
    if a.mode == "devices":
        result["providers"] = ort.get_available_providers()
        result["device_count_api"] = hasattr(ort, "get_device")
    elif a.mode == "options":
        s = session(encpath, a.mem_pattern, not a.parallel)
        result.update(providers=s.get_providers(), output_shape=run(s).shape)
    elif a.mode == "encoder200":
        rss_before = proc.memory_info().rss
        s = session(encpath)
        ref = run(s)
        rss_after_create = proc.memory_info().rss
        ts = []
        rss_samples = []
        for i in range(200):
            t = time.perf_counter()
            out = run(s)
            ts.append(time.perf_counter()-t)
            rss_samples.append(proc.memory_info().rss)
        result.update(providers=s.get_providers(), first_s=ts[0],
                      mean_first10_s=float(np.mean(ts[:10])),
                      mean_last10_s=float(np.mean(ts[-10:])),
                      last_10_ratio=float(np.mean(ts[-10:])/np.mean(ts[:10])),
                      max_abs_from_first=float(np.max(np.abs(out.astype(np.float32)-ref.astype(np.float32)))),
                      rss_before_session_bytes=rss_before,
                      rss_after_session_bytes=rss_after_create,
                      rss_first10_mean_bytes=int(np.mean(rss_samples[:10])),
                      rss_last10_mean_bytes=int(np.mean(rss_samples[-10:])),
                      rss_min_bytes=min(rss_samples), rss_max_bytes=max(rss_samples),
                      working_set_bytes=proc.memory_info().rss, iterations=len(ts))
    elif a.mode == "two-sequential":
        x, y = session(encpath), session(encpath)
        rx, ry = run(x), run(y)
        result.update(providers=[x.get_providers(), y.get_providers()],
                      max_abs=float(np.max(np.abs(rx.astype(np.float32)-ry.astype(np.float32)))))
    elif a.mode == "two-threads":
        import concurrent.futures
        x, y = session(encpath), session(encpath)
        with concurrent.futures.ThreadPoolExecutor(2) as pool:
            rx, ry = list(pool.map(run, [x,y]))
        result.update(providers=[x.get_providers(), y.get_providers()],
                      max_abs=float(np.max(np.abs(rx.astype(np.float32)-ry.astype(np.float32)))))
    else:
        values=[]
        for _ in range(20):
            s=session(encpath)
            values.append(float(run(s).mean()))
            del s
        result["means"]=values
    result["elapsed_s"] = time.perf_counter()-t0
    print(json.dumps(result), flush=True)

if __name__ == "__main__":
    main()
