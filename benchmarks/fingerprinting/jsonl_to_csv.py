"""Flatten benchmark JSONL records into a CSV suitable for summaries."""

import argparse
import csv
import json
from pathlib import Path


def convert(source, destination):
    records = [
        json.loads(line) for line in source.read_text(encoding="utf-8").splitlines()
    ]
    run = 0
    for row in records:
        if row.get("record") == "environment":
            run += 1
        row["run_id"] = f"run-{run:02d}"
    trials = {
        (
            row["run_id"],
            row["workload"],
            row["repeat"],
            row["algorithm"],
            row["workers"],
            row["hash_threads"],
        ): row
        for row in records
        if row.get("record") == "trial" and not row["contention"]
    }
    for row in records:
        if row.get("record") != "trial":
            continue
        key = (
            row["run_id"],
            row["workload"],
            row["repeat"],
            row["algorithm"],
            row["workers"],
            row["hash_threads"],
        )
        solo = trials.get(key)
        row["candidate_solo_MB_s"] = solo["MB_s"] if solo else None
        row["candidate_slowdown"] = (
            solo["MB_s"] / row["MB_s"]
            if row["contention"] and solo and row["MB_s"]
            else None
        )
        row["competitor_slowdown"] = (
            row["competitor_solo_MB_s"] / row["competitor_MB_s"]
            if row["contention"] and row.get("competitor_MB_s")
            else None
        )
    columns = sorted({key for row in records for key in row})
    with destination.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        for row in records:
            writer.writerow(
                {
                    key: json.dumps(value, sort_keys=True)
                    if isinstance(value, (dict, list))
                    else value
                    for key, value in row.items()
                }
            )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("jsonl", type=Path)
    parser.add_argument("csv", type=Path)
    args = parser.parse_args()
    convert(args.jsonl, args.csv)


if __name__ == "__main__":
    main()
