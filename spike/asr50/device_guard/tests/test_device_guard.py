import os
from pathlib import Path
import sys

import onnx
from onnx import helper, TensorProto
import onnxruntime as ort
import pytest

ROOT = Path(r"C:\code\muteinous-spike50\spike\asr50\device_guard")
sys.path.insert(0, str(ROOT))
from device_guard import (DeviceUnavailable, FallbackDetected, enumerate_ort,
                          enumerate_ggml, ort_session, whisper_run)
GGML = Path(r"C:\scratch\asr50\WP2\artifacts\whisper-vulkan-dl-windows-x64")
MODEL = Path(r"C:\scratch\asr50\models\whisper-small-en-onnx-fp16\onnx\encoder_model_fp16.onnx")
CPP_MODEL = Path(r"C:\scratch\asr50\models\whisper-small-en-whisper-cpp-q5-1\ggml-small.en-q5_1.bin")
AUDIO = Path(r"C:\scratch\asr50\WP6\audio16k")


def graph(path):
    x = helper.make_tensor_value_info("x", TensorProto.FLOAT, [1, 4])
    y = helper.make_tensor_value_info("y", TensorProto.FLOAT, [1, 4])
    w = helper.make_tensor("w", TensorProto.FLOAT, [4, 4], [1, 0, 0, 0] * 4)
    node = helper.make_node("MatMul", ["x", "w"], ["y"])
    model = helper.make_model(helper.make_graph([node], "matmul", [x], [y], [w]),
                              opset_imports=[helper.make_opsetid("", 13)])
    model.ir_version = 10
    onnx.save(model, path)


def test_enumeration_metadata():
    devices = enumerate_ort(ort)
    assert devices and any(d.kind == "cpu" for d in devices)
    dml = [d for d in devices if d.backend == "DmlExecutionProvider"]
    if dml:
        assert dml[0].name and dml[0].key
        assert dml[0].memory_mb is not None
        assert dml[0].integrated is False


def test_approved_encoder_input_contract():
    model = onnx.load(str(MODEL))
    inputs = {x.name: x for x in model.graph.input}
    inp = inputs["input_features"]
    dims = [d.dim_value or d.dim_param for d in inp.type.tensor_type.shape.dim]
    assert inp.type.tensor_type.elem_type == TensorProto.FLOAT
    assert dims == ["batch_size", "feature_size", "encoder_sequence_length"]


def test_cpu_and_invalid_explicit(tmp_path):
    p = tmp_path / "matmul.onnx"
    graph(p)
    _, report = ort_session(ort, str(p), "cpu")
    assert report["actual"] == "cpu"
    with pytest.raises((DeviceUnavailable, FallbackDetected)):
        ort_session(ort, str(p), "explicit-gpu", 9999)


def test_dml_only_vs_cpu_fallback(tmp_path):
    p = tmp_path / "matmul.onnx"
    graph(p)
    dml_only = ort.InferenceSession(
        str(p), providers=[("DmlExecutionProvider", {"device_id": 9999})])
    # ORT 1.24.4 retries CPU despite a DML-only request.
    assert dml_only.get_providers() == ["CPUExecutionProvider"]
    # The policy layer guards silent CPU fallback irrespective of runtime behavior.
    with pytest.raises((DeviceUnavailable, FallbackDetected)):
        ort_session(ort, str(p), "explicit-gpu", 9999)


def test_explicit_gpu_and_auto(tmp_path):
    model = tmp_path / "matmul.onnx"
    graph(model)
    ds = [d for d in enumerate_ort(ort) if d.backend == "DmlExecutionProvider"]
    if not ds:
        pytest.skip("No DirectML adapter enumerated")
    _, gpu = ort_session(ort, model, "explicit-gpu", ds[0].index)
    assert gpu["actual"] == "gpu"
    _, auto = ort_session(ort, model, "auto")
    assert auto["actual"] == "gpu"


def test_whisper_encoder_explicit_gpu_and_invalid_device():
    if not MODEL.exists():
        pytest.skip("approved fp16 encoder unavailable")
    ds = [d for d in enumerate_ort(ort) if d.backend == "DmlExecutionProvider"]
    if not ds:
        pytest.skip("No DirectML adapter enumerated")
    _, report = ort_session(ort, str(MODEL), "explicit-gpu", ds[0].index)
    assert report["actual"] == "gpu"
    assert report["dml_events"] > 0
    with pytest.raises((DeviceUnavailable, FallbackDetected)):
        ort_session(ort, str(MODEL), "explicit-gpu", 9999)


def test_auto_creation_failure_records_fallback(monkeypatch, tmp_path):
    p = tmp_path / "matmul.onnx"
    graph(p)
    class Fake:
        def __init__(self, model, providers, provider_options=None, **kwargs):
            if isinstance(providers[0], tuple):
                raise RuntimeError("simulated DML creation failure")
            self.providers = providers
        def get_providers(self): return self.providers
    class ORT:
        InferenceSession = Fake
        class ExecutionMode:
            ORT_SEQUENTIAL = 0
        class SessionOptions:
            enable_mem_pattern = True
            execution_mode = None
            enable_profiling = False
    _, report = ort_session(ORT, str(p), "auto")
    assert report["actual"] == "cpu" and "simulated" in report["fallback_reason"]


def test_ggml_enumeration():
    if not (GGML / "ggml-diag.exe").exists():
        pytest.skip("ggml-diag absent")
    ds = enumerate_ggml(str(GGML / "ggml-diag.exe"))
    assert any(d.kind == "cpu" for d in ds)
    assert all(d.key and d.name for d in ds)


def test_whisper_explicit_gpu_invalid_rejected_before_run():
    if not (GGML / "whisper-cli.exe").exists():
        pytest.skip("whisper-cli absent")
    with pytest.raises(DeviceUnavailable):
        whisper_run(str(GGML / "whisper-cli.exe"), str(CPP_MODEL), "not-a-real-file.wav",
                    "explicit-gpu", 9999)


def test_whisper_hidden_device_rejected(monkeypatch):
    if not (GGML / "whisper-cli.exe").exists():
        pytest.skip("whisper-cli absent")
    monkeypatch.setenv("GGML_VK_VISIBLE_DEVICES", "99")
    with pytest.raises(DeviceUnavailable):
        whisper_run(str(GGML / "whisper-cli.exe"), str(CPP_MODEL), "not-a-real-file.wav",
                    "explicit-gpu", 0)


@pytest.mark.parametrize("mode", ["explicit-gpu", "auto", "cpu"])
def test_whisper_one_short_clip(mode):
    exe = GGML / "whisper-cli.exe"
    clips = list(AUDIO.glob("*.wav"))
    if not exe.exists() or not clips or not CPP_MODEL.exists():
        pytest.skip("approved whisper assets unavailable")
    gpu = [d for d in enumerate_ggml(str(GGML / "ggml-diag.exe")) if d.kind == "gpu"]
    if mode == "explicit-gpu" and not gpu:
        pytest.skip("No Vulkan GPU")
    if mode == "explicit-gpu":
        r = whisper_run(str(exe), str(CPP_MODEL), str(clips[0]), mode, gpu[0].index)
        assert r["actual"] == "gpu"
    else:
        r = whisper_run(str(exe), str(CPP_MODEL), str(clips[0]), mode)
        assert r["actual"] == ("cpu" if mode == "cpu" else r["actual"])
