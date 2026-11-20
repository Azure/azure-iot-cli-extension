# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Display-only ADO run names derived from frozen product metadata."""

import argparse
import os
from pathlib import Path
import re
import runpy


def _values(values, pattern, label):
    if isinstance(values, str):
        raise ValueError(f"{label} must be a sequence, not a string.")
    result = []
    for value in values:
        if not isinstance(value, str) or not re.fullmatch(pattern, value):
            raise ValueError(f"Invalid {label} value.")
        if value not in result:
            result.append(value)
    return result


def _compact(values):
    if not values:
        return ""
    count = min(3, len(values))
    while True:
        label = ", ".join(values[:count])
        if count < len(values):
            label += f" +{len(values) - count}"
        if len(label) <= 80 or count == 1:
            return label
        count -= 1


def format_title(prefix, build_id, version=None, *, scopes=(), regions=(), runtimes=(), channels=(), action=None):
    if prefix not in {"iot", "ops", "clean"} or not re.fullmatch(r"[1-9][0-9]*", str(build_id)):
        raise ValueError("A known product prefix and positive ADO Build ID are required.")
    scopes = _values(scopes, r"[A-Za-z0-9][A-Za-z0-9._-]*", "scope")
    if prefix == "iot":
        if {"HubControl", "HubData"}.issubset(scopes):
            scopes = [scope for scope in scopes if scope not in {"HubControl", "HubData"}] + ["Hub"]
        order = {scope: index for index, scope in enumerate(("DPS", "Hub", "HubControl", "HubData", "ADU", "ADR"))}
        scopes.sort(key=lambda scope: (order.get(scope, len(order)), scope))
    regions = sorted(_values(regions, r"[a-z][a-z0-9]+", "region"))
    runtimes = _values(runtimes, r"[0-9][A-Za-z0-9.+!-]*", "runtime version")
    channels = _values(channels, r"stable|preview", "channel")
    channels = [channel for channel in ("stable", "preview") if channel in channels]
    if action not in {None, "validate", "draft", "release"}:
        raise ValueError("Unsupported release action.")
    if prefix == "clean" and (version is not None or scopes or regions or runtimes or channels or action):
        raise ValueError("Shared cleanup has no CLI under test.")
    title = f"{prefix}-{build_id}"
    if len(title) > 255:
        raise ValueError("The run title exceeds the ADO name limit.")
    if version is None:
        return title
    if not isinstance(version, str) or not re.fullmatch(r"[0-9][A-Za-z0-9.+!-]*", version):
        raise ValueError("The frozen CLI version is missing or unsafe.")
    groups = [version, _compact(scopes), _compact(regions)]
    if runtimes:
        groups.append("runtime " + ", ".join(runtimes))
    groups.extend([", ".join(channels), action])
    title += "".join(f" ({group})" for group in groups if group)
    if len(title) > 255:
        raise ValueError("The run title exceeds the ADO name limit.")
    return title


def wheel_version(path):
    path = Path(path)
    wheels = list(path.rglob("*.whl")) if path.is_dir() else [path]
    if len(wheels) != 1 or not wheels[0].is_file():
        raise ValueError("Exactly one frozen candidate wheel is required for its run title.")
    release = runpy.run_path(str(Path(__file__).with_name("release_pipeline.py")))
    return release["wheel_metadata"](wheels[0])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prefix", choices=["iot", "ops", "clean"], required=True)
    parser.add_argument("--wheel", type=Path)
    args = parser.parse_args()
    version = wheel_version(args.wheel) if args.wheel is not None else None
    print(f"##vso[build.updatebuildnumber]{format_title(args.prefix, os.environ['BUILD_BUILDID'], version)}")


if __name__ == "__main__":
    main()
