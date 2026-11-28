"""Optional deterministic checks of benchmark methodology; not hardware tests."""

import csv
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from benchmark import BLOCK, ContentionWindow, competitor_rate
from jsonl_to_csv import convert


class MethodologyTests(unittest.TestCase):
    def test_window_counts_only_complete_in_interval_blocks(self):
        window = ContentionWindow()
        window.record_completed(0.0)
        window.ready.set()
        with patch("benchmark.time.perf_counter", side_effect=[10.0, 11.0]):
            self.assertEqual(window.begin(), 10.0)
            window.record_completed(9.9)  # Started before the timed interval.
            window.record_completed(10.1)
            window.record_completed(10.2)
            self.assertEqual(window.finish(), (11.0, 2 * BLOCK))
        window.record_completed(10.9)  # Completed/recorded after the boundary.
        self.assertEqual(window.total, 2 * BLOCK)

    def test_insufficient_overlap_has_no_rate(self):
        self.assertIsNone(competitor_rate(0, 1.0))
        self.assertIsNone(competitor_rate(19 * BLOCK, 1.0))
        self.assertIsNone(competitor_rate(100 * BLOCK, 0.01))
        self.assertEqual(competitor_rate(20 * BLOCK, 1.0), 20 * BLOCK / 1e6)

    def test_invalid_contention_does_not_produce_slowdown(self):
        common = dict(
            record="trial", workload="synthetic", repeat=0,
            algorithm="production-blake3", workers=1, hash_threads=1,
            cache_mode="cold-eviction-reported", MB_s=100,
        )
        rows = [
            dict(record="environment"),
            common | dict(contention=False),
            common | dict(
                contention=True, contention_valid=False,
                competitor_MB_s=None, competitor_solo_MB_s=100,
            ),
        ]
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.jsonl"
            dest = Path(directory) / "summary.csv"
            source.write_text(
                "\n".join(json.dumps(row) for row in rows), encoding="utf-8"
            )
            convert(source, dest)
            with dest.open(encoding="utf-8", newline="") as stream:
                trial = list(csv.DictReader(stream))[-1]
        self.assertEqual(trial["candidate_slowdown"], "")
        self.assertEqual(trial["competitor_slowdown"], "")


if __name__ == "__main__":
    unittest.main()
