"""Adapt corpus-v3's Windows SAPI recipe to WP23's independently written text."""
import importlib.util
import json
import sys
from pathlib import Path

sys.dont_write_bytecode = True
source = Path(r"C:\code\muteinous-spike50\spike\asr50\benchmark\corpus_v3\generate_corpus_v3.py")
spec = importlib.util.spec_from_file_location("corpus_v3_sapi", source)
module = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(module)
rows = json.loads(Path(r"C:\scratch\asr50\WP23\labels\wp23_authored.json").read_text(encoding="utf-8"))
module.SENTENCES = [row["sentence"] for row in rows]
sys.argv = [str(source), "--output-root", r"C:\scratch\asr50\WP23\corpus",
            "--sapi-cache", r"C:\scratch\asr50\WP23\sapi_cache"]
module.main()
