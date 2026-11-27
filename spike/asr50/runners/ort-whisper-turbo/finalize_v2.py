"""Fill runtime wheel footprint metadata in v2 records without rerunning inference."""
import json
import pathlib

base = pathlib.Path(r"C:\scratch\asr50\WP12\venv")
footprint = {}
for device in ("cpu", "dml"):
    site = base / device / "Lib" / "site-packages"
    roots = [site / "onnxruntime", *site.glob("onnxruntime*.dist-info")]
    footprint[device] = sum(
        item.stat().st_size for root in roots if root.exists()
        for item in ([root] if root.is_file() else root.rglob("*")) if item.is_file()
    )
output = pathlib.Path(r"C:\scratch\asr50\results_v2\ort-whisper-turbo")
records_file = output / "results.jsonl"
records = [json.loads(line) for line in records_file.read_text(encoding="utf-8").splitlines() if line]
for record in records:
    record["runtime"]["installed_bytes"] = footprint[record["device"]["requested"]]
records_file.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records),
                        encoding="utf-8")
