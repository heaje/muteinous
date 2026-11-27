"""Small policy-enforcing prototype for DirectML and whisper.cpp Vulkan."""
from __future__ import annotations

from dataclasses import dataclass
import json
import re
import subprocess
from pathlib import Path
from typing import Literal


class DeviceError(RuntimeError): pass
class DeviceUnavailable(DeviceError): pass
class FallbackDetected(DeviceError): pass


@dataclass(frozen=True)
class Device:
    key: str
    name: str
    kind: Literal["gpu", "cpu"]
    memory_mb: int | None
    backend: str
    index: int
    integrated: bool | None


def enumerate_ort(ort) -> list[Device]:
    out = []
    for ep in ort.get_ep_devices():
        d = ep.device
        meta = dict(d.metadata or {})
        name = meta.get("Description", f"device-{d.device_id}")
        kind = "gpu" if "GPU" in str(d.type).upper() else "cpu"
        mem = re.search(r"([\d.]+)\s*MB", meta.get("DxgiVideoMemory", ""))
        idx = int(meta.get("DxgiAdapterNumber", d.device_id if kind == "gpu" else 0))
        # PCI vendor/device identity is stable enough for matching this adapter;
        # adapter ordinal is retained only as the runtime's invocation index.
        key = f"{ep.ep_name}:{int(d.vendor_id):04x}:{int(d.device_id):04x}:{name.casefold()}"
        out.append(Device(key, name, kind, int(float(mem.group(1))) if mem else None,
                          ep.ep_name, idx, meta.get("Discrete") == "0" if "Discrete" in meta else None))
    return out


def enumerate_ggml(exe: str) -> list[Device]:
    p = subprocess.run([exe, "list"], capture_output=True, text=True, check=True)
    out = []
    for ln in p.stdout.splitlines() + p.stderr.splitlines():
        m = re.search(r'device\[(\d+)\]\s+name=(\S+)\s+type=(GPU|CPU).*?description="([^"]*)".*?memory_total=(\d+)', ln)
        if m:
            i, name, kind, desc, mem = m.groups()
            out.append(Device(f"ggml:{kind.lower()}:{desc.casefold()}", desc.strip(), kind.lower(),
                              int(mem) // (1024 * 1024), "whisper.cpp", int(i),
                              ("uma: 1" in p.stdout or "uma: 1" in p.stderr) if kind == "GPU" else None))
    return out


def ort_session(ort, model: str, mode: str, device_id: int | None = None, run: bool = True):
    """Returns session + verification report. Auto falls back only with reason recorded."""
    if mode == "cpu":
        sess = ort.InferenceSession(model, providers=["CPUExecutionProvider"])
        return sess, {"actual": "cpu", "providers": sess.get_providers()}
    providers = [("DmlExecutionProvider", {"device_id": device_id} if device_id is not None else {}),
                 ("CPUExecutionProvider", {})]
    so = ort.SessionOptions()
    so.enable_mem_pattern = False
    so.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
    if run:
        so.enable_profiling = True
    try:
        sess = ort.InferenceSession(model, sess_options=so, providers=providers)
    except Exception as exc:
        if mode == "auto":
            sess = ort.InferenceSession(model, providers=["CPUExecutionProvider"])
            return sess, {"actual": "cpu", "fallback_reason": f"{type(exc).__name__}: {exc}"}
        raise DeviceUnavailable(str(exc)) from exc
    got = sess.get_providers()
    if mode == "cpu":
        if got != ["CPUExecutionProvider"]:
            raise FallbackDetected(f"CPU requested but providers are {got}")
        return sess, {"actual": "cpu", "providers": got}
    if mode == "explicit-gpu" and "DmlExecutionProvider" not in got:
        raise FallbackDetected(f"GPU requested, but session providers are {got}")
    if mode == "auto" and "DmlExecutionProvider" not in got:
        return sess, {"actual": "cpu", "providers": got, "fallback_reason": "DML absent from session"}
    if run:
        sess.disable_fallback()
        inp = next((i for i in sess.get_inputs() if i.name == "input_features"),
                   sess.get_inputs()[0])
        import numpy as np
        shape = [((80 if "feature" in str(x).lower() else
                   3000 if "sequence" in str(x).lower() or "audio" in str(x).lower() else 1)
                  if not isinstance(x, int) or x <= 0 else x) for x in inp.shape]
        dtype = {"tensor(float)": np.float32, "tensor(float16)": np.float16}.get(inp.type, np.float32)
        try:
            sess.run(None, {inp.name: np.zeros(shape, dtype=dtype)})
        except Exception as exc:
            if mode == "auto":
                cpu = ort.InferenceSession(model, providers=["CPUExecutionProvider"])
                return cpu, {"actual": "cpu", "providers": cpu.get_providers(),
                             "fallback_reason": f"GPU probe/inference failed: {type(exc).__name__}: {exc}"}
            raise FallbackDetected(f"Explicit GPU execution failed: {type(exc).__name__}: {exc}") from exc
        profile = sess.end_profiling()
        profile_text = Path(profile).read_text(encoding="utf-8")
        decoder = json.JSONDecoder()
        events = None
        for pos, char in enumerate(profile_text):
            if char != "[":
                continue
            try:
                candidate, _ = decoder.raw_decode(profile_text[pos:])
            except json.JSONDecodeError:
                continue
            if isinstance(candidate, list):
                events = candidate
                break
        if events is None:
            raise FallbackDetected("ORT profiling output did not contain a JSON event list")
        dml = [e for e in events if "DmlExecutionProvider" in json.dumps(e)]
        Path(profile).unlink(missing_ok=True)
        if mode == "explicit-gpu" and not dml:
            raise FallbackDetected("DML provider present but profiling showed no DML events")
        return sess, {"actual": "gpu" if dml else "unknown", "providers": got, "dml_events": len(dml)}
    return sess, {"actual": "provider-listed-only", "providers": got}


def whisper_run(exe: str, model: str, wav: str, mode: str, device_index: int | None = None):
    exe = str(Path(exe).resolve())
    devices = enumerate_ggml(str(Path(exe).with_name("ggml-diag.exe")))
    gpus = [d for d in devices if d.kind == "gpu"]
    if mode == "explicit-gpu":
        if device_index is None or not any(d.index == device_index for d in gpus):
            raise DeviceUnavailable(f"Vulkan device index {device_index} is not available")
        args = ["-dev", str(device_index)]
    elif mode == "cpu":
        args = ["-ng"]
    elif mode == "auto":
        args = ["-dev", str(gpus[0].index)] if gpus else ["-ng"]
    else:
        raise ValueError(mode)
    p = subprocess.run([exe, "-m", model, "-f", wav, *args], capture_output=True, text=True,
                       cwd=str(Path(exe).parent))
    log = p.stdout + "\n" + p.stderr
    if p.returncode:
        raise DeviceError(f"whisper-cli exited {p.returncode}: {log[-2000:]}")
    vulkan = bool(re.search(r"using Vulkan\d+ backend|Vulkan\d+ total size", log, re.I))
    cpu = bool(re.search(r"CPU total size|no GPU found", log, re.I))
    if mode == "explicit-gpu" and (not vulkan or cpu):
        raise FallbackDetected("explicit Vulkan request not verified: " + log[-1000:])
    return {"actual": "gpu" if vulkan and not cpu else "cpu", "log": log}
