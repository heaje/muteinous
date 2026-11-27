"""Update final verification metadata on completed benchmark observations."""
import json
import pathlib

results = pathlib.Path(r"C:\scratch\asr50\results\ort-whisper-turbo\results.jsonl")
pdhs = 2_965_151_744
actual = "DmlExecutionProvider+CPUExecutionProvider (profile-verified mixed; device_id=0)"
rows = [json.loads(line) for line in results.read_text(encoding="utf-8").splitlines() if line]
base = pathlib.Path(r"C:\scratch\asr50\WP12\venv")
footprints = {}
for device in ("cpu", "dml"):
    site = base / device / "Lib" / "site-packages"
    targets = [site / "onnxruntime", *site.glob("onnxruntime*.dist-info")]
    footprints[device] = sum(
        item.stat().st_size for root in targets if root.exists()
        for item in ([root] if root.is_file() else root.rglob("*")) if item.is_file()
    )
for row in rows:
    row["runtime"]["installed_bytes"] = footprints[row["device"]["requested"]]
    if row["device"]["requested"] == "dml":
        row["device"]["actual"] = actual
    if row["run"]["kind"] == "gpu-proof2":
        row["measurements"]["peak_vram_bytes"] = pdhs
        row["measurements"]["peak_vram_method"] = (
            "Windows PDH GPU Process Memory(*) Dedicated Usage; process-filtered PID 15312; ~1 s sampling"
        )
results.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")

for device in ("cpu", "dml"):
    folder = results.parent / device
    for file in folder.glob("*.json"):
        data = json.loads(file.read_text(encoding="utf-8"))
        if device == "dml":
            data["meta"]["actual_device"] = actual
            if data["meta"].get("run_kind") == "gpu-proof2":
                data["meta"]["peak_dedicated_gpu_bytes"] = pdhs
        file.write_text(json.dumps(data, indent=2), encoding="utf-8")
