"""Child workload for DirectML stability tests; every invocation is externally timed."""
import concurrent.futures
import importlib.util
import json
import os
import pathlib
import sys
import time
import numpy as np
import onnxruntime as ort

RUNNER = pathlib.Path(r"C:\code\muteinous-spike50\spike\asr50\runners\ort-whisper-small-en\run.py")
MODEL = pathlib.Path(r"C:\scratch\asr50\models\whisper-small-en-onnx-fp16")
AUDIO = pathlib.Path(r"C:\scratch\asr50\corpus_v2_frozen\natural_18s_00.wav")
GEN = json.loads((MODEL / "generation_config.json").read_text(encoding="utf-8"))
spec = importlib.util.spec_from_file_location("whisper_runner", RUNNER)
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)
TOK = runner.Tokenizer.from_file(str(MODEL / "tokenizer.json"))

def sessions(provider):
    names=("encoder_model_fp16.onnx", "decoder_model_fp16.onnx",
           "decoder_with_past_model_fp16.onnx")
    if provider == "cpu":
        # ORT 1.24's default FP16 graph fusion fails on this model; disable
        # graph optimizations for an independent CPU reference attempt.
        result=[]
        for name in names:
            opts=ort.SessionOptions()
            opts.graph_optimization_level=ort.GraphOptimizationLevel.ORT_DISABLE_ALL
            opts.enable_mem_pattern=False
            opts.execution_mode=ort.ExecutionMode.ORT_SEQUENTIAL
            opts.intra_op_num_threads=1
            result.append(ort.InferenceSession(str(MODEL/"onnx"/name),
                                               sess_options=opts,
                                               providers=["CPUExecutionProvider"]))
        return result
    return [runner.create(MODEL / "onnx" / name, provider, 0, 1) for name in names]

def decode(audio, sess):
    return runner.transcribe(audio, *sess, TOK, GEN, "on")[0]

def main():
    mode = sys.argv[1]
    out = {"pid": os.getpid(), "ort": ort.__version__, "mode": mode}
    if mode in ("asr", "create20", "providers"):
        if mode == "providers":
            out["has_add_provider_for_devices"] = hasattr(ort, "add_provider_for_devices")
            out["available"] = ort.get_available_providers()
            print(json.dumps(out), flush=True); return
        if mode == "create20":
            t0 = time.perf_counter()
            means=[]
            for _ in range(20):
                ss=sessions("dml")
                means.append(decode(runner.read_wav(AUDIO), ss))
                del ss
            out.update(elapsed_s=time.perf_counter()-t0, unique_texts=len(set(means)))
        else:
            provider = sys.argv[2]
            ss=sessions(provider)
            out.update(providers=[s.get_providers() for s in ss],
                       text=decode(runner.read_wav(AUDIO), ss))
    elif mode == "threads":
        s1, s2 = sessions("dml"), sessions("dml")
        audio = runner.read_wav(AUDIO)
        with concurrent.futures.ThreadPoolExecutor(2) as ex:
            texts=list(ex.map(lambda s: decode(audio, s), [s1,s2]))
        out.update(texts=texts, same=(texts[0] == texts[1]),
                   providers=[s1[0].get_providers(), s2[0].get_providers()])
    elif mode == "cpu":
        out["text"] = decode(runner.read_wav(AUDIO), sessions("cpu"))
    elif mode == "hold":
        # Explicit controllable DML allocation, retained until parent terminates child.
        n=int(sys.argv[2])
        hold=[]
        for _ in range(n):
            hold.append(ort.OrtValue.ortvalue_from_numpy(np.zeros((64*1024*1024,), dtype=np.uint8),
                                                         "dml", 0))
        print(json.dumps({"pid":os.getpid(),"allocated_bytes":len(hold)*64*1024*1024,
                          "providers":ort.get_available_providers()}), flush=True)
        while True:
            time.sleep(1)
    else:
        raise ValueError(mode)
    print(json.dumps(out), flush=True)

if __name__ == "__main__":
    main()
