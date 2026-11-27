"""Summarize ONNX Runtime per-node profile provider and operator placement."""
import collections
import json
import pathlib
import sys

for filename in sys.argv[1:]:
    events = json.loads(pathlib.Path(filename).read_text(encoding="utf-8"))
    counts = collections.Counter()
    times = collections.Counter()
    operators = collections.defaultdict(collections.Counter)
    for event in events:
        args = event.get("args", {})
        if event.get("cat") != "Node" or "provider" not in args:
            continue
        provider = args["provider"]
        op = args.get("op_name", event.get("name", "unknown"))
        counts[provider] += 1
        operators[provider][op] += 1
        times[provider] += event.get("dur", 0)
    print(json.dumps({"profile": filename, "node_events": dict(counts),
                      "provider_operator_counts": {p: dict(c) for p, c in operators.items()},
                      "provider_duration_us": dict(times)}, indent=2))
