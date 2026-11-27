"""Record ONNX Runtime provider/device data and probe Whisper session creation.

This is a diagnostic probe only; it does not claim successful ASR inference.
Run in a disposable runtime-specific environment with HF offline variables set.
"""
from __future__ import annotations

import argparse
import json
import pathlib

import onnxruntime as ort


def device_data(device):
    return {
        "type": str(device.type),
        "vendor": device.vendor,
        "vendor_id": device.vendor_id,
        "device_id": device.device_id,
        "metadata": dict(device.metadata),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", required=True)
    parser.add_argument("--device-id", type=int, default=0)
    args = parser.parse_args()

    result = {
        "ort_version": ort.__version__,
        "available_providers": ort.get_available_providers(),
        "ep_devices": [
            {
                "ep": item.ep_name,
                "ep_metadata": dict(item.ep_metadata),
                "device": device_data(item.device),
            }
            for item in ort.get_ep_devices()
        ] if hasattr(ort, "get_ep_devices") else None,
    }
    opts = ort.SessionOptions()
    opts.enable_mem_pattern = False
    opts.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
    try:
        session = ort.InferenceSession(
            str(pathlib.Path(args.model)),
            sess_options=opts,
            providers=[
                ("DmlExecutionProvider", {"device_id": args.device_id}),
                "CPUExecutionProvider",
            ],
        )
        result["session"] = {
            "status": "created",
            "requested_device_id": args.device_id,
            "providers": session.get_providers(),
            "inputs": [
                {"name": item.name, "type": item.type, "shape": item.shape}
                for item in session.get_inputs()
            ],
        }
    except Exception as error:
        result["session"] = {
            "status": "failed",
            "requested_device_id": args.device_id,
            "exception_type": type(error).__name__,
            "error": str(error),
        }
    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
