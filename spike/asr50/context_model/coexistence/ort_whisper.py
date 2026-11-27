"""Small greedy Whisper ONNX decoder for the local q4 export (no model fetch)."""
import json, time
from pathlib import Path
import numpy as np
import onnxruntime as ort
from transformers import WhisperFeatureExtractor, WhisperTokenizer

MODEL = Path(r"C:\scratch\asr50\models\whisper-large-v3-turbo-onnx-merged-q4")
ONNX = MODEL / "onnx"

class WhisperOrt:
    def __init__(self, provider="DmlExecutionProvider"):
        self.provider = provider
        self.options = ort.SessionOptions()
        self.options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
        self.options.enable_mem_pattern = False
        self.options.log_severity_level = 3
        self.encoder = ort.InferenceSession(str(ONNX/"encoder_model_q4.onnx"), self.options,
                                             providers=[(provider, {"device_id": 0}), "CPUExecutionProvider"])
        self.decoder = ort.InferenceSession(str(ONNX/"decoder_model_merged_q4.onnx"), self.options,
                                             providers=[(provider, {"device_id": 0}), "CPUExecutionProvider"])
        self.decoder_past = ort.InferenceSession(str(ONNX/"decoder_with_past_model_q4.onnx"), self.options,
                                                  providers=[(provider, {"device_id": 0}), "CPUExecutionProvider"])
        self.fe = WhisperFeatureExtractor.from_pretrained(str(MODEL), local_files_only=True)
        self.tok = WhisperTokenizer.from_pretrained(str(MODEL), local_files_only=True)
        self.start_id = 50258
        self.eos_id = 50257
        prompt = self.tok.get_decoder_prompt_ids(language="english", task="transcribe", no_timestamps=True)
        self.prefix = [self.start_id] + [v for _,v in sorted(prompt)]
        self.layer_count=4

    def transcribe(self, audio):
        feats=self.fe(audio, sampling_rate=16000, return_tensors="np").input_features.astype(np.float32)
        enc=self.encoder.run(["last_hidden_state"],{"input_features":feats})[0]
        feeds={"input_ids":np.asarray([self.prefix],dtype=np.int64),
               "encoder_hidden_states":enc,
               "use_cache_branch":np.asarray([False],dtype=np.bool_)}
        empty=np.zeros((1,20,0,64),dtype=np.float32)
        for i in range(self.layer_count):
            for side in ("decoder","encoder"):
                for kv in ("key","value"):
                    feeds[f"past_key_values.{i}.{side}.{kv}"]=empty
        out=self.decoder.run(None,feeds)
        names=[x.name for x in self.decoder.get_outputs()]
        vals=dict(zip(names,out))
        cache={k:v for k,v in vals.items() if k.startswith("present.")}
        generated=list(self.prefix)
        for _ in range(128):
            token=int(np.argmax(vals["logits"][0,-1,:]))
            if token==self.eos_id: break
            generated.append(token)
            if len(generated)>=448: break
            past={f"past_key_values.{k.split('.',1)[1]}":v for k,v in cache.items()}
            past["input_ids"]=np.asarray([[token]],dtype=np.int64)
            out=self.decoder_past.run(None,past)
            vals=dict(zip([x.name for x in self.decoder_past.get_outputs()],out))
            cache={k:v for k,v in cache.items() if ".encoder." in k}
            cache.update({k:v for k,v in vals.items() if k.startswith("present.")})
        text=self.tok.decode(generated[len(self.prefix):],skip_special_tokens=True)
        return text.strip()

def transcribe_wav(recognizer, path):
    import soundfile as sf
    a,sr=sf.read(path,dtype="float32",always_2d=True)
    if sr!=16000 or a.shape[1]!=1: raise ValueError(f"unexpected audio {sr} {a.shape}")
    return recognizer.transcribe(a[:,0])
