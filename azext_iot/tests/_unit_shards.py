# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Deterministic unit-file balancing and fail-closed aggregation of four serial pytest jobs."""

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys

COUNT = 4
PROFILE = Path(__file__).with_name("unit_test_durations.json")
ARTIFACTS = ("coverage.dat", "junit.xml")


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write(path, value, *, exclusive=False):
    with Path(path).open("x" if exclusive else "w", encoding="utf-8") as stream:
        stream.write(json.dumps(value, indent=2, sort_keys=True) + "\n")


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def file_digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def partition(files, profile):
    files = sorted(set(files))
    weights = {name: profile["seconds"].get(name, profile["default_seconds"]) for name in files}
    if len(files) < COUNT or any(not isinstance(w, (int, float)) or not math.isfinite(w) or w <= 0 for w in weights.values()):
        raise ValueError("Four nonempty shards require valid positive file-duration weights.")
    loads, shards = [0.0] * COUNT, [[] for _ in range(COUNT)]
    for name in sorted(files, key=lambda name: (-weights[name], name)):
        index = min(range(COUNT), key=lambda index: (loads[index], index))
        shards[index].append(name)
        loads[index] += weights[name]
    return [sorted(shard) for shard in shards]


def context():
    return {"build": os.environ["UNIT_RUN_ID"], "commit": os.environ["UNIT_COMMIT"]}


def python_series(version):
    match = re.fullmatch(r"([0-9]+\.[0-9]+)\.[0-9]+", version) if isinstance(version, str) else None
    if match is None:
        raise ValueError("Unit shard Python version must have a major, minor and patch number.")
    return match.group(1)


def validate(records, expected_context, profile):
    if len(records) != COUNT or {r["shard"] for r in records} != set(range(1, COUNT + 1)):
        raise ValueError("Exactly four distinct unit shards are required.")
    if len({python_series(record["python"]) for record in records}) != 1:
        raise ValueError("Unit shards must use the same Python major/minor version.")
    inventory = records[0]["inventory"]
    if not inventory or inventory != sorted(set(inventory)):
        raise ValueError("Full unit collection is empty or duplicated.")
    plan = partition([node.split("::", 1)[0] for node in inventory], profile)
    selected = []
    for record in records:
        expected = [node for node in inventory if node.split("::", 1)[0] in plan[record["shard"] - 1]]
        if (record.get("schema") != 1 or record["context"] != expected_context
                or record["profile"] != digest(profile)
                or record["inventory"] != inventory or record["selected"] != expected
                or record["finished"] is not True or record["exitstatus"] != 0
                or set(record["reports"]) != set(expected)):
            raise ValueError("Unit shard identity, collection, selection or terminal execution is invalid.")
        for stages in record["reports"].values():
            setup_skip = stages.get("setup") == ["skipped"]
            if (stages.get("teardown") != ["passed"]
                    or set(stages) != ({"setup", "teardown"} if setup_skip else {"setup", "call", "teardown"})
                    or not setup_skip and (stages.get("setup") != ["passed"]
                                           or stages.get("call") not in (["passed"], ["skipped"]))):
                raise ValueError("A unit case failed or has missing/duplicate execution stages.")
        selected.extend(record["selected"])
    if sorted(selected) != inventory:
        raise ValueError("Unit shards omit or duplicate cases.")
    return len(inventory)


def aggregate(history, output):
    latest = {}
    for folder in Path(history).glob("unit-shard-*"):
        match = re.fullmatch(r"unit-shard-([1-4])-([1-9][0-9]*)", folder.name)
        if not match or not folder.is_dir():
            raise ValueError("Unexpected unit-shard artifact.")
        shard, attempt = map(int, match.groups())
        if shard not in latest or attempt > latest[shard][0]:
            latest[shard] = (attempt, folder)
    records, coverage = [], []
    for shard, (attempt, folder) in sorted(latest.items()):
        record = read(folder / "receipt.json")
        if record["shard"] != shard or record["attempt"] != attempt:
            raise ValueError("Unit artifact name disagrees with its receipt.")
        if record.get("artifacts") != {name: file_digest(folder / name) for name in ARTIFACTS}:
            raise ValueError("Unit results/coverage are missing or changed.")
        records.append(record)
        coverage.append(str((folder / "coverage.dat").resolve()))
    count = validate(records, context(), read(PROFILE))
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    subprocess.run([sys.executable, "-m", "coverage", "combine", "--keep", *coverage], check=True,
                   env=dict(os.environ, COVERAGE_FILE=str(output / ".coverage")))
    totals = {}
    for record in records:
        for name, seconds in record["durations"].items():
            totals[name] = totals.get(name, 0) + seconds
    write(output / "timings.json", {"default_seconds": 1, "seconds": totals})
    write(output / "summary.json", {
        "context": context(), "tests": count,
        "shards": [{"shard": r["shard"], "attempt": r["attempt"], "tests": len(r["selected"]),
                    "seconds": r["seconds"], "python": r["python"]} for r in records],
    })
    print(f"Verified all {count} unit cases exactly once across four shards; coverage combined.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--history", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    aggregate(args.history, args.output)
